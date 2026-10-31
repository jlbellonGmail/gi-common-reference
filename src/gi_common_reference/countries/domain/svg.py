"""Assets SVG de bandera: ruta segura y contenido sin partes activas (RF-49, D12 del plan).

La ruta es relativa al directorio de assets del paquete y se compone de segmentos simples: sin `..`,
sin rutas absolutas, sin separadores de Windows y con extensión `.svg` (la misma regla que la
constraint `country_flag_asset_path_format`). El contenido es una función pura: un SVG de bandera es
datos, nunca ejecuta nada ni carga recursos externos. Las rutas, la existencia y la suma de
verificación las comprueba la aplicación a través del puerto `FlagStore`.
"""

import hashlib
import re
import xml.etree.ElementTree as ET

SVG_MEDIA_TYPE = "image/svg+xml"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
MAX_SVG_BYTES = 512 * 1024
ASSET_PATH = re.compile(r"([A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.svg")
# Una bandera es arte estático: tampoco se admite animación SMIL, que puede escribir un `href`
# peligroso por `to`, `from`, `by` o `values` sin que el atributo `href` figure en el documento.
FORBIDDEN_ELEMENTS = frozenset(
    {
        "script",
        "foreignobject",
        "iframe",
        "object",
        "embed",
        "set",
        "animate",
        "animatetransform",
        "animatemotion",
        "discard",
    }
)
URL_REFERENCE = re.compile(r"url\(\s*(?P<quote>['\"]?)(?P<target>[^)]*?)(?P=quote)\s*\)", re.I)


def is_safe_asset_path(path: str) -> bool:
    """`ar.svg` y `4x3/ar.svg` sí; `../ar.svg`, `/ar.svg`, `a//b.svg`, `ar.png` y `a\\b.svg` no."""
    return ASSET_PATH.fullmatch(path) is not None


def sha256_of(data: bytes) -> str:
    """Suma de verificación de los bytes exactos del archivo, con el prefijo del contrato."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def svg_content_problems(data: bytes) -> list[str]:
    """Motivos por los que el contenido no es un SVG de bandera aceptable; vacío si lo es."""
    if len(data) > MAX_SVG_BYTES:
        return [f"supera el tamaño máximo de {MAX_SVG_BYTES} bytes"]
    if not data:
        return ["está vacío"]
    if b"\x00" in data:
        return ["contiene bytes nulos (no es XML en UTF-8)"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ["no está codificado en UTF-8"]
    lowered = text.lower()
    # Se rechazan DTD y entidades antes de parsear: nunca llegan a expandirse.
    if "<!doctype" in lowered or "<!entity" in lowered:
        return ["contiene DTD o entidades"]
    if "<?xml-stylesheet" in lowered:
        return ["referencia una hoja de estilos externa"]
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return ["no es un XML bien formado"]
    if root.tag != f"{{{SVG_NAMESPACE}}}svg":
        return ["su raíz no es un elemento svg del espacio de nombres SVG"]

    problems: list[str] = []
    for element in root.iter():
        local = element.tag.rsplit("}", 1)[-1].lower()
        if local in FORBIDDEN_ELEMENTS:
            problems.append(f"elemento <{local}> no permitido")
        if local == "style":
            problems += _css_problems(element.text or "", "elemento <style>")
        for attribute, value in element.attrib.items():
            name = attribute.rsplit("}", 1)[-1].lower()
            if name.startswith("on"):
                problems.append(f"manejador de eventos {name!r} no permitido")
            if name in ("href", "src") and not _is_local_fragment(value):
                problems.append(f"referencia {name}={value!r} que no es un fragmento local #id")
            problems += _css_problems(value, f"atributo {name!r}")
    return list(dict.fromkeys(problems))


def _is_local_fragment(value: str) -> bool:
    return value.startswith("#") and len(value) > 1


def _css_problems(text: str, where: str) -> list[str]:
    """`url(...)` solo hacia fragmentos locales; sin `@import` ni escapes que oculten `url(`."""
    problems: list[str] = []
    if "\\" in text:
        problems.append(f"{where} usa escapes CSS")
    if "@import" in text.lower():
        problems.append(f"{where} importa una hoja de estilos")
    for match in URL_REFERENCE.finditer(text):
        target = match.group("target").strip()
        if not _is_local_fragment(target):
            problems.append(f"{where} referencia {target!r}, que no es un fragmento local #id")
    return problems
