"""Lector de la tabla UCUM empaquetada (`ucum/ucum-essence.xml`, D8, RNF-7).

El archivo oficial se redistribuye sin modificar (UCUM License v1.1, ver `ucum/NOTICE.md`). Antes de
interpretarlo se verifica su sha256 contra el valor fijado aquí: un archivo adulterado, truncado o
con otros fines de línea es un error del entorno (`SchemaLoadError`), nunca un snapshot inválido.
El XML solo se parsea con la biblioteca estándar y sin entidades externas.
"""

import hashlib
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from importlib import resources
from types import MappingProxyType

from gi_common_reference.units.domain.errors import SchemaLoadError
from gi_common_reference.units.domain.model import (
    UcumAtom,
    UcumFunction,
    UcumPrefix,
    UcumTable,
)

__all__ = [
    "UCUM_PACKAGE",
    "UCUM_RESOURCE",
    "UCUM_SHA256",
    "load_ucum_table",
    "parse_ucum_table",
    "read_ucum_bytes",
]

UCUM_PACKAGE = "gi_common_reference.units.infrastructure"
UCUM_DIRECTORY = "ucum"
UCUM_RESOURCE = "ucum-essence.xml"
# ucum-essence.xml v2.2, revisión 2024-06-17 (github.com/ucum-org/ucum), sin modificar.
UCUM_SHA256 = "dfccea1b5dc284245ebae97edd1dc03c45864da4e87df55bc9851797b4fd0b61"
NAMESPACE = "{http://unitsofmeasure.org/ucum-essence}"


def read_ucum_bytes() -> bytes:
    """Bytes exactos del archivo empaquetado, sin verificar."""
    try:
        resource = resources.files(UCUM_PACKAGE).joinpath(UCUM_DIRECTORY).joinpath(UCUM_RESOURCE)
        return resource.read_bytes()
    except (OSError, ModuleNotFoundError) as error:
        raise SchemaLoadError(
            f"no se pudo cargar la tabla UCUM {UCUM_RESOURCE} del paquete: {type(error).__name__}"
        ) from error


def load_ucum_table() -> UcumTable:
    """Tabla UCUM empaquetada, verificada contra el sha256 fijado."""
    return parse_ucum_table(read_ucum_bytes())


def parse_ucum_table(data: bytes, expected_sha256: str = UCUM_SHA256) -> UcumTable:
    """Verifica el sha256 de `data` y lo interpreta; si no coincide, `SchemaLoadError`."""
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise SchemaLoadError(
            f"la tabla UCUM {UCUM_RESOURCE} no coincide con el sha256 fijado "
            f"(esperado {expected_sha256}, calculado {actual})"
        )
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise SchemaLoadError(f"la tabla UCUM {UCUM_RESOURCE} no es XML válido") from error
    if root.tag != f"{NAMESPACE}root":
        raise SchemaLoadError(f"la tabla UCUM {UCUM_RESOURCE} no es un ucum-essence")
    version, revision_date = root.get("version"), root.get("revision-date")
    if not version or not revision_date:
        raise SchemaLoadError(f"la tabla UCUM {UCUM_RESOURCE} no declara versión y revisión")
    prefixes: dict[str, UcumPrefix] = {}
    atoms: dict[str, UcumAtom] = {}
    for element in root:
        tag = element.tag.removeprefix(NAMESPACE)
        if tag == "prefix":
            prefix = _prefix(element)
            prefixes[prefix.code] = prefix
        elif tag in ("base-unit", "unit"):
            atom = _atom(element, base=tag == "base-unit")
            atoms[atom.code] = atom
    if not prefixes or not atoms:
        raise SchemaLoadError(f"la tabla UCUM {UCUM_RESOURCE} no tiene prefijos o unidades")
    return UcumTable(
        version,
        revision_date,
        actual,
        _frozen(prefixes),
        _frozen(atoms),
    )


def _frozen[T](items: dict[str, T]) -> Mapping[str, T]:
    return MappingProxyType(items)


def _prefix(element: ET.Element) -> UcumPrefix:
    code = element.get("Code")
    value = element.find(f"{NAMESPACE}value")
    if not code or value is None or not value.get("value"):
        raise SchemaLoadError(f"la tabla UCUM {UCUM_RESOURCE} tiene un prefijo incompleto")
    return UcumPrefix(code, value.get("value") or "")


def _atom(element: ET.Element, *, base: bool) -> UcumAtom:
    code = element.get("Code")
    if not code:
        raise SchemaLoadError(f"la tabla UCUM {UCUM_RESOURCE} tiene una unidad sin código")
    special = element.get("isSpecial") == "yes"
    arbitrary = element.get("isArbitrary") == "yes"
    if base:
        # El archivo no marca `isMetric` en las unidades base; en UCUM todas admiten prefijos.
        return UcumAtom(code, True, special, arbitrary, dimension=element.get("dim"))
    definition = element.find(f"{NAMESPACE}value")
    if definition is None:
        raise SchemaLoadError(f"la unidad UCUM {code} no tiene definición")
    function_element = definition.find(f"{NAMESPACE}function")
    function = (
        UcumFunction(
            function_element.get("name") or "",
            function_element.get("value") or "",
            function_element.get("Unit") or "",
        )
        if function_element is not None
        else None
    )
    return UcumAtom(
        code,
        element.get("isMetric") == "yes",
        special,
        arbitrary,
        value=definition.get("value"),
        unit=definition.get("Unit"),
        function=function,
    )
