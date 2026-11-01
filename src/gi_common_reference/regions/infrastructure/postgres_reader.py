"""Adaptador de lectura de Regions sobre Postgres: la API se conecta con `reference_reader`.

El nombre sale de `region_locale`/`subregion_locale` para el `locale_id` pedido, sin fallback a otro
locale (RF-18). La existencia del `locale_id` se consulta en `reference.locale` (RF-19).
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg

from gi_common_reference.regions.domain.errors import describe_error
from gi_common_reference.regions.domain.model import RegionRecord, SubregionRecord
from gi_common_reference.regions.domain.ports import ReaderUnavailable, RegionView, SubregionView
from gi_common_reference.regions.infrastructure.conninfo import validate_conninfo

REGIONS = (
    "SELECT r.region_id::text, r.code, r.status, r.replacement_region_id::text, n.name "
    "FROM reference.region r LEFT JOIN reference.region_locale n "
    "ON n.region_id = r.region_id AND n.locale_id = %(locale)s::uuid "
)
SUBREGIONS = (
    "SELECT s.subregion_id::text, s.region_id::text, s.code, s.status, "
    "s.replacement_subregion_id::text, n.name "
    "FROM reference.subregion s LEFT JOIN reference.subregion_locale n "
    "ON n.subregion_id = s.subregion_id AND n.locale_id = %(locale)s::uuid "
)
# D7: la `active` que tiene el código; si no, la `inactive` que lo obtuvo más recientemente.
BY_CODE = "ORDER BY ({alias}.status = 'active') DESC, {alias}.code_snapshot_version DESC, {key} "


class PostgresRegionReader:
    """Una conexión por sesión, de solo lectura y con una instantánea consistente."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = validate_conninfo(conninfo)

    @contextmanager
    def session(self) -> Iterator["PostgresRegionSession"]:
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
                yield PostgresRegionSession(connection)
        except psycopg.OperationalError as error:
            raise ReaderUnavailable(describe_error(error)) from None


class PostgresRegionSession:
    def __init__(self, connection: "psycopg.Connection[Any]") -> None:
        self._connection = connection

    def snapshot_version(self) -> int | None:
        row = self._connection.execute(
            "SELECT max(snapshot_version) FROM reference.region_snapshot"
        ).fetchone()
        return None if row is None else row[0]

    def locale_exists(self, locale_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM reference.locale WHERE locale_id = %s::uuid", [locale_id]
        ).fetchone()
        return row is not None

    def regions(self, status: str | None, locale_id: str | None) -> Sequence[RegionView]:
        rows = self._connection.execute(
            REGIONS + "WHERE (%(status)s::text IS NULL OR r.status = %(status)s::text) "
            "ORDER BY r.code NULLS LAST, r.region_id",
            {"locale": locale_id, "status": status},
        ).fetchall()
        return [_region(row) for row in rows]

    def region_by_id(self, region_id: str, locale_id: str | None) -> RegionView | None:
        row = self._connection.execute(
            REGIONS + "WHERE r.region_id = %(id)s::uuid", {"locale": locale_id, "id": region_id}
        ).fetchone()
        return None if row is None else _region(row)

    def region_by_code(self, code: str, locale_id: str | None) -> RegionView | None:
        row = self._connection.execute(
            REGIONS
            + "WHERE r.code = %(code)s "
            + BY_CODE.format(alias="r", key="r.region_id")
            + "LIMIT 1",
            {"locale": locale_id, "code": code},
        ).fetchone()
        return None if row is None else _region(row)

    def subregions(
        self, region_id: str | None, status: str | None, locale_id: str | None
    ) -> Sequence[SubregionView]:
        rows = self._connection.execute(
            SUBREGIONS + "WHERE (%(status)s::text IS NULL OR s.status = %(status)s::text) "
            "AND (%(region)s::uuid IS NULL OR s.region_id = %(region)s::uuid) "
            "ORDER BY s.code NULLS LAST, s.subregion_id",
            {"locale": locale_id, "status": status, "region": region_id},
        ).fetchall()
        return [_subregion(row) for row in rows]

    def subregion_by_id(self, subregion_id: str, locale_id: str | None) -> SubregionView | None:
        row = self._connection.execute(
            SUBREGIONS + "WHERE s.subregion_id = %(id)s::uuid",
            {"locale": locale_id, "id": subregion_id},
        ).fetchone()
        return None if row is None else _subregion(row)

    def subregion_by_code(self, code: str, locale_id: str | None) -> SubregionView | None:
        row = self._connection.execute(
            SUBREGIONS
            + "WHERE s.code = %(code)s "
            + BY_CODE.format(alias="s", key="s.subregion_id")
            + "LIMIT 1",
            {"locale": locale_id, "code": code},
        ).fetchone()
        return None if row is None else _subregion(row)


def _region(row: tuple[Any, ...]) -> RegionView:
    return RegionView(RegionRecord(*row[:4]), row[4])


def _subregion(row: tuple[Any, ...]) -> SubregionView:
    return SubregionView(SubregionRecord(*row[:5]), row[5])
