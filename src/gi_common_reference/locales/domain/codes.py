"""Reglas de código de Locale v1: solo el subtag `language` (spec 001, "Reglas de publicación")."""

import re
from enum import StrEnum

from gi_common_reference.locales.domain.iana import IanaRegistry

WELL_FORMED = re.compile(r"[A-Za-z]{2,3}")
PUBLISHABLE_FORMAT = re.compile(r"[a-z]{2,3}")


class CodeViolation(StrEnum):
    FORMAT = "format"  # reglas 2 y 6
    NOT_REGISTERED = "not_registered"  # regla 3
    NOT_PREFERRED = "not_preferred"  # regla 4
    SCOPE_SPECIAL = "scope_special"  # regla 5
    PRIVATE_USE = "private_use"  # regla 5


def lookup_key(raw: str) -> str | None:
    """Clave de consulta pública (RF-8, RF-9).

    Un subtag de idioma bien formado son 2 o 3 letras ASCII, sin `-`, `_` ni espacios; no se recorta
    nada. Devuelve el código en minúsculas, o `None` si no está bien formado.
    """
    return raw.lower() if WELL_FORMED.fullmatch(raw) else None


def is_lowercase(code: str) -> bool:
    """RF-28: los códigos de un snapshot llegan en minúsculas; el sistema no los normaliza.

    Solo evalúa las mayúsculas: el formato lo valida `publication_violations`.
    """
    return code == code.lower()


def publication_violations(code: str, registry: IanaRegistry) -> list[CodeViolation]:
    """Reglas de publicación de un locale nuevo contra el artefacto IANA del snapshot (RF-4)."""
    if not PUBLISHABLE_FORMAT.fullmatch(code):
        return [CodeViolation.FORMAT]
    if registry.is_private_use(code):
        return [CodeViolation.PRIVATE_USE]
    entry = registry.language(code)
    if entry is None:
        return [CodeViolation.NOT_REGISTERED]
    if entry.scope == "special":
        return [CodeViolation.SCOPE_SPECIAL]
    if entry.preferred_value:
        return [CodeViolation.NOT_PREFERRED]
    return []
