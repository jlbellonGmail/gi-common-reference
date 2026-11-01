"""Lector de snapshots: lee un archivo local y valida su estructura contra el JSON Schema (RF-31).

No accede a la red (RNF-2). Los digests y las reglas del catálogo las evalúa el dominio.

El schema viaja dentro del paquete (`locale-snapshot.v1.schema.json`, junto a este módulo) y se
carga con `importlib.resources`, de modo que la CLI no depende del checkout. La copia publicada para
PREP es `contracts/locale-snapshot.v1.schema.json`; una prueba verifica que ambas sean equivalentes.
"""

import json
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from gi_common_reference.locales.domain.errors import SchemaLoadError
from gi_common_reference.locales.domain.ports import SnapshotFormatError

__all__ = [
    "SCHEMA_PACKAGE",
    "SCHEMA_RESOURCE",
    "SchemaLoadError",
    "SnapshotFormatError",
    "load_snapshot_schema",
    "read_snapshot_document",
]

SCHEMA_PACKAGE = "gi_common_reference.locales.infrastructure"
SCHEMA_RESOURCE = "locale-snapshot.v1.schema.json"


def load_snapshot_schema() -> dict[str, Any]:
    """Schema empaquetado. Si no se puede cargar es `SchemaLoadError`, no culpa del snapshot."""
    try:
        text = resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_RESOURCE).read_text("utf-8")
        schema = json.loads(text)
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, ModuleNotFoundError, SchemaError) as error:
        raise SchemaLoadError(
            f"no se pudo cargar el schema {SCHEMA_RESOURCE} del paquete: {type(error).__name__}"
        ) from error
    if not isinstance(schema, dict):
        raise SchemaLoadError(f"el schema {SCHEMA_RESOURCE} del paquete no es un objeto JSON")
    return schema


def read_snapshot_document(path: Path) -> dict[str, Any]:
    """Devuelve el documento JSON del snapshot, ya validado contra el schema.

    Errores distintos: `SchemaLoadError` (entorno), `OSError` (el archivo no se puede leer) y
    `SnapshotFormatError` (el contenido no es un snapshot válido).
    """
    schema = load_snapshot_schema()
    raw = path.read_bytes()
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise SnapshotFormatError([f"JSON inválido: {error}"]) from error
    if not isinstance(document, dict):
        raise SnapshotFormatError(["el snapshot debe ser un objeto JSON"])
    _validate(document, schema)
    return document


def _validate(document: dict[str, Any], schema: dict[str, Any]) -> None:
    problems = sorted(
        f"/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in Draft202012Validator(schema).iter_errors(document)
    )
    if problems:
        raise SnapshotFormatError(problems)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"clave duplicada: {key!r}")
        result[key] = value
    return result


def _reject_number(literal: str) -> Any:
    raise ValueError(f"número no entero no admitido: {literal}")
