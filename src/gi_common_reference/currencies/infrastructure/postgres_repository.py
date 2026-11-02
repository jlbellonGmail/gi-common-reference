"""Adaptador de Postgres para la incorporación de Currency (psycopg 3 con SQL explícito, D16, D17).

Cada transacción toma el lock exclusivo de Currency y locks compartidos sobre los de Locale y
Countries: ni un locale ni un país cambian mientras se valida contra ellos (RF-13, RF-19, RF-40).
Lee `reference.locale`, `reference.country` y sus snapshots del mismo schema; no importa código de
`locales`, `regions` ni `countries` (RNF-6).
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date
from typing import Any

import psycopg
from psycopg import errors
from psycopg.types.json import Jsonb

from gi_common_reference.currencies.domain.errors import (
    ConstraintRejected,
    PersistenceError,
    describe_error,
)
from gi_common_reference.currencies.domain.model import (
    CatalogState,
    CountryCatalog,
    CountryCurrencyRecord,
    CountryInfo,
    CurrencyRecord,
    LocaleCatalog,
    LocaleInfo,
    NameRecord,
)
from gi_common_reference.currencies.domain.ports import IntegrityViolation
from gi_common_reference.currencies.domain.snapshot import HistoricalSnapshot
from gi_common_reference.currencies.infrastructure.conninfo import validate_conninfo

LOCK_NAME = "gi-common-reference.currencies.incorporation"
LOCALES_LOCK_NAME = "gi-common-reference.locales.incorporation"  # el que toma Locale (D12 de 001)
COUNTRIES_LOCK_NAME = "gi-common-reference.countries.incorporation"  # el que toma Countries (D15)


class PostgresCurrencyRepository:
    """Cada `transaction()` abre una conexión, toma los locks y confirma o deshace todo junto."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = validate_conninfo(conninfo)

    @contextmanager
    def transaction(self) -> Iterator["PostgresCurrencyTransaction"]:
        """Una constraint violada sale como `ConstraintRejected` (con su nombre, D17); los demás
        errores del driver, como `PersistenceError` con solo tipo y SQLSTATE."""
        try:
            with psycopg.connect(self._conninfo) as connection:  # commit al salir; si no, rollback
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [LOCK_NAME]
                )
                for shared in (LOCALES_LOCK_NAME, COUNTRIES_LOCK_NAME):
                    connection.execute(
                        "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))", [shared]
                    )
                yield PostgresCurrencyTransaction(connection)
        except errors.IntegrityError as error:
            raise ConstraintRejected(error.diag.constraint_name, error.sqlstate) from None
        except psycopg.Error as error:
            raise PersistenceError(describe_error(error)) from None

    @contextmanager
    def inspect(self) -> Iterator["PostgresCatalogView"]:
        """Vista de solo lectura sobre una instantánea consistente; sin locks (D22)."""
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
            "SELECT snapshot_version, content_digest FROM reference.currency_snapshot "
            "ORDER BY snapshot_version"
        ).fetchall()
        return [HistoricalSnapshot(version, digest) for version, digest in rows]

    def current_state(self) -> CatalogState:
        execute = self._connection.execute
        currencies = execute(
            "SELECT currency_id::text, alphabetic_code, numeric_code, minor_units, fund_code, "
            "status, replacement_currency_ids::text[] FROM reference.currency "
            "ORDER BY currency_id"
        ).fetchall()
        names = execute(
            "SELECT currency_id::text, locale_id::text, name FROM reference.currency_locale "
            "ORDER BY currency_id, locale_id"
        ).fetchall()
        associations = execute(
            "SELECT country_currency_id::text, country_id::text, currency_id::text, status, "
            "valid_from, valid_to FROM reference.country_currency ORDER BY country_currency_id"
        ).fetchall()
        return CatalogState(
            currencies=tuple(_currency(row) for row in currencies),
            names=tuple(NameRecord(*row) for row in names),
            associations=tuple(_association(row) for row in associations),
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

    def country_catalog(self) -> CountryCatalog:
        execute = self._connection.execute
        versions = [
            row[0]
            for row in execute(
                "SELECT snapshot_version FROM reference.country_snapshot ORDER BY snapshot_version"
            ).fetchall()
        ]
        countries = execute(
            "SELECT country_id::text, status FROM reference.country ORDER BY country_id"
        ).fetchall()
        return CountryCatalog(
            max(versions) if versions else None,
            frozenset(versions),
            tuple(CountryInfo(*row) for row in countries),
        )

    def integrity_violations(self) -> Sequence[IntegrityViolation]:
        rows = self._connection.execute(
            "SELECT country_currency_id::text, country_id::text, currency_id::text, "
            "country_not_active, currency_not_active "
            "FROM reference.country_currency_integrity_violation ORDER BY country_currency_id"
        ).fetchall()
        return [IntegrityViolation(*row) for row in rows]


def _currency(row: tuple[Any, ...]) -> CurrencyRecord:
    """La fila de `reference.currency`; los reemplazos salen del arreglo ascendente (D-17)."""
    return CurrencyRecord(
        currency_id=row[0],
        alphabetic_code=row[1],
        numeric_code=row[2],
        minor_units=row[3],
        fund_code=row[4],
        status=row[5],
        replacement_currency_ids=tuple(sorted(row[6] or ())),
    )


def _association(row: tuple[Any, ...]) -> CountryCurrencyRecord:
    return CountryCurrencyRecord(
        country_currency_id=row[0],
        country_id=row[1],
        currency_id=row[2],
        status=row[3],
        valid_from=row[4] if isinstance(row[4], date) else None,
        valid_to=row[5] if isinstance(row[5], date) else None,
    )


class PostgresCurrencyTransaction(PostgresCatalogView):
    def insert_snapshot(
        self,
        document: Mapping[str, Any],
        locale_snapshot_version: int,
        country_current_snapshot_version: int,
        policy_version: int,
    ) -> None:
        self._connection.execute(
            "INSERT INTO reference.currency_snapshot (snapshot_version, content_digest, "
            "locale_snapshot_version, country_snapshot_version, country_current_snapshot_version, "
            "required_locales_version, provenance, artifact) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [
                document["snapshot_version"],
                document["content_digest"],
                locale_snapshot_version,
                document["country_snapshot_version"],
                country_current_snapshot_version,
                policy_version,
                Jsonb(document["provenance"]),
                Jsonb(document),
            ],
        )

    def insert_currencies(self, currencies: Sequence[CurrencyRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.currency (currency_id, alphabetic_code, numeric_code, "
                "minor_units, fund_code, status, replacement_currency_ids, "
                "first_snapshot_version, last_changed_snapshot_version) "
                "VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::uuid[], %s, %s)",
                [
                    (
                        c.currency_id,
                        c.alphabetic_code,
                        c.numeric_code,
                        c.minor_units,
                        c.fund_code,
                        c.status,
                        list(c.replacement_currency_ids),
                        version,
                        version,
                    )
                    for c in currencies
                ],
            )

    def update_currencies(self, currencies: Sequence[CurrencyRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE reference.currency SET minor_units = %s, fund_code = %s, status = %s, "
                "replacement_currency_ids = %s::uuid[], last_changed_snapshot_version = %s "
                "WHERE currency_id = %s::uuid",
                [
                    (
                        c.minor_units,
                        c.fund_code,
                        c.status,
                        list(c.replacement_currency_ids),
                        version,
                        c.currency_id,
                    )
                    for c in currencies
                ],
            )

    def insert_names(self, names: Sequence[NameRecord]) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.currency_locale (currency_id, locale_id, name) "
                "VALUES (%s::uuid, %s::uuid, %s)",
                [(n.currency_id, n.locale_id, n.name) for n in names],
            )

    def update_names(self, names: Sequence[NameRecord]) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE reference.currency_locale SET name = %s "
                "WHERE currency_id = %s::uuid AND locale_id = %s::uuid",
                [(n.name, n.currency_id, n.locale_id) for n in names],
            )

    def insert_associations(
        self, associations: Sequence[CountryCurrencyRecord], version: int
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.country_currency (country_currency_id, country_id, "
                "currency_id, status, valid_from, valid_to, first_snapshot_version, "
                "last_changed_snapshot_version) "
                "VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s)",
                [
                    (
                        a.country_currency_id,
                        a.country_id,
                        a.currency_id,
                        a.status,
                        a.valid_from,
                        a.valid_to,
                        version,
                        version,
                    )
                    for a in associations
                ],
            )

    def update_associations(
        self, associations: Sequence[CountryCurrencyRecord], version: int
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE reference.country_currency SET status = %s, valid_from = %s, "
                "valid_to = %s, last_changed_snapshot_version = %s "
                "WHERE country_currency_id = %s::uuid",
                [
                    (a.status, a.valid_from, a.valid_to, version, a.country_currency_id)
                    for a in associations
                ],
            )

    def touch_currencies(self, currency_ids: Sequence[str], version: int) -> None:
        if not currency_ids:
            return
        self._connection.execute(
            "UPDATE reference.currency SET last_changed_snapshot_version = %s "
            "WHERE currency_id = ANY(%s::uuid[])",
            [version, list(currency_ids)],
        )

    def check_constraints(self) -> None:
        """Evalúa ahora las constraints diferidas: el estado final completo (RF-3, RF-19, RF-45)."""
        self._connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
