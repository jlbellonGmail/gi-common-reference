"""Adaptador de Postgres para la incorporación de Units (psycopg 3 con SQL explícito, D12, D13).

Cada transacción toma el lock exclusivo de Units y un lock compartido sobre el de Locale: ningún
locale cambia mientras se valida contra él (RF-19). Lee `reference.locale` y su snapshot del mismo
schema; no importa código de `locales`, `regions`, `countries` ni `currencies` (RNF-5).
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import errors
from psycopg.types.json import Jsonb

from gi_common_reference.units.domain.errors import (
    ConstraintRejected,
    PersistenceError,
    describe_error,
)
from gi_common_reference.units.domain.model import (
    AssociationRecord,
    CatalogState,
    KindNameRecord,
    LocaleCatalog,
    LocaleInfo,
    QuantityKindRecord,
    UnitNameRecord,
    UnitRecord,
)
from gi_common_reference.units.domain.snapshot import HistoricalSnapshot
from gi_common_reference.units.infrastructure.conninfo import validate_conninfo

LOCK_NAME = "gi-common-reference.units.incorporation"
LOCALES_LOCK_NAME = "gi-common-reference.locales.incorporation"  # el que toma Locale (D12 de 001)


class PostgresUnitsRepository:
    """Cada `transaction()` abre una conexión, toma los locks y confirma o deshace todo junto."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = validate_conninfo(conninfo)

    @contextmanager
    def transaction(self) -> Iterator["PostgresUnitsTransaction"]:
        """Una constraint violada sale como `ConstraintRejected` (con su nombre); los demás errores
        del driver, como `PersistenceError` con solo tipo y SQLSTATE."""
        try:
            with psycopg.connect(self._conninfo) as connection:  # commit al salir; si no, rollback
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [LOCK_NAME]
                )
                connection.execute(
                    "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))",
                    [LOCALES_LOCK_NAME],
                )
                yield PostgresUnitsTransaction(connection)
        except errors.IntegrityError as error:
            raise ConstraintRejected(error.diag.constraint_name, error.sqlstate) from None
        except psycopg.Error as error:
            raise PersistenceError(describe_error(error)) from None

    @contextmanager
    def inspect(self) -> Iterator["PostgresCatalogView"]:
        """Vista de solo lectura sobre una instantánea consistente; sin locks."""
        try:
            with psycopg.connect(self._conninfo) as connection:
                connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                connection.read_only = True
                yield PostgresCatalogView(connection)
        except psycopg.Error as error:
            raise PersistenceError(describe_error(error)) from None


class PostgresCatalogView:
    def __init__(self, connection: "psycopg.Connection[Any]") -> None:
        self._connection = connection

    def history(self) -> Sequence[HistoricalSnapshot]:
        rows = self._connection.execute(
            "SELECT snapshot_version, content_digest FROM reference.unit_snapshot "
            "ORDER BY snapshot_version"
        ).fetchall()
        return [HistoricalSnapshot(version, digest) for version, digest in rows]

    def current_state(self) -> CatalogState:
        execute = self._connection.execute
        kinds = execute(
            "SELECT quantity_kind_id::text, code, conversion_type, reference_unit_id::text, "
            "status FROM reference.quantity_kind ORDER BY quantity_kind_id"
        ).fetchall()
        units = execute(
            "SELECT unit_id::text, ucum_code, unece_code, symbol, status "
            "FROM reference.unit ORDER BY unit_id"
        ).fetchall()
        associations = execute(
            'SELECT quantity_kind_id::text, unit_id::text, factor, "offset", status '
            "FROM reference.quantity_kind_unit ORDER BY quantity_kind_id, unit_id"
        ).fetchall()
        kind_names = execute(
            "SELECT quantity_kind_id::text, locale_id::text, name "
            "FROM reference.quantity_kind_locale ORDER BY quantity_kind_id, locale_id"
        ).fetchall()
        unit_names = execute(
            "SELECT unit_id::text, locale_id::text, name, plural "
            "FROM reference.unit_locale ORDER BY unit_id, locale_id"
        ).fetchall()
        return CatalogState(
            quantity_kinds=tuple(QuantityKindRecord(*row) for row in kinds),
            units=tuple(UnitRecord(*row) for row in units),
            associations=tuple(AssociationRecord(*row) for row in associations),
            kind_names=tuple(KindNameRecord(*row) for row in kind_names),
            unit_names=tuple(UnitNameRecord(*row) for row in unit_names),
        )

    def locale_catalog(self) -> LocaleCatalog:
        row = self._connection.execute(
            "SELECT max(snapshot_version) FROM reference.locale_snapshot"
        ).fetchone()
        locales = self._connection.execute(
            "SELECT locale_id::text, code, status FROM reference.locale ORDER BY code"
        ).fetchall()
        return LocaleCatalog(
            None if row is None else row[0], tuple(LocaleInfo(*item) for item in locales)
        )


class PostgresUnitsTransaction(PostgresCatalogView):
    def insert_snapshot(
        self,
        document: Mapping[str, Any],
        locale_snapshot_version: int,
        policy_version: int,
        ucum_table_version: str,
    ) -> None:
        self._connection.execute(
            "INSERT INTO reference.unit_snapshot (snapshot_version, content_digest, "
            "locale_snapshot_version, required_locales_version, ucum_table_version, "
            "provenance, artifact) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                document["snapshot_version"],
                document["content_digest"],
                locale_snapshot_version,
                policy_version,
                ucum_table_version,
                Jsonb(document["provenance"]),
                Jsonb(document),
            ],
        )

    def insert_units(self, units: Sequence[UnitRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.unit (unit_id, ucum_code, unece_code, symbol, status, "
                "first_snapshot_version, last_changed_snapshot_version) "
                "VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)",
                [
                    (u.unit_id, u.ucum_code, u.unece_code, u.symbol, u.status, version, version)
                    for u in units
                ],
            )

    def update_units(self, units: Sequence[UnitRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE reference.unit SET ucum_code = %s, unece_code = %s, symbol = %s, "
                "status = %s, last_changed_snapshot_version = %s WHERE unit_id = %s::uuid",
                [
                    (u.ucum_code, u.unece_code, u.symbol, u.status, version, u.unit_id)
                    for u in units
                ],
            )

    def insert_quantity_kinds(self, kinds: Sequence[QuantityKindRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.quantity_kind (quantity_kind_id, code, conversion_type, "
                "reference_unit_id, status, first_snapshot_version, "
                "last_changed_snapshot_version) "
                "VALUES (%s::uuid, %s, %s, %s::uuid, %s, %s, %s)",
                [
                    (
                        k.quantity_kind_id,
                        k.code,
                        k.conversion_type,
                        k.reference_unit_id,
                        k.status,
                        version,
                        version,
                    )
                    for k in kinds
                ],
            )

    def update_quantity_kinds(self, kinds: Sequence[QuantityKindRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE reference.quantity_kind SET status = %s, "
                "last_changed_snapshot_version = %s WHERE quantity_kind_id = %s::uuid",
                [(k.status, version, k.quantity_kind_id) for k in kinds],
            )

    def insert_associations(self, associations: Sequence[AssociationRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.quantity_kind_unit (quantity_kind_id, unit_id, factor, "
                '"offset", status, first_snapshot_version, last_changed_snapshot_version) '
                "VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)",
                [
                    (a.quantity_kind_id, a.unit_id, a.factor, a.offset, a.status, version, version)
                    for a in associations
                ],
            )

    def update_associations(self, associations: Sequence[AssociationRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                'UPDATE reference.quantity_kind_unit SET factor = %s, "offset" = %s, status = %s, '
                "last_changed_snapshot_version = %s "
                "WHERE quantity_kind_id = %s::uuid AND unit_id = %s::uuid",
                [
                    (a.factor, a.offset, a.status, version, a.quantity_kind_id, a.unit_id)
                    for a in associations
                ],
            )

    def insert_kind_names(self, names: Sequence[KindNameRecord]) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.quantity_kind_locale (quantity_kind_id, locale_id, name) "
                "VALUES (%s::uuid, %s::uuid, %s)",
                [(n.quantity_kind_id, n.locale_id, n.name) for n in names],
            )

    def update_kind_names(self, names: Sequence[KindNameRecord]) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE reference.quantity_kind_locale SET name = %s "
                "WHERE quantity_kind_id = %s::uuid AND locale_id = %s::uuid",
                [(n.name, n.quantity_kind_id, n.locale_id) for n in names],
            )

    def insert_unit_names(self, names: Sequence[UnitNameRecord]) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.unit_locale (unit_id, locale_id, name, plural) "
                "VALUES (%s::uuid, %s::uuid, %s, %s)",
                [(n.unit_id, n.locale_id, n.name, n.plural) for n in names],
            )

    def update_unit_names(self, names: Sequence[UnitNameRecord]) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE reference.unit_locale SET name = %s, plural = %s "
                "WHERE unit_id = %s::uuid AND locale_id = %s::uuid",
                [(n.name, n.plural, n.unit_id, n.locale_id) for n in names],
            )

    def touch_units(self, unit_ids: Sequence[str], version: int) -> None:
        if not unit_ids:
            return
        self._connection.execute(
            "UPDATE reference.unit SET last_changed_snapshot_version = %s "
            "WHERE unit_id = ANY(%s::uuid[])",
            [version, list(unit_ids)],
        )

    def touch_quantity_kinds(self, kind_ids: Sequence[str], version: int) -> None:
        if not kind_ids:
            return
        self._connection.execute(
            "UPDATE reference.quantity_kind SET last_changed_snapshot_version = %s "
            "WHERE quantity_kind_id = ANY(%s::uuid[])",
            [version, list(kind_ids)],
        )

    def check_constraints(self) -> None:
        """Evalúa ahora las constraints diferidas: el estado final completo (RF-8, RF-12)."""
        self._connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
