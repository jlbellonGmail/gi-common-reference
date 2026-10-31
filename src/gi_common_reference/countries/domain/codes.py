"""Formato de los códigos de Countries: texto ASCII, nunca normalizado ni interpretado (RF-5).

`NA` (Namibia) es un código válido y no un nulo; `004` conserva sus ceros y `4` no es válido. Los
códigos ISO 3166-1 y E.164 son identificadores externos y versionables, nunca la identidad (RF-2).
"""

import re

from gi_common_reference.countries.domain.model import CodeKind

ALPHA2 = re.compile(r"[A-Z]{2}")
ALPHA3 = re.compile(r"[A-Z]{3}")
NUMERIC_CODE = re.compile(r"[0-9]{3}")
CALLING_CODE = re.compile(r"[1-9][0-9]{0,2}")
_BY_KIND: dict[CodeKind, re.Pattern[str]] = {
    "alpha2": ALPHA2,
    "alpha3": ALPHA3,
    "numeric_code": NUMERIC_CODE,
}


def is_valid_alpha2(code: str) -> bool:
    """2 letras A-Z mayúsculas: `NA` sí; `na`, ` NA`, `N1` no."""
    return ALPHA2.fullmatch(code) is not None


def is_valid_alpha3(code: str) -> bool:
    return ALPHA3.fullmatch(code) is not None


def is_valid_numeric_code(code: str) -> bool:
    """3 dígitos ASCII con ceros a la izquierda: `004` sí; `4`, `04` y dígitos no ASCII no."""
    return NUMERIC_CODE.fullmatch(code) is not None


def is_valid_calling_code(code: str) -> bool:
    """1 a 3 dígitos sin `+` ni cero inicial (`1`, `54`, `264`)."""
    return CALLING_CODE.fullmatch(code) is not None


def is_valid_code(kind: CodeKind, code: str) -> bool:
    return _BY_KIND[kind].fullmatch(code) is not None
