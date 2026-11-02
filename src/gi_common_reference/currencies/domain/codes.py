"""Formatos de los códigos ISO 4217 e identidades (RF-4, RF-2).

Los códigos son siempre texto: el numérico conserva sus ceros (`032`) y nunca se normaliza ni se
coacciona (CL-3). `fullmatch` evita que un salto de línea final pase como válido.
"""

import re
from typing import Any

ALPHABETIC_CODE = re.compile(r"[A-Z]{3}")
NUMERIC_CODE = re.compile(r"[0-9]{3}")
UUID_FORMAT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def is_alphabetic_code(value: Any) -> bool:
    return isinstance(value, str) and ALPHABETIC_CODE.fullmatch(value) is not None


def is_numeric_code(value: Any) -> bool:
    return isinstance(value, str) and NUMERIC_CODE.fullmatch(value) is not None


def is_uuid(value: Any) -> bool:
    return isinstance(value, str) and UUID_FORMAT.fullmatch(value) is not None


def is_minor_units(value: Any) -> bool:
    """Entero no negativo o `None` («no aplicable»); un booleano no es un entero (RF-4, CL-1)."""
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


def is_trimmed(text: str) -> bool:
    """No vacío y sin espacios al inicio ni al final (RF-16)."""
    return bool(text) and text == text.strip()


def normalize_code_for_lookup(value: str) -> str | None:
    """Clave de resolución por código alfabético: mayúsculas; `None` si el formato no es válido.

    Se tolera `usd`; ` USD`, `US`, `US$` o vacío no son válidos (RF-23, RF-25, CL-12).
    """
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z]{3}", value) is None:
        return None
    return value.upper()
