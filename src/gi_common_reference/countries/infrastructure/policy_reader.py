"""Carga el conjunto obligatorio de locales que viaja con el paquete (`required-locales.v1.json`).

Es la política versionada en el repositorio (RF-35, D10). Un archivo ausente o mal formado es un
error del entorno (`SchemaLoadError`), nunca un snapshot inválido.
"""

import json
import re
from importlib import resources
from typing import Any

from gi_common_reference.countries.domain.errors import SchemaLoadError
from gi_common_reference.countries.domain.policy import RequiredLocale, RequiredLocales

POLICY_PACKAGE = "gi_common_reference.countries.infrastructure"
POLICY_RESOURCE = "required-locales.v1.json"
UUID_FORMAT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def load_required_locales() -> RequiredLocales:
    try:
        text = resources.files(POLICY_PACKAGE).joinpath(POLICY_RESOURCE).read_text("utf-8")
        document = json.loads(text)
    except (OSError, ValueError, ModuleNotFoundError) as error:
        raise SchemaLoadError(
            f"no se pudo cargar la política {POLICY_RESOURCE} del paquete: {type(error).__name__}"
        ) from error
    return parse_required_locales(document)


def parse_required_locales(document: Any) -> RequiredLocales:
    """Valida la forma de la política: versión positiva y una lista no vacía de locales únicos."""
    if not isinstance(document, dict):
        raise SchemaLoadError(f"la política {POLICY_RESOURCE} no es un objeto JSON")
    version, items = document.get("policy_version"), document.get("locales")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise SchemaLoadError(f"la política {POLICY_RESOURCE} no tiene una policy_version válida")
    if not isinstance(items, list) or not items:
        raise SchemaLoadError(f"la política {POLICY_RESOURCE} no lista ningún locale")
    locales: list[RequiredLocale] = []
    for item in items:
        locale_id = item.get("locale_id") if isinstance(item, dict) else None
        code = item.get("code") if isinstance(item, dict) else None
        if not isinstance(locale_id, str) or not UUID_FORMAT.fullmatch(locale_id):
            raise SchemaLoadError(f"la política {POLICY_RESOURCE} tiene un locale_id inválido")
        if not isinstance(code, str) or not code:
            raise SchemaLoadError(f"la política {POLICY_RESOURCE} tiene un locale sin código")
        locales.append(RequiredLocale(locale_id, code))
    if len({item.locale_id for item in locales}) != len(locales):
        raise SchemaLoadError(f"la política {POLICY_RESOURCE} repite un locale_id")
    return RequiredLocales(version, tuple(locales))
