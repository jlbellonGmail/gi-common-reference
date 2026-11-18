"""T4: forma canónica de factor y desplazamiento, valores de entrada y formato del resultado."""

from decimal import Decimal
from fractions import Fraction

import pytest

from gi_common_reference.units.domain.numeric import (
    NumericFormatError,
    ResultNotRepresentable,
    format_result,
    is_canonical_decimal,
    is_canonical_factor,
    parse_canonical_decimal,
    parse_canonical_factor,
    parse_canonical_offset,
    parse_value,
)

VALID_FACTORS = [
    ("1", Fraction(1)),
    ("1000", Fraction(1000)),
    ("0.45359237", Fraction(45359237, 10**8)),
    ("0.000001", Fraction(1, 10**6)),
    ("5/9", Fraction(5, 9)),
    ("5/18", Fraction(5, 18)),
    ("1/3", Fraction(1, 3)),
    ("22/7", Fraction(22, 7)),
]
INVALID_FACTORS = [
    "1.0", "01", "+1", "2/4", "1/2", "1/1", "0", "-1", "1e3", "0.0", "-0", "1/0", "0/5",
    "-1/3", "1/-3", "1/3/5", "3/6", " 1", "1 ", "1.", ".5", "", "1/5", "3/10", "1/25", "٣",
    "1\n", "5/ 9", "NaN",
]  # fmt: skip


@pytest.mark.parametrize(("text", "expected"), VALID_FACTORS)
def test_canonical_factors_are_parsed_exactly(text: str, expected: Fraction) -> None:
    assert parse_canonical_factor(text) == expected
    assert is_canonical_factor(text)


@pytest.mark.parametrize("text", INVALID_FACTORS)
def test_non_canonical_factors_are_rejected(text: str) -> None:
    with pytest.raises(NumericFormatError):
        parse_canonical_factor(text)
    assert not is_canonical_factor(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", 0),
        ("273.15", Fraction(27315, 100)),
        ("459.67", Fraction(45967, 100)),
        ("-5", -5),
        ("-0.5", Fraction(-1, 2)),
        ("10", 10),
    ],
)
def test_canonical_offsets_are_decimals(text: str, expected: Fraction) -> None:
    assert parse_canonical_offset(text) == expected
    assert parse_canonical_decimal(text) == expected
    assert is_canonical_decimal(text)


@pytest.mark.parametrize(
    "text",
    ["-0", "0.0", "00", "+1", "1.50", "1e2", "1/3", "5/9", "", " 1", ".5", "5.", "--1", "0x1"],
)
def test_non_canonical_offsets_are_rejected(text: str) -> None:
    with pytest.raises(NumericFormatError):
        parse_canonical_offset(text)
    assert not is_canonical_decimal(text)


# --- valores de entrada (RF-26, CL-7) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", 0),
        ("-0", 0),
        ("-0.0", 0),
        ("0.0", 0),
        ("1", 1),
        ("-40", -40),
        ("1.50", Fraction(3, 2)),
        ("1.500", Fraction(3, 2)),
        ("0.5", Fraction(1, 2)),
        ("9" * 30, 10**30 - 1),
        ("-" + "9" * 30, -(10**30 - 1)),
        ("0." + "1" * 30, Fraction(int("1" * 30), 10**30)),
        ("9" * 30 + "." + "9" * 30, Fraction(10**60 - 1, 10**30)),
    ],
)
def test_valid_request_values(text: str, expected: Fraction) -> None:
    assert parse_value(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "1e3", "+1", "1,5", ".5", "5.", "007", " 1", "1 ", "NaN", "Infinity", "-Infinity", "",
        "1_000", "--1", "- 1", "0x10", "1.2.3", "٣", "1\n", "00", "-", ".", "-.5",
        "9" * 31, "0." + "1" * 31, "1" + "0" * 30,
    ],
)  # fmt: skip
def test_invalid_request_values(text: str) -> None:
    with pytest.raises(NumericFormatError):
        parse_value(text)


def test_a_non_string_value_is_invalid() -> None:
    with pytest.raises(NumericFormatError):
        parse_value(5)  # type: ignore[arg-type]
    with pytest.raises(NumericFormatError):
        parse_value(1.5)  # type: ignore[arg-type]


# --- formato del resultado (RF-27, RF-28, CL-8) --------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Fraction(0), "0"),
        (Fraction(1), "1"),
        (Fraction(-40), "-40"),
        (Fraction(1000), "1000"),
        (Fraction(10**30), "1" + "0" * 30),
        (Fraction(3, 2), "1.5"),
        (Fraction(27315, 100), "273.15"),
        (Fraction(-1, 8), "-0.125"),
        (Fraction(1, 10**40), "0." + "0" * 39 + "1"),
        (Fraction(10**39), "1" + "0" * 39),
        (Fraction(9 * 10**39), "9" + "0" * 39),
    ],
)
def test_exact_results_are_canonical_text(value: Fraction, text: str) -> None:
    assert format_result(value) == (text, True)


def test_a_result_with_exactly_34_significant_digits_is_exact() -> None:
    value = Fraction(int("1234567890123456789012345678901234"), 10**10)
    assert format_result(value) == ("123456789012345678901234.5678901234", True)


def test_trailing_zeros_of_the_integer_part_are_not_significant() -> None:
    # 5 × 10^39 tiene un solo dígito significativo: exacto aunque se escriba con 40 dígitos.
    assert format_result(Fraction(5 * 10**39)) == ("5" + "0" * 39, True)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Fraction(1, 3), "0." + "3" * 34),
        (Fraction(2, 3), "0." + "6" * 33 + "7"),
        (Fraction(-2, 3), "-0." + "6" * 33 + "7"),
        (Fraction(5, 18), "0.2777777777777777777777777777777778"),
        (Fraction(5, 9), "0.5555555555555555555555555555555556"),
        (Fraction(10, 3), "3." + "3" * 33),
        (Fraction(10**39, 3), "3" * 34 + "0" * 5),
    ],
)
def test_inexact_results_are_rounded_once_to_34_significant_digits(
    value: Fraction, text: str
) -> None:
    assert format_result(value) == (text, False)


@pytest.mark.parametrize(
    ("exact", "text"),
    [
        # 35 dígitos significativos, el último es 5 (empate); el anterior decide (half-even).
        ("1234567890123456789012345678901234.5", "1234567890123456789012345678901234"),  # par
        ("1234567890123456789012345678901235.5", "1234567890123456789012345678901236"),  # impar
        ("-1234567890123456789012345678901234.5", "-1234567890123456789012345678901234"),
        ("-1234567890123456789012345678901235.5", "-1234567890123456789012345678901236"),
        ("0.12345678901234567890123456789012345", "0.1234567890123456789012345678901234"),
        ("0.12345678901234567890123456789012355", "0.1234567890123456789012345678901236"),
        # no es un empate: por encima o por debajo de la mitad.
        ("1234567890123456789012345678901234.51", "1234567890123456789012345678901235"),
        ("1234567890123456789012345678901234.49", "1234567890123456789012345678901234"),
        ("1234567890123456789012345678901235.49", "1234567890123456789012345678901235"),
    ],
)
def test_ties_at_the_34th_digit_round_half_even(exact: str, text: str) -> None:
    assert format_result(Fraction(exact)) == (text, False)


def test_rounding_carries_into_a_new_digit() -> None:
    value = Fraction("9999999999999999999999999999999999.5")
    assert format_result(value) == ("10000000000000000000000000000000000", False)


@pytest.mark.parametrize(
    "value", [Fraction(10**40), Fraction(-(10**40)), Fraction(10**40 + 1), Fraction(10**50)]
)
def test_results_of_10_to_the_40_or_more_are_not_representable(value: Fraction) -> None:
    with pytest.raises(ResultNotRepresentable):
        format_result(value)


def test_a_result_that_rounds_up_to_10_to_the_40_is_not_representable() -> None:
    value = Fraction(10**40) - Fraction(1, 10**10)  # 9.999...9 e39, redondea a 10^40
    with pytest.raises(ResultNotRepresentable):
        format_result(value)


@pytest.mark.parametrize(
    "value",
    [Fraction(1, 10**40 + 1), Fraction(-1, 10**41), Fraction(1, 10**41), Fraction(1, 3 * 10**40)],
)
def test_nonzero_results_below_10_to_the_minus_40_are_not_representable(value: Fraction) -> None:
    with pytest.raises(ResultNotRepresentable):
        format_result(value)


def test_the_boundaries_themselves() -> None:
    assert format_result(Fraction(1, 10**40)) == ("0." + "0" * 39 + "1", True)
    assert format_result(Fraction(-1, 10**40))[0] == "-0." + "0" * 39 + "1"
    assert format_result(Fraction(10**40 - 10**6)) == ("9" * 34 + "0" * 6, True)


def test_no_exponent_and_no_trailing_zeros_in_inexact_results() -> None:
    text, exact = format_result(Fraction(1, 3 * 10**30))
    assert not exact and "e" not in text.lower() and not text.endswith("0")
    assert Decimal(text) == Decimal("3.333333333333333333333333333333333E-31")


def test_the_result_is_never_negative_zero() -> None:
    assert format_result(-Fraction(0)) == ("0", True)
