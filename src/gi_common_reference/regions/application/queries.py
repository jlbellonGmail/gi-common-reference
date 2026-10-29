"""Consultas de solo lectura del catálogo Region/Subregion (RF-14–RF-20).

Cada consulta usa una única sesión: la `snapshot_version` informada y los datos salen del mismo
estado del catálogo, aunque se incorpore un snapshot en paralelo. Un parámetro inválido es un error
de validación (`INVALID`), distinto de "no encontrado" (RF-17, RF-19).
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from gi_common_reference.regions.domain.codes import is_valid_code
from gi_common_reference.regions.domain.model import STATUSES
from gi_common_reference.regions.domain.ports import (
    RegionReader,
    RegionSession,
    RegionView,
    SubregionView,
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
    error: str = ""  # código de error estable para el contrato (p. ej. `unknown_locale`)
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


def _locale(session: RegionSession, locale_id: str | None) -> str | None | _Invalid:
    """RF-18, RF-19: `None` sin locale; el `locale_id` normalizado; o el motivo del 422."""
    if locale_id is None:
        return None
    if not UUID_TEXT.fullmatch(locale_id):
        return _Invalid("invalid_locale_id", "locale_id debe ser un UUID")
    key = locale_id.lower()
    if not session.locale_exists(key):
        return _Invalid("unknown_locale", "el locale_id no existe en el catálogo de Locale")
    return key


def _status(status: str | None) -> _Invalid | None:
    if status is not None and status not in STATUSES:
        return _Invalid("invalid_status", f"status debe ser uno de: {', '.join(STATUSES)}")
    return None


def _by_id[View: (RegionView, SubregionView)](
    reader: RegionReader,
    entity_id: str,
    locale_id: str | None,
    fetch: Callable[[RegionSession, str, str | None], View | None],
    label: str,
) -> Lookup[View]:
    """RF-16. Un id mal formado no puede existir: es "no encontrado", nunca un error."""
    with reader.session() as session:
        version = session.snapshot_version()
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Lookup(LookupStatus.INVALID, version, None, locale.error, locale.detail)
        found = (
            fetch(session, entity_id.lower(), locale) if UUID_TEXT.fullmatch(entity_id) else None
        )
    if found is None:
        return Lookup(LookupStatus.NOT_FOUND, version, None, "not_found", f"{label} no encontrado")
    return Lookup(LookupStatus.FOUND, version, found)


def _by_code[View: (RegionView, SubregionView)](
    reader: RegionReader,
    code: str,
    locale_id: str | None,
    fetch: Callable[[RegionSession, str, str | None], View | None],
) -> Lookup[View]:
    """RF-17: compara contra el código vigente; un código mal formado es 422, no 404."""
    with reader.session() as session:
        version = session.snapshot_version()
        if not is_valid_code(code):
            detail = "el código debe ser un código UN M49 de 3 dígitos (p. ej. 019)"
            return Lookup(LookupStatus.INVALID, version, None, "invalid_code", detail)
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Lookup(LookupStatus.INVALID, version, None, locale.error, locale.detail)
        found = fetch(session, code, locale)
    if found is None:
        return Lookup(LookupStatus.NOT_FOUND, version, None, "not_found", "código no encontrado")
    return Lookup(LookupStatus.FOUND, version, found)


def get_region_by_id(
    reader: RegionReader, region_id: str, locale_id: str | None = None
) -> Lookup[RegionView]:
    return _by_id(reader, region_id, locale_id, lambda s, i, lo: s.region_by_id(i, lo), "region_id")


def get_subregion_by_id(
    reader: RegionReader, subregion_id: str, locale_id: str | None = None
) -> Lookup[SubregionView]:
    return _by_id(
        reader, subregion_id, locale_id, lambda s, i, lo: s.subregion_by_id(i, lo), "subregion_id"
    )


def get_region_by_code(
    reader: RegionReader, code: str, locale_id: str | None = None
) -> Lookup[RegionView]:
    return _by_code(reader, code, locale_id, lambda s, c, lo: s.region_by_code(c, lo))


def get_subregion_by_code(
    reader: RegionReader, code: str, locale_id: str | None = None
) -> Lookup[SubregionView]:
    return _by_code(reader, code, locale_id, lambda s, c, lo: s.subregion_by_code(c, lo))


def list_regions(
    reader: RegionReader, status: str | None = None, locale_id: str | None = None
) -> Listing[RegionView]:
    """RF-14: todas las regiones publicadas, o solo las de un `status`, en orden determinístico."""
    with reader.session() as session:
        version = session.snapshot_version()
        problem = _status(status)
        locale = _locale(session, locale_id) if problem is None else None
        problem = problem or (locale if isinstance(locale, _Invalid) else None)
        if problem is not None:
            return Listing(LookupStatus.INVALID, version, (), problem.error, problem.detail)
        items: Sequence[RegionView] = session.regions(status, _key(locale))
    return Listing(LookupStatus.FOUND, version, tuple(items))


def list_subregions(
    reader: RegionReader,
    region_id: str | None = None,
    status: str | None = None,
    locale_id: str | None = None,
) -> Listing[SubregionView]:
    """RF-15: filtrables por `region_id` y `status`; un `region_id` inexistente da lista vacía."""
    with reader.session() as session:
        version = session.snapshot_version()
        problem = _status(status)
        if problem is None and region_id is not None and not UUID_TEXT.fullmatch(region_id):
            problem = _Invalid("invalid_region_id", "region_id debe ser un UUID")
        locale = _locale(session, locale_id) if problem is None else None
        problem = problem or (locale if isinstance(locale, _Invalid) else None)
        if problem is not None:
            return Listing(LookupStatus.INVALID, version, (), problem.error, problem.detail)
        region = None if region_id is None else region_id.lower()
        items: Sequence[SubregionView] = session.subregions(region, status, _key(locale))
    return Listing(LookupStatus.FOUND, version, tuple(items))


def _key(locale: str | None | _Invalid) -> str | None:
    return locale if isinstance(locale, str) else None
