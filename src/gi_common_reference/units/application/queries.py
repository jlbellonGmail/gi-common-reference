"""Consultas de solo lectura del catálogo Units (RF-20, RF-32 a RF-37).

Cada consulta usa una única sesión: la `snapshot_version` informada y los datos salen del mismo
estado del catálogo, aunque se incorpore un snapshot en paralelo. Un parámetro inválido es un error
de validación (`INVALID`), distinto de «no encontrado» (RF-37); una falla técnica no se captura
aquí: sube como `ReaderUnavailable`. Los errores llevan códigos estables y legibles por máquina,
sin traducir (D15 del plan). Los nombres salen solo del locale pedido, sin fallback (RF-20).
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from gi_common_reference.units.domain.ports import (
    QuantityKindView,
    UnitsReader,
    UnitsSession,
    UnitView,
)

UUID_TEXT = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class LookupStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    INVALID = "invalid"


@dataclass(frozen=True)
class Lookup[T]:
    status: LookupStatus
    snapshot_version: int | None
    item: T | None = None
    error: str = ""  # código de error estable para el contrato (p. ej. `unit_not_found`)
    detail: str = ""


@dataclass(frozen=True)
class Listing[T]:
    status: LookupStatus
    snapshot_version: int | None
    items: tuple[T, ...] = ()
    error: str = ""
    detail: str = ""


@dataclass(frozen=True)
class _Invalid:
    error: str
    detail: str


def _locale(session: UnitsSession, locale_id: str | None) -> str | None | _Invalid:
    """RF-20: `None` sin locale; el `locale_id` normalizado; o el motivo del 422."""
    if locale_id is None:
        return None
    if not UUID_TEXT.fullmatch(locale_id):
        return _Invalid("invalid_locale_id", "locale_id debe ser un UUID")
    key = locale_id.lower()
    if not session.locale_exists(key):
        return _Invalid("unknown_locale", "el locale_id no existe en el catálogo de Locale")
    return key


def _key(locale: str | None | _Invalid) -> str | None:
    return locale if isinstance(locale, str) else None


def get_catalog_version(reader: UnitsReader) -> int | None:
    """RF-36: la versión aplicada del catálogo Units (`None` con catálogo vacío)."""
    with reader.session() as session:
        return session.snapshot_version()


def list_quantity_kinds(
    reader: UnitsReader,
    include_inactive: bool = False,
    code: str | None = None,
    locale_id: str | None = None,
) -> Listing[QuantityKindView]:
    """RF-32: por defecto solo las `active`, por código; `code` filtra por igualdad exacta."""
    with reader.session() as session:
        version = session.snapshot_version()
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Listing(LookupStatus.INVALID, version, (), locale.error, locale.detail)
        items = session.quantity_kinds(include_inactive, code, _key(locale))
    return Listing(LookupStatus.FOUND, version, tuple(items))


def get_quantity_kind(
    reader: UnitsReader, quantity_kind_id: str, locale_id: str | None = None
) -> Lookup[QuantityKindView]:
    """RF-33: `active` o `inactive`; un id mal formado es error de validación."""
    with reader.session() as session:
        version = session.snapshot_version()
        if not UUID_TEXT.fullmatch(quantity_kind_id):
            return Lookup(
                LookupStatus.INVALID,
                version,
                None,
                "invalid_quantity_kind_id",
                "quantity_kind_id debe ser un UUID",
            )
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Lookup(LookupStatus.INVALID, version, None, locale.error, locale.detail)
        found = session.quantity_kind_by_id(quantity_kind_id.lower(), _key(locale))
    if found is None:
        return Lookup(
            LookupStatus.NOT_FOUND, version, None, "quantity_kind_not_found", "no encontrado"
        )
    return Lookup(LookupStatus.FOUND, version, found)


def list_units(
    reader: UnitsReader,
    quantity_kind_id: str | None = None,
    ucum_code: str | None = None,
    unece_code: str | None = None,
    include_inactive: bool = False,
    locale_id: str | None = None,
) -> Listing[UnitView]:
    """RF-34: por defecto solo las `active`, por (símbolo, `unit_id`).

    Con `quantity_kind_id`, solo las unidades con asociación `active` a esa magnitud (cualquiera
    si `include_inactive`); una magnitud inexistente es «no encontrado». Los códigos filtran por
    igualdad exacta (UCUM distingue mayúsculas).
    """
    with reader.session() as session:
        version = session.snapshot_version()
        kind: str | None = None
        if quantity_kind_id is not None:
            if not UUID_TEXT.fullmatch(quantity_kind_id):
                return Listing(
                    LookupStatus.INVALID,
                    version,
                    (),
                    "invalid_quantity_kind_id",
                    "quantity_kind_id debe ser un UUID",
                )
            kind = quantity_kind_id.lower()
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Listing(LookupStatus.INVALID, version, (), locale.error, locale.detail)
        if kind is not None and not session.quantity_kind_exists(kind):
            return Listing(
                LookupStatus.NOT_FOUND, version, (), "quantity_kind_not_found", "no encontrado"
            )
        items = session.units(kind, ucum_code, unece_code, include_inactive, _key(locale))
    return Listing(LookupStatus.FOUND, version, tuple(items))


def get_unit(reader: UnitsReader, unit_id: str, locale_id: str | None = None) -> Lookup[UnitView]:
    """RF-35: `active` o `inactive`, con sus asociaciones; un id mal formado es inválido."""
    with reader.session() as session:
        version = session.snapshot_version()
        if not UUID_TEXT.fullmatch(unit_id):
            return Lookup(
                LookupStatus.INVALID, version, None, "invalid_unit_id", "unit_id debe ser un UUID"
            )
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Lookup(LookupStatus.INVALID, version, None, locale.error, locale.detail)
        found = session.unit_by_id(unit_id.lower(), _key(locale))
    if found is None:
        return Lookup(LookupStatus.NOT_FOUND, version, None, "unit_not_found", "no encontrado")
    return Lookup(LookupStatus.FOUND, version, found)
