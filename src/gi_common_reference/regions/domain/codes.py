"""Códigos UN M49: texto de 3 dígitos ASCII con ceros a la izquierda (`002`, `019`, `419`).

Es un identificador externo y versionable de la fuente de autoridad, nunca la identidad (RF-2).
"""

import re

CODE_FORMAT = re.compile(r"[0-9]{3}")


def is_valid_code(code: str) -> bool:
    """`019` es válido; `19`, `0019`, letras, espacios o dígitos no ASCII no (RF-3, RF-17)."""
    return CODE_FORMAT.fullmatch(code) is not None
