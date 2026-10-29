"""Adaptador de Postgres para la incorporación de Regions (psycopg 3 con SQL explícito, D11, D13).

Cada transacción toma el lock exclusivo de Regions y un lock compartido sobre el de Locale: así
Locale no cambia mientras se valida contra él (RF-33, RF-38). Lee `reference.locale` y
`reference.locale_snapshot` del mismo schema; no importa código de `locales` (RNF-6).
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import errors
from psycopg.types.json import Jsonb

from gi_common_reference.regions.domain.errors import (
    ConstraintRejected,
    PersistenceError,
    describe_error,
)
from gi_common_reference.regions.domain.model import (
    CatalogState,
    EntityType,
    LocaleCatalog,
    LocaleInfo,
    NameRecord,
    Reclassification,
    Recoding,
    RegionRecord,
    SubregionRecord,
)
from gi_common_reference.regions.domain.snapshot import HistoricalSnapshot
from gi_common_reference.regions.infrastructure.conninfo import validate_conninfo

LOCK_NAME = "gi-common-reference.regions.incorporation"
LOCALES_LOCK_NAME = "gi-common-reference.locales.incorporation"  # el que toma Locale (D12 de 001)

# Al recibir un código distinto, la entidad lo obtuvo en esta versión (D7); sin código, no hay.
CODE_SNAPSHOT = (
    "CASE WHEN %(code)s::text IS NULL THEN NULL "
    "WHEN code IS DISTINCT FROM %(code)s::text THEN %(version)s::bigint "
    "ELSE code_snapshot_version END"
)


class PostgresRegionRepository:
    """Cada `transaction()` abre una conexión, toma los locks y confirma o deshace todo junto."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = validate_conninfo(conninfo)

    @contextmanager
    def transaction(self) -> Iterator["PostgresRegionTransaction"]:
        """Una constraint violada sale como `ConstraintRejected` (con su nombre, D13); los demás
        errores del driver, como `PersistenceError` con solo tipo y SQLSTATE."""
        try:
            with psycopg.connect(self._conninfo) as connection:  # commit al salir; si no, rollback
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [LOCK_NAME]
                )
                connection.execute(
                    "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))",
                    [LOCALES_LOCK_NAME],
                )
                yield PostgresRegionTransaction(connection)
        except errors.IntegrityError as error:
            raise ConstraintRejected(
                error.diag.constraint_name,
                error.sqlstate,
                isinstance(error, errors.ForeignKeyViolation),
            ) from None
        except psycopg.Error as error:
            raise PersistenceError(describe_error(error)) from None


class PostgresRegionTransaction:
    def __init__(self, connection: "psycopg.Connection[Any]") -> None:
        self._connection = connection

    def history(self) -> Sequence[HistoricalSnapshot]:
        rows = self._connection.execute(
            "SELECT snapshot_version, content_digest FROM reference.region_snapshot "
            "ORDER BY snapshot_version"
        ).fetchall()
        return [HistoricalSnapshot(version, digest) for version, digest in rows]

    def current_state(self) -> CatalogState:
        execute = self._connection.execute
        regions = execute(
            "SELECT region_id::text, code, status, replacement_region_id::text "
            "FROM reference.region ORDER BY region_id"
        ).fetchall()
        subregions = execute(
            "SELECT subregion_id::text, region_id::text, code, status, "
            "replacement_subregion_id::text FROM reference.subregion ORDER BY subregion_id"
        ).fetchall()
        region_names = execute(
            "SELECT region_id::text, locale_id::text, name FROM reference.region_locale "
            "ORDER BY region_id, locale_id"
        ).fetchall()
        subregion_names = execute(
            "SELECT subregion_id::text, locale_id::text, name FROM reference.subregion_locale "
            "ORDER BY subregion_id, locale_id"
        ).fetchall()
        history = execute(
            "SELECT 'region', region_id::text, previous_code FROM reference.region_recoding "
            "UNION ALL SELECT 'subregion', subregion_id::text, previous_code "
            "FROM reference.subregion_recoding ORDER BY 1, 2, 3"
        ).fetchall()
        historical: list[tuple[EntityType, str, str]] = [
            ("region" if kind == "region" else "subregion", entity_id, code)
            for kind, entity_id, code in history
        ]
        return CatalogState(
            regions=tuple(RegionRecord(*row) for row in regions),
            subregions=tuple(SubregionRecord(*row) for row in subregions),
            region_names=tuple(NameRecord(*row) for row in region_names),
            subregion_names=tuple(NameRecord(*row) for row in subregion_names),
            historical_codes=tuple(historical),
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

    def insert_snapshot(
        self, document: Mapping[str, Any], locale_snapshot_version: int, policy_version: int
    ) -> None:
        self._connection.execute(
            "INSERT INTO reference.region_snapshot (snapshot_version, content_digest, "
            "locale_snapshot_version, required_locales_version, provenance, artifact) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [
                document["snapshot_version"],
                document["content_digest"],
                locale_snapshot_version,
                policy_version,
                Jsonb(document["provenance"]),
                Jsonb(document),
            ],
        )

    def insert_regions(self, regions: Sequence[RegionRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.region (region_id, code, code_snapshot_version, status, "
                "replacement_region_id, first_snapshot_version) "
                "VALUES (%s::uuid, %s, %s, %s, %s::uuid, %s)",
                [
                    (
                        r.region_id,
                        r.code,
                        None if r.code is None else version,
                        r.status,
                        r.replacement_region_id,
                        version,
                    )
                    for r in regions
                ],
            )

    def update_regions(self, regions: Sequence[RegionRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                f"UPDATE reference.region SET code_snapshot_version = {CODE_SNAPSHOT}, "
                "code = %(code)s, status = %(status)s, "
                "replacement_region_id = %(replacement)s::uuid WHERE region_id = %(id)s::uuid",
                [
                    {
                        "id": r.region_id,
                        "code": r.code,
                        "status": r.status,
                        "replacement": r.replacement_region_id,
                        "version": version,
                    }
                    for r in regions
                ],
            )

    def insert_subregions(self, subregions: Sequence[SubregionRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.subregion (subregion_id, region_id, code, "
                "code_snapshot_version, status, replacement_subregion_id, "
                "first_snapshot_version) VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s::uuid, %s)",
                [
                    (
                        s.subregion_id,
                        s.region_id,
                        s.code,
                        None if s.code is None else version,
                        s.status,
                        s.replacement_subregion_id,
                        version,
                    )
                    for s in subregions
                ],
            )

    def update_subregions(self, subregions: Sequence[SubregionRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                f"UPDATE reference.subregion SET code_snapshot_version = {CODE_SNAPSHOT}, "
                "region_id = %(region)s::uuid, code = %(code)s, status = %(status)s, "
                "replacement_subregion_id = %(replacement)s::uuid "
                "WHERE subregion_id = %(id)s::uuid",
                [
                    {
                        "id": s.subregion_id,
                        "region": s.region_id,
                        "code": s.code,
                        "status": s.status,
                        "replacement": s.replacement_subregion_id,
                        "version": version,
                    }
                    for s in subregions
                ],
            )

    def record_reclassifications(
        self, reclassifications: Sequence[Reclassification], version: int
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.subregion_reclassification (subregion_id, "
                "snapshot_version, previous_region_id, new_region_id) "
                "VALUES (%s::uuid, %s, %s::uuid, %s::uuid)",
                [
                    (r.subregion_id, version, r.previous_region_id, r.new_region_id)
                    for r in reclassifications
                ],
            )

    def record_recodings(self, recodings: Sequence[Recoding], version: int) -> None:
        for kind, table, column in (
            ("region", "region_recoding", "region_id"),
            ("subregion", "subregion_recoding", "subregion_id"),
        ):
            with self._connection.cursor() as cursor:
                cursor.executemany(
                    f"INSERT INTO reference.{table} ({column}, snapshot_version, previous_code, "
                    "new_code, provenance) VALUES (%s::uuid, %s, %s, %s, %s)",
                    [
                        (r.entity_id, version, r.previous_code, r.new_code, Jsonb(r.provenance))
                        for r in recodings
                        if r.entity_type == kind
                    ],
                )

    def insert_names(
        self, region_names: Sequence[NameRecord], subregion_names: Sequence[NameRecord]
    ) -> None:
        for table, column, names in (
            ("region_locale", "region_id", region_names),
            ("subregion_locale", "subregion_id", subregion_names),
        ):
            with self._connection.cursor() as cursor:
                cursor.executemany(
                    f"INSERT INTO reference.{table} ({column}, locale_id, name) "
                    "VALUES (%s::uuid, %s::uuid, %s)",
                    [(n.entity_id, n.locale_id, n.name) for n in names],
                )

    def update_names(
        self, region_names: Sequence[NameRecord], subregion_names: Sequence[NameRecord]
    ) -> None:
        for table, column, names in (
            ("region_locale", "region_id", region_names),
            ("subregion_locale", "subregion_id", subregion_names),
        ):
            with self._connection.cursor() as cursor:
                cursor.executemany(
                    f"UPDATE reference.{table} SET name = %s "
                    f"WHERE {column} = %s::uuid AND locale_id = %s::uuid",
                    [(n.name, n.entity_id, n.locale_id) for n in names],
                )

    def check_constraints(self) -> None:
        """Evalúa ahora las constraints diferidas: el estado final completo (RF-42, RF-35)."""
        self._connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
