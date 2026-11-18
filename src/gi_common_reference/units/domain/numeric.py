"""Aritmética exacta de Units (D3 y D7 del plan, RF-11, RF-13, RF-26 a RF-28).

Todo se calcula con `fractions.Fraction`; nunca con `float`. Este módulo define:

- la forma canónica de factores y desplazamientos (texto ⇔ valor, RF-13);
- el valor de entrada de una conversión (RF-26);
- el formato del resultado (RF-27, RF-28): exacto si su expansión decimal termina con a lo sumo
  34 dígitos significativos; si no, un único redondeo a 34 dígitos significativos al par.
"""

import re
from decimal import ROUND_HALF_EVEN, Context, Decimal
from fractions import Fraction
from math import gcd

SIGNIFICANT_DIGITS = 34
LOWER_LIMIT = Fraction(1, 10**40)  # |resultado| >= 10^-40 salvo el cero
UPPER_LIMIT = Fraction(10**40)  # |resultado| < 10^40

CANONICAL_DECIMAL = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?")
CANONICAL_FRACTION = re.compile(r"([1-9][0-9]*)/([1-9][0-9]*)")
REQUEST_VALUE = re.compile(r"-?(0|[1-9][0-9]{0,29})(\.[0-9]{1,30})?")

# El contexto no impone límites de exponente: el rango de salida se valida aparte.
_ROUNDING = Context(
    prec=SIGNIFICANT_DIGITS,
    rounding=ROUND_HALF_EVEN,
    Emax=999_999_999,
    Emin=-999_999_999,
)


class NumericFormatError(ValueError):
    """El texto no tiene la forma exigida (factor, desplazamiento o valor de entrada)."""


class ResultNotRepresentable(ArithmeticError):
    """El resultado es >= 10^40 o distinto de cero y menor que 10^-40 (RF-28)."""


def _decimal_fraction(text: str) -> Fraction:
    sign = -1 if text.startswith("-") else 1
    digits = text.removeprefix("-")
    whole, _, fraction = digits.partition(".")
    return Fraction(sign * int(whole + fraction), 10 ** len(fraction))


def parse_canonical_decimal(text: str) -> Fraction:
    """Decimal canónico (RF-13): sin ceros sobrantes, sin `+`, sin exponente y sin `-0`."""
    if not isinstance(text, str) or CANONICAL_DECIMAL.fullmatch(text) is None or text == "-0":
        raise NumericFormatError(f"decimal no canónico: «{text}»")
    return _decimal_fraction(text)


def parse_canonical_offset(text: str) -> Fraction:
    """Desplazamiento: siempre un decimal canónico (RF-13)."""
    return parse_canonical_decimal(text)


def _has_prime_other_than_2_and_5(value: int) -> bool:
    while value % 2 == 0:
        value //= 2
    while value % 5 == 0:
        value //= 5
    return value > 1


def parse_canonical_factor(text: str) -> Fraction:
    """Factor canónico (RF-13): decimal > 0, o `p/q` coprimos con `q > 1` de expansión infinita."""
    if not isinstance(text, str):
        raise NumericFormatError(f"factor no canónico: «{text}»")
    fraction = CANONICAL_FRACTION.fullmatch(text)
    if fraction is not None:
        numerator, denominator = int(fraction.group(1)), int(fraction.group(2))
        if (
            denominator > 1
            and gcd(numerator, denominator) == 1
            and _has_prime_other_than_2_and_5(denominator)
        ):
            return Fraction(numerator, denominator)
        raise NumericFormatError(f"factor no canónico: «{text}»")
    value = parse_canonical_decimal(text)
    if value <= 0:
        raise NumericFormatError(f"el factor debe ser mayor que 0: «{text}»")
    return value


def is_canonical_decimal(text: str) -> bool:
    try:
        parse_canonical_decimal(text)
    except NumericFormatError:
        return False
    return True


def is_canonical_factor(text: str) -> bool:
    try:
        parse_canonical_factor(text)
    except NumericFormatError:
        return False
    return True


def parse_value(text: str) -> Fraction:
    """Valor de entrada de una conversión (RF-26, CL-7); `-0` y `-0.0` son cero."""
    if not isinstance(text, str) or REQUEST_VALUE.fullmatch(text) is None:
        raise NumericFormatError("el valor no es un decimal admitido")
    return _decimal_fraction(text)


def _terminates(denominator: int) -> bool:
    return not _has_prime_other_than_2_and_5(denominator)


def _in_range(magnitude: Fraction) -> bool:
    return magnitude == 0 or LOWER_LIMIT <= magnitude < UPPER_LIMIT


def _exact_text(value: Fraction) -> tuple[str, int]:
    """Texto decimal exacto de `value` (cuyo denominador solo tiene los primos 2 y 5)."""
    places = 0
    while (10**places) % value.denominator != 0:
        places += 1
    scaled = abs(value.numerator) * (10**places // value.denominator)
    digits = str(scaled).rjust(places + 1, "0")
    whole, fraction = digits[: len(digits) - places], digits[len(digits) - places :]
    text = f"{whole}.{fraction}" if fraction else whole
    significant = len(str(scaled).rstrip("0"))
    return ("-" + text if value < 0 else text), significant


def _plain(number: Decimal) -> str:
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def format_result(value: Fraction) -> tuple[str, bool]:
    """`(texto, exacto)` del resultado exacto `value`; `ResultNotRepresentable` fuera de rango."""
    if not _in_range(abs(value)):
        raise ResultNotRepresentable("el resultado está fuera del rango representable")
    if value == 0:
        return "0", True
    if _terminates(value.denominator):
        text, significant = _exact_text(value)
        if significant <= SIGNIFICANT_DIGITS:
            return text, True
    rounded = _ROUNDING.divide(Decimal(value.numerator), Decimal(value.denominator))
    if not _in_range(abs(Fraction(rounded))):
        raise ResultNotRepresentable("el resultado redondeado está fuera del rango representable")
    return _plain(rounded), False
