"""Consultas de solo lectura del catálogo de locales (RF-7–RF-13).

Cada consulta usa una única sesión: la `snapshot_version` informada y los datos salen del mismo
estado del catálogo, aunque se incorpore un snapshot en paralelo.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from gi_common_reference.locales.domain.codes import lookup_key
from gi_common_reference.locales.domain.model import LocaleRecord
from gi_common_reference.locales.domain.ports import LocaleReader

UUID_TEXT = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
STATUSES = ("active", "inactive")


class LookupStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    INVALID = "invalid"


@dataclass(frozen=True)
class LocaleLookup:
    status: LookupStatus
    snapshot_version: int | None
    locale: LocaleRecord | None = None
    detail: str = ""


@dataclass(frozen=True)
class LocaleListing:
    status: LookupStatus
    snapshot_version: int | None
    locales: tuple[LocaleRecord, ...] = ()
    detail: str = ""


def get_locale_by_id(reader: LocaleReader, locale_id: str) -> LocaleLookup:
    """RF-7. Un id mal formado no puede existir: es "no encontrado", nunca un error."""
    with reader.session() as session:
        version = session.snapshot_version()
        if not UUID_TEXT.fullmatch(locale_id):
            return LocaleLookup(LookupStatus.NOT_FOUND, version, detail="locale_id no encontrado")
        locale = session.by_id(locale_id.lower())
    if locale is None:
        return LocaleLookup(LookupStatus.NOT_FOUND, version, detail="locale_id no encontrado")
    return LocaleLookup(LookupStatus.FOUND, version, locale)


def get_locale_by_code(reader: LocaleReader, raw_code: str) -> LocaleLookup:
    """RF-8, RF-9, RF-10: el código publicado, o el de su *Preferred-Value* si no se publicó."""
    with reader.session() as session:
        version = session.snapshot_version()
        key = lookup_key(raw_code)
        if key is None:
            detail = "el código debe ser un subtag de idioma de 2 o 3 letras ASCII, sin '-' ni '_'"
            return LocaleLookup(LookupStatus.INVALID, version, detail=detail)
        locale = session.by_code(key)
        if locale is None:
            preferred = session.alias(key)
            locale = session.by_code(preferred) if preferred else None
    if locale is None:
        return LocaleLookup(LookupStatus.NOT_FOUND, version, detail="código no encontrado")
    return LocaleLookup(LookupStatus.FOUND, version, locale)


def list_locales(reader: LocaleReader, status: str | None) -> LocaleListing:
    """RF-11: todos los locales publicados por `code`, o solo los de un `status`."""
    with reader.session() as session:
        version = session.snapshot_version()
        if status is not None and status not in STATUSES:
            detail = f"status debe ser uno de: {', '.join(STATUSES)}"
            return LocaleListing(LookupStatus.INVALID, version, detail=detail)
        locales = tuple(session.all_locales(status))
    return LocaleListing(LookupStatus.FOUND, version, locales)
