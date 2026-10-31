"""Consultas de solo lectura del catálogo Countries (RF-8–RF-16, RF-38, RF-50).

Cada consulta usa una única sesión: la `snapshot_version` informada y los datos salen del mismo
estado del catálogo, aunque se incorpore un snapshot en paralelo. Un parámetro inválido es un error
de validación (`INVALID`), distinto de "no encontrado" (RF-11, RF-12). Los errores llevan códigos
estables y legibles por máquina, sin traducir (RNF-9, D-19).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from gi_common_reference.countries.application.flags import FlagReadError, read_verified_flag
from gi_common_reference.countries.domain.codes import is_valid_code
from gi_common_reference.countries.domain.model import STATUSES, CodeKind
from gi_common_reference.countries.domain.ports import (
    CountryReader,
    CountrySession,
    CountryView,
    FlagStore,
)

UUID_TEXT = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
ALPHA_QUERY: dict[CodeKind, re.Pattern[str]] = {
    "alpha2": re.compile(r"[A-Za-z]{2}"),
    "alpha3": re.compile(r"[A-Za-z]{3}"),
    "numeric_code": re.compile(r"[0-9]{3}"),
}
STATUS_FILTERS = (*STATUSES, "all")


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


def _locale(session: CountrySession, locale_id: str | None) -> str | None | _Invalid:
    """RF-38: `None` sin locale; el `locale_id` normalizado; o el motivo del 422."""
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


def get_country_by_id(
    reader: CountryReader, country_id: str, locale_id: str | None = None
) -> Lookup[CountryView]:
    """RF-8, RF-14. Un id mal formado no puede existir: es "no encontrado", nunca un error."""
    with reader.session() as session:
        version = session.snapshot_version()
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Lookup(LookupStatus.INVALID, version, None, locale.error, locale.detail)
        found = (
            session.country_by_id(country_id.lower(), locale)
            if UUID_TEXT.fullmatch(country_id)
            else None
        )
    if found is None:
        return Lookup(LookupStatus.NOT_FOUND, version, None, "country_not_found", "no encontrado")
    return Lookup(LookupStatus.FOUND, version, found)


def get_country_by_code(
    reader: CountryReader, kind: CodeKind, code: str, locale_id: str | None = None
) -> Lookup[CountryView]:
    """RF-9–RF-12: `alpha2`/`alpha3` sin distinguir mayúsculas; el numérico, el texto exacto.

    Compara contra el código vigente; un código mal formado es 422, no 404.
    """
    with reader.session() as session:
        version = session.snapshot_version()
        if ALPHA_QUERY[kind].fullmatch(code) is None:
            detail = {
                "alpha2": "el código debe tener 2 letras A-Z (p. ej. AR)",
                "alpha3": "el código debe tener 3 letras A-Z (p. ej. ARG)",
                "numeric_code": "el código debe tener 3 dígitos (p. ej. 032)",
            }[kind]
            return Lookup(LookupStatus.INVALID, version, None, "invalid_code", detail)
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Lookup(LookupStatus.INVALID, version, None, locale.error, locale.detail)
        normalized = code if kind == "numeric_code" else code.upper()
        found = (
            session.country_by_code(kind, normalized, locale)
            if is_valid_code(kind, normalized)
            else None
        )
    if found is None:
        return Lookup(LookupStatus.NOT_FOUND, version, None, "country_not_found", "no encontrado")
    return Lookup(LookupStatus.FOUND, version, found)


def list_countries(
    reader: CountryReader,
    status: str | None = None,
    region_id: str | None = None,
    subregion_id: str | None = None,
    locale_id: str | None = None,
) -> Listing[CountryView]:
    """RF-13: por defecto solo los `active`; `status=all` incluye los `inactive`."""
    chosen = "active" if status is None else status
    with reader.session() as session:
        version = session.snapshot_version()
        problem: _Invalid | None = None
        if chosen not in STATUS_FILTERS:
            problem = _Invalid(
                "invalid_status", f"status debe ser uno de: {', '.join(STATUS_FILTERS)}"
            )
        elif region_id is not None and not UUID_TEXT.fullmatch(region_id):
            problem = _Invalid("invalid_region_id", "region_id debe ser un UUID")
        elif subregion_id is not None and not UUID_TEXT.fullmatch(subregion_id):
            problem = _Invalid("invalid_subregion_id", "subregion_id debe ser un UUID")
        locale = _locale(session, locale_id) if problem is None else None
        problem = problem or (locale if isinstance(locale, _Invalid) else None)
        if problem is not None:
            return Listing(LookupStatus.INVALID, version, (), problem.error, problem.detail)
        items: Sequence[CountryView] = session.countries(
            None if chosen == "all" else chosen,
            None if region_id is None else region_id.lower(),
            None if subregion_id is None else subregion_id.lower(),
            _key(locale),
        )
    return Listing(LookupStatus.FOUND, version, tuple(items))


class FlagStatus(StrEnum):
    FOUND = "found"
    COUNTRY_NOT_FOUND = "country_not_found"
    NOT_DECLARED = "flag_not_declared"  # excepción declarada: el país no tiene bandera
    INTEGRITY = "flag_integrity_error"  # el archivo falta o no coincide con la suma registrada


@dataclass(frozen=True)
class FlagLookup:
    status: FlagStatus
    snapshot_version: int | None
    content: bytes | None = None
    sha256: str | None = None


def get_flag(reader: CountryReader, store: FlagStore, country_id: str) -> FlagLookup:
    """RF-50: el SVG verificado contra la suma registrada, o el motivo por el que no hay."""
    with reader.session() as session:
        version = session.snapshot_version()
        if not UUID_TEXT.fullmatch(country_id):
            return FlagLookup(FlagStatus.COUNTRY_NOT_FOUND, version)
        key = country_id.lower()
        if session.country_by_id(key, None) is None:
            return FlagLookup(FlagStatus.COUNTRY_NOT_FOUND, version)
        flag = session.flag(key)
    if flag is None or flag.asset_path is None or flag.sha256 is None:
        return FlagLookup(FlagStatus.NOT_DECLARED, version)
    try:
        content = read_verified_flag(store, flag.asset_path, flag.sha256)
    except FlagReadError:
        return FlagLookup(FlagStatus.INTEGRITY, version)
    return FlagLookup(FlagStatus.FOUND, version, content, flag.sha256)
