"""Adaptador de lectura de Units sobre Postgres: la API se conecta con `reference_reader`.

El nombre y el plural salen de `quantity_kind_locale` / `unit_locale` para el `locale_id` pedido,
sin fallback a otro locale (RF-20). La existencia del `locale_id` se consulta en `reference.locale`.
La conversión lee el artefacto íntegro de `unit_snapshot` (D6). Solo se lee el catálogo persistido:
nunca una fuente externa.
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg

from gi_common_reference.units.domain.errors import describe_error
from gi_common_reference.units.domain.model import QuantityKindRecord, UnitRecord
from gi_common_reference.units.domain.ports import (
    QuantityKindView,
    ReaderUnavailable,
    UnitAssociationView,
    UnitView,
)
from gi_common_reference.units.infrastructure.conninfo import validate_conninfo

KINDS = (
    "SELECT k.quantity_kind_id::text, k.code, k.conversion_type, k.reference_unit_id::text, "
    "k.status, n.name FROM reference.quantity_kind k "
    "LEFT JOIN reference.quantity_kind_locale n "
    "ON n.quantity_kind_id = k.quantity_kind_id AND n.locale_id = %(locale)s::uuid "
)
UNITS = (
    "SELECT u.unit_id::text, u.ucum_code, u.unece_code, u.symbol, u.status, n.name, n.plural "
    "FROM reference.unit u LEFT JOIN reference.unit_locale n "
    "ON n.unit_id = u.unit_id AND n.locale_id = %(locale)s::uuid "
)
ASSOCIATIONS = (
    "SELECT a.unit_id::text, a.quantity_kind_id::text, a.status, "
    "k.reference_unit_id = a.unit_id FROM reference.quantity_kind_unit a "
    "JOIN reference.quantity_kind k ON k.quantity_kind_id = a.quantity_kind_id "
    "WHERE a.unit_id = ANY(%(ids)s::uuid[]) ORDER BY a.unit_id, a.quantity_kind_id"
)


class PostgresUnitsReader:
    """Una conexión por sesión, de solo lectura y con una instantánea consistente."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = validate_conninfo(conninfo)

    @contextmanager
    def session(self) -> Iterator["PostgresUnitsSession"]:
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
                yield PostgresUnitsSession(connection)
        except psycopg.OperationalError as error:
            raise ReaderUnavailable(describe_error(error)) from None


class PostgresUnitsSession:
    def __init__(self, connection: "psycopg.Connection[Any]") -> None:
        self._connection = connection

    def snapshot_version(self) -> int | None:
        row = self._connection.execute(
            "SELECT max(snapshot_version) FROM reference.unit_snapshot"
        ).fetchone()
        return None if row is None else row[0]

    def locale_exists(self, locale_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM reference.locale WHERE locale_id = %s::uuid", [locale_id]
        ).fetchone()
        return row is not None

    def quantity_kind_exists(self, quantity_kind_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM reference.quantity_kind WHERE quantity_kind_id = %s::uuid",
            [quantity_kind_id],
        ).fetchone()
        return row is not None

    def quantity_kinds(
        self, include_inactive: bool, code: str | None, locale_id: str | None
    ) -> Sequence[QuantityKindView]:
        rows = self._connection.execute(
            KINDS + "WHERE (%(inactive)s OR k.status = 'active') "
            "AND (%(code)s::text IS NULL OR k.code = %(code)s::text) "
            'ORDER BY k.code COLLATE "C", k.quantity_kind_id',
            {"locale": locale_id, "inactive": include_inactive, "code": code},
        ).fetchall()
        return [_kind(row) for row in rows]

    def quantity_kind_by_id(
        self, quantity_kind_id: str, locale_id: str | None
    ) -> QuantityKindView | None:
        row = self._connection.execute(
            KINDS + "WHERE k.quantity_kind_id = %(id)s::uuid",
            {"locale": locale_id, "id": quantity_kind_id},
        ).fetchone()
        return None if row is None else _kind(row)

    def units(
        self,
        quantity_kind_id: str | None,
        ucum_code: str | None,
        unece_code: str | None,
        include_inactive: bool,
        locale_id: str | None,
    ) -> Sequence[UnitView]:
        rows = self._connection.execute(
            UNITS + "WHERE (%(inactive)s OR u.status = 'active') "
            "AND (%(ucum)s::text IS NULL OR u.ucum_code = %(ucum)s::text) "
            "AND (%(unece)s::text IS NULL OR u.unece_code = %(unece)s::text) "
            "AND (%(kind)s::uuid IS NULL OR EXISTS ("
            "SELECT 1 FROM reference.quantity_kind_unit a WHERE a.unit_id = u.unit_id "
            "AND a.quantity_kind_id = %(kind)s::uuid AND (%(inactive)s OR a.status = 'active'))) "
            'ORDER BY u.symbol COLLATE "C", u.unit_id',
            {
                "locale": locale_id,
                "inactive": include_inactive,
                "ucum": ucum_code,
                "unece": unece_code,
                "kind": quantity_kind_id,
            },
        ).fetchall()
        return self._with_associations(rows)

    def unit_by_id(self, unit_id: str, locale_id: str | None) -> UnitView | None:
        rows = self._connection.execute(
            UNITS + "WHERE u.unit_id = %(id)s::uuid", {"locale": locale_id, "id": unit_id}
        ).fetchall()
        views = self._with_associations(rows)
        return views[0] if views else None

    def artifact(self, snapshot_version: int) -> Mapping[str, Any] | None:
        row = self._connection.execute(
            "SELECT artifact FROM reference.unit_snapshot WHERE snapshot_version = %s",
            [snapshot_version],
        ).fetchone()
        return None if row is None else row[0]

    def _with_associations(self, rows: Sequence[tuple[Any, ...]]) -> list[UnitView]:
        if not rows:
            return []
        found = self._connection.execute(ASSOCIATIONS, {"ids": [row[0] for row in rows]}).fetchall()
        by_unit: dict[str, list[UnitAssociationView]] = {}
        for unit_id, kind_id, status, reference in found:
            by_unit.setdefault(unit_id, []).append(UnitAssociationView(kind_id, status, reference))
        return [
            UnitView(
                UnitRecord(row[0], row[1], row[2], row[3], row[4]),
                row[5],
                row[6],
                tuple(by_unit.get(row[0], ())),
            )
            for row in rows
        ]


def _kind(row: tuple[Any, ...]) -> QuantityKindView:
    return QuantityKindView(QuantityKindRecord(row[0], row[1], row[2], row[3], row[4]), row[5])
