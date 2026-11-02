"""Adaptador de lectura de Currency sobre Postgres: la API se conecta con `reference_reader`.

El nombre sale de `currency_locale` para el `locale_id` pedido, sin fallback a otro locale (RF-15).
La existencia del `locale_id` se consulta en `reference.locale` y la del Country en
`reference.country`: Currency solo lee el catálogo de Countries, nunca lo redefine (RF-20). Solo se
lee el catálogo persistido: nunca una fuente externa (RF-42).
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from typing import Any

import psycopg

from gi_common_reference.currencies.domain.errors import describe_error
from gi_common_reference.currencies.domain.model import CountryCurrencyRecord, CurrencyRecord
from gi_common_reference.currencies.domain.ports import (
    AssociationView,
    CurrencyView,
    ReaderUnavailable,
)
from gi_common_reference.currencies.infrastructure.conninfo import validate_conninfo

CURRENCY_COLUMNS = (
    "c.currency_id::text, c.alphabetic_code, c.numeric_code, c.minor_units, c.fund_code, "
    "c.status, c.replacement_currency_ids::text[], n.name"
)
CURRENCIES = (
    f"SELECT {CURRENCY_COLUMNS} FROM reference.currency c "
    "LEFT JOIN reference.currency_locale n "
    "ON n.currency_id = c.currency_id AND n.locale_id = %(locale)s::uuid "
)
ASSOCIATIONS = (
    "SELECT a.country_currency_id::text, a.country_id::text, a.status, a.valid_from, a.valid_to, "
    f"{CURRENCY_COLUMNS} FROM reference.country_currency a "
    "JOIN reference.currency c ON c.currency_id = a.currency_id "
    "LEFT JOIN reference.currency_locale n "
    "ON n.currency_id = c.currency_id AND n.locale_id = %(locale)s::uuid "
)


class PostgresCurrencyReader:
    """Una conexión por sesión, de solo lectura y con una instantánea consistente."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = validate_conninfo(conninfo)

    @contextmanager
    def session(self) -> Iterator["PostgresCurrencySession"]:
        """Cualquier error del driver al conectar, y los de conexión perdida a mitad de sesión,
        salen como `ReaderUnavailable` con solo tipo y SQLSTATE: su texto puede citar la conexión.
        Los demás errores de las consultas no se traducen."""
        try:
            connection = psycopg.connect(self._conninfo)
        except psycopg.Error as error:
            raise ReaderUnavailable(describe_error(error)) from None
        try:
            with connection:
                connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                connection.read_only = True
                yield PostgresCurrencySession(connection)
        except psycopg.OperationalError as error:
            raise ReaderUnavailable(describe_error(error)) from None


class PostgresCurrencySession:
    def __init__(self, connection: "psycopg.Connection[Any]") -> None:
        self._connection = connection

    def snapshot_version(self) -> int | None:
        row = self._connection.execute(
            "SELECT max(snapshot_version) FROM reference.currency_snapshot"
        ).fetchone()
        return None if row is None else row[0]

    def locale_exists(self, locale_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM reference.locale WHERE locale_id = %s::uuid", [locale_id]
        ).fetchone()
        return row is not None

    def country_exists(self, country_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM reference.country WHERE country_id = %s::uuid", [country_id]
        ).fetchone()
        return row is not None

    def currencies(
        self, include_inactive: bool, exclude_funds: bool, locale_id: str | None
    ) -> Sequence[CurrencyView]:
        rows = self._connection.execute(
            CURRENCIES + "WHERE (%(inactive)s OR c.status = 'active') "
            "AND (NOT %(funds)s OR NOT c.fund_code) "
            'ORDER BY c.alphabetic_code COLLATE "C", c.currency_id',
            {"locale": locale_id, "inactive": include_inactive, "funds": exclude_funds},
        ).fetchall()
        return [_view(row) for row in rows]

    def currency_by_id(self, currency_id: str, locale_id: str | None) -> CurrencyView | None:
        row = self._connection.execute(
            CURRENCIES + "WHERE c.currency_id = %(id)s::uuid",
            {"locale": locale_id, "id": currency_id},
        ).fetchone()
        return None if row is None else _view(row)

    def currency_by_code(self, code: str, locale_id: str | None) -> CurrencyView | None:
        row = self._connection.execute(
            CURRENCIES + "WHERE c.alphabetic_code = %(code)s",
            {"locale": locale_id, "code": code},
        ).fetchone()
        return None if row is None else _view(row)

    def associations_of_country(
        self, country_id: str, locale_id: str | None
    ) -> Sequence[AssociationView]:
        rows = self._connection.execute(
            ASSOCIATIONS + "WHERE a.country_id = %(id)s::uuid",
            {"locale": locale_id, "id": country_id},
        ).fetchall()
        return [_association(row) for row in rows]

    def associations_of_currency(
        self, currency_id: str, locale_id: str | None
    ) -> Sequence[AssociationView]:
        rows = self._connection.execute(
            ASSOCIATIONS + "WHERE a.currency_id = %(id)s::uuid",
            {"locale": locale_id, "id": currency_id},
        ).fetchall()
        return [_association(row) for row in rows]


def _view(row: tuple[Any, ...]) -> CurrencyView:
    record = CurrencyRecord(
        currency_id=row[0],
        alphabetic_code=row[1],
        numeric_code=row[2],
        minor_units=row[3],
        fund_code=row[4],
        status=row[5],
        replacement_currency_ids=tuple(sorted(row[6] or ())),
    )
    return CurrencyView(record, row[7])


def _association(row: tuple[Any, ...]) -> AssociationView:
    currency = _view(row[5:])
    return AssociationView(
        CountryCurrencyRecord(
            country_currency_id=row[0],
            country_id=row[1],
            currency_id=currency.record.currency_id,
            status=row[2],
            valid_from=row[3] if isinstance(row[3], date) else None,
            valid_to=row[4] if isinstance(row[4], date) else None,
        ),
        currency,
    )
