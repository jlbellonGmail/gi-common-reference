"""Digest de contenido del snapshot de Currency: mismas reglas que el de Locale (D7 de 001, RF-41).

`currencies` no importa `locales`, `regions` ni `countries` (RNF-6, D21 del plan): esta es una
copia de la canonicalización de `locale-snapshot.v1`. Una prueba de contrato comprueba que
reproduce los vectores publicados en `contracts/locale-snapshot.v1.vectors.json`, así PREP usa
una sola implementación.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

DIGEST_PREFIX = "sha256:"
CONTENT_DIGEST_FIELD = "content_digest"


class CanonicalizationError(ValueError):
    """El documento no tiene representación canónica (números no enteros, tipos no JSON...)."""


def canonical_json(value: Any) -> bytes:
    """JSON canónico en UTF-8: claves por punto de código, sin espacios, solo enteros."""
    return _canonical(value).encode("utf-8")


def content_digest(document: Mapping[str, Any]) -> str:
    """Digest del documento sin su `content_digest` de nivel superior (no autorreferente)."""
    body = {key: value for key, value in document.items() if key != CONTENT_DIGEST_FIELD}
    return DIGEST_PREFIX + hashlib.sha256(canonical_json(body)).hexdigest()


def content_digest_matches(document: Mapping[str, Any]) -> bool:
    declared = document.get(CONTENT_DIGEST_FIELD)
    try:
        return isinstance(declared, str) and declared == content_digest(document)
    except CanonicalizationError:
        return False


def _canonical(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise CanonicalizationError(f"clave que no es string: {key!r}")
        items = (f"{_string(key)}:{_canonical(value[key])}" for key in sorted(value))
        return "{" + ",".join(items) + "}"
    raise CanonicalizationError(f"valor no admitido en el JSON canónico: {type(value).__name__}")


def _string(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise CanonicalizationError("string con sustitutos Unicode sin par") from error
    return json.dumps(value, ensure_ascii=False)
