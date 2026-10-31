"""Adaptador de lectura de Countries sobre Postgres: la API se conecta con `reference_reader`.

El nombre sale de `country_locale` para el `locale_id` pedido, sin fallback a otro locale (RF-38).
La existencia del `locale_id` se consulta en `reference.locale`. Solo se lee el catálogo persistido:
nunca una fuente externa (RF-26, RF-37).
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg

from gi_common_reference.countries.domain.errors import describe_error
from gi_common_reference.countries.domain.model import CodeKind, CountryRecord, FlagRecord
from gi_common_reference.countries.domain.ports import CountryView, ReaderUnavailable
from gi_common_reference.countries.infrastructure.conninfo import validate_conninfo

COUNTRIES = (
    "SELECT c.country_id::text, c.alpha2, c.alpha3, c.numeric_code, c.region_id::text, "
    "c.subregion_id::text, c.calling_code, c.status, c.replacement_country_id::text, "
    "n.name, n.official_name "
    "FROM reference.country c LEFT JOIN reference.country_locale n "
    "ON n.country_id = c.country_id AND n.locale_id = %(locale)s::uuid "
)
# Columna por tipo de código: valores fijos del dominio, nunca texto del consumidor.
CODE_COLUMNS: dict[CodeKind, str] = {
    "alpha2": "c.alpha2",
    "alpha3": "c.alpha3",
    "numeric_code": "c.numeric_code",
}


class PostgresCountryReader:
    """Una conexión por sesión, de solo lectura y con una instantánea consistente."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = validate_conninfo(conninfo)

    @contextmanager
    def session(self) -> Iterator["PostgresCountrySession"]:
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
                yield PostgresCountrySession(connection)
        except psycopg.OperationalError as error:
            raise ReaderUnavailable(describe_error(error)) from None


class PostgresCountrySession:
    def __init__(self, connection: "psycopg.Connection[Any]") -> None:
        self._connection = connection

    def snapshot_version(self) -> int | None:
        row = self._connection.execute(
            "SELECT max(snapshot_version) FROM reference.country_snapshot"
        ).fetchone()
        return None if row is None else row[0]

    def locale_exists(self, locale_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM reference.locale WHERE locale_id = %s::uuid", [locale_id]
        ).fetchone()
        return row is not None

    def countries(
        self,
        status: str | None,
        region_id: str | None,
        subregion_id: str | None,
        locale_id: str | None,
    ) -> Sequence[CountryView]:
        rows = self._connection.execute(
            COUNTRIES + "WHERE (%(status)s::text IS NULL OR c.status = %(status)s::text) "
            "AND (%(region)s::uuid IS NULL OR c.region_id = %(region)s::uuid) "
            "AND (%(subregion)s::uuid IS NULL OR c.subregion_id = %(subregion)s::uuid) "
            'ORDER BY c.alpha2 COLLATE "C", c.country_id',
            {
                "locale": locale_id,
                "status": status,
                "region": region_id,
                "subregion": subregion_id,
            },
        ).fetchall()
        return [_view(row) for row in rows]

    def country_by_id(self, country_id: str, locale_id: str | None) -> CountryView | None:
        row = self._connection.execute(
            COUNTRIES + "WHERE c.country_id = %(id)s::uuid",
            {"locale": locale_id, "id": country_id},
        ).fetchone()
        return None if row is None else _view(row)

    def country_by_code(
        self, kind: CodeKind, code: str, locale_id: str | None
    ) -> CountryView | None:
        column = CODE_COLUMNS[kind]
        # D6: la `active` que tiene el código; si no, la `inactive` que lo obtuvo más recientemente.
        row = self._connection.execute(
            COUNTRIES + f"WHERE {column} = %(code)s "
            "ORDER BY (c.status = 'active') DESC, c.codes_snapshot_version DESC, c.country_id "
            "LIMIT 1",
            {"locale": locale_id, "code": code},
        ).fetchone()
        return None if row is None else _view(row)

    def flag(self, country_id: str) -> FlagRecord | None:
        row = self._connection.execute(
            "SELECT country_id::text, asset_path, sha256, exception_reason "
            "FROM reference.country_flag WHERE country_id = %s::uuid",
            [country_id],
        ).fetchone()
        return None if row is None else FlagRecord(*row)


def _view(row: tuple[Any, ...]) -> CountryView:
    return CountryView(CountryRecord(*row[:9]), row[9], row[10])
