"""T5: parser y evaluador UCUM sobre la tabla oficial empaquetada (D8, RF-15, RF-17, CL-12)."""

import json
from fractions import Fraction

import pytest
from tests.fixtures.units import EXAMPLE
from tests.unit.units.helpers import ucum_table

from gi_common_reference.units.domain.ucum import BASE_UNITS, UcumError, UcumEvaluator

EVALUATOR = UcumEvaluator(ucum_table())


def dimension(**powers: int) -> tuple[int, ...]:
    return tuple(powers.get(base, 0) for base in BASE_UNITS)


def test_the_base_units_are_the_seven_of_ucum() -> None:
    assert BASE_UNITS == ("m", "s", "g", "rad", "K", "C", "cd")


@pytest.mark.parametrize(
    ("code", "scale", "dim"),
    [
        ("m", Fraction(1), dimension(m=1)),
        ("g", Fraction(1), dimension(g=1)),
        ("kg", Fraction(1000), dimension(g=1)),
        ("mg", Fraction(1, 1000), dimension(g=1)),
        ("t", Fraction(10**6), dimension(g=1)),
        ("[lb_av]", Fraction("453.59237"), dimension(g=1)),
        ("[oz_av]", Fraction("28.349523125"), dimension(g=1)),
        ("km", Fraction(1000), dimension(m=1)),
        ("dam", Fraction(10), dimension(m=1)),
        ("[in_i]", Fraction("0.0254"), dimension(m=1)),
        ("[mi_i]", Fraction("1609.344"), dimension(m=1)),
        ("m2", Fraction(1), dimension(m=2)),
        ("cm2", Fraction(1, 10**4), dimension(m=2)),
        ("har", Fraction(10**4), dimension(m=2)),
        ("m3", Fraction(1), dimension(m=3)),
        ("L", Fraction(1, 1000), dimension(m=3)),
        ("mL", Fraction(1, 10**6), dimension(m=3)),
        ("[gal_us]", Fraction("0.003785411784"), dimension(m=3)),
        ("h", Fraction(3600), dimension(s=1)),
        ("min", Fraction(60), dimension(s=1)),
        ("d", Fraction(86400), dimension(s=1)),
        ("wk", Fraction(604800), dimension(s=1)),
        ("m/s", Fraction(1), dimension(m=1, s=-1)),
        ("km/h", Fraction(5, 18), dimension(m=1, s=-1)),
        ("[mi_i]/h", Fraction("0.44704"), dimension(m=1, s=-1)),
        ("kg/m3", Fraction(1000), dimension(g=1, m=-3)),
        ("g/L", Fraction(1000), dimension(g=1, m=-3)),
        ("kg/har", Fraction(1, 10), dimension(g=1, m=-2)),
        ("t/har", Fraction(100), dimension(g=1, m=-2)),
        ("L/har", Fraction(1, 10**7), dimension(m=1)),
        ("mL/m2", Fraction(1, 10**6), dimension(m=1)),
        ("kg/m2", Fraction(1000), dimension(g=1, m=-2)),
        ("m3/m2", Fraction(1), dimension(m=1)),
        ("%", Fraction(1, 100), dimension()),
        ("[ppth]", Fraction(1, 1000), dimension()),
        ("[ppm]", Fraction(1, 10**6), dimension()),
        ("{each}", Fraction(1), dimension()),
        ("1", Fraction(1), dimension()),
        ("10*-2", Fraction(1, 100), dimension()),
        ("10*3", Fraction(1000), dimension()),
        ("10^-3", Fraction(1, 1000), dimension()),
        ("K", Fraction(1), dimension(K=1)),
        ("N", Fraction(1000), dimension(g=1, m=1, s=-2)),
        ("kPa", Fraction(10**6), dimension(g=1, m=-1, s=-2)),
    ],
)
def test_expected_scale_and_dimension(code: str, scale: Fraction, dim: tuple[int, ...]) -> None:
    result = EVALUATOR.evaluate(code)
    assert (result.scale, result.dimension, result.special) == (scale, dim, False)


@pytest.mark.parametrize(
    ("code", "scale", "offset", "dim"),
    [
        ("Cel", Fraction(1), Fraction("273.15"), dimension(K=1)),
        ("[degF]", Fraction(5, 9), Fraction("459.67"), dimension(K=1)),
    ],
)
def test_the_two_supported_special_units(
    code: str, scale: Fraction, offset: Fraction, dim: tuple[int, ...]
) -> None:
    result = EVALUATOR.evaluate(code)
    assert result.special and (result.scale, result.offset, result.dimension) == (
        scale,
        offset,
        dim,
    )


@pytest.mark.parametrize(
    ("code", "scale", "dim"),
    [
        ("/s", Fraction(1), dimension(s=-1)),
        ("m/s/s", Fraction(1), dimension(m=1, s=-2)),
        ("kg.m/s2", Fraction(1000), dimension(g=1, m=1, s=-2)),
        ("kg/(m.s)", Fraction(1000), dimension(g=1, m=-1, s=-1)),
        ("kg/m.s", Fraction(1000), dimension(g=1, m=-1, s=1)),  # asociativa a la izquierda
        ("m{foo}", Fraction(1), dimension(m=1)),
        ("{foo}", Fraction(1), dimension()),
        ("m2{foo}/s", Fraction(1), dimension(m=2, s=-1)),
        ("10.m", Fraction(10), dimension(m=1)),
        ("2.m", Fraction(2), dimension(m=1)),
        ("m-1", Fraction(1), dimension(m=-1)),
        ("m+2", Fraction(1), dimension(m=2)),
        ("(m)", Fraction(1), dimension(m=1)),
        ("((m.s))/s", Fraction(1), dimension(m=1)),
        ("cd", Fraction(1), dimension(cd=1)),  # el átomo completo antes que c + d
        ("min", Fraction(60), dimension(s=1)),
        ("{a_b-c/d}", Fraction(1), dimension()),
    ],
)
def test_the_grammar_operators_exponents_annotations_and_parentheses(
    code: str, scale: Fraction, dim: tuple[int, ...]
) -> None:
    result = EVALUATOR.evaluate(code)
    assert (result.scale, result.dimension) == (scale, dim)


@pytest.mark.parametrize(
    "code",
    [
        "kg//m",  # CL-12: mal formado
        "KG",  # mayúsculas incorrectas
        "Kg",
        "[foo]",  # átomo desconocido
        "foo",
        "k[lb_av]",  # prefijo sobre átomo no métrico
        "kmin",
        "ha",  # ha no es un código UCUM (es «har»)
        "Cel/s",  # especial compuesta
        "Cel.s",
        "m.Cel",
        "kCel",  # prefijo sobre especial
        "mCel",
        "Cel2",  # exponente sobre especial
        "Cel-1",
        "(Cel)",
        "/Cel",
        "2Cel",
        "Cel{x}",
        "[degF]2",
        "[degF]/s",
        "m[degF]",
        "[degRe]",  # especial no soportada
        "[pH]",
        "B[V]",
        "[iU]",  # arbitraria
        "k[iU]",
        "[hp_X]",
        "[pi]",  # irracional: no representable exactamente
        "deg",
        "",
        " kg",
        "kg ",
        "k g",
        "m/",
        "/",
        ".m",
        "m.",
        "m..s",
        "m/.s",
        "(m",
        "m)",
        "()",
        "(m))",
        "m(s)",
        "(m)2",
        "m-",
        "m+",
        "m2.",
        "m--2",
        "{unclosed",
        "m{a{b}c}",
        "m}",
        "m{a b}",  # el espacio no es un carácter de anotación
        "m{ñ}",
        "m2{x}{y}",
        "2m",
        "m 2",
        "m^2",
        "m*2",
        "1.5m",
        "1e3",
        "m/s2 ",
        "kg\n",
        "m\x00",
        "٣",
    ],
)
def test_invalid_ucum_codes_are_rejected_with_a_ucum_error(code: str) -> None:
    with pytest.raises(UcumError):
        EVALUATOR.evaluate(code)


def test_the_error_names_the_problem() -> None:
    with pytest.raises(UcumError, match="no métric"):
        EVALUATOR.evaluate("k[lb_av]")
    with pytest.raises(UcumError, match="especial"):
        EVALUATOR.evaluate("Cel/s")
    with pytest.raises(UcumError, match="arbitraria"):
        EVALUATOR.evaluate("[iU]")
    with pytest.raises(UcumError, match="desconocid"):
        EVALUATOR.evaluate("[foo]")


def test_evaluations_are_cached() -> None:
    evaluator = UcumEvaluator(ucum_table())
    first = evaluator.evaluate("kg/har")
    assert evaluator.evaluate("kg/har") is first
    assert evaluator.evaluate("[lb_av]") is evaluator.evaluate("[lb_av]")
    with pytest.raises(UcumError):
        evaluator.evaluate("[foo]")
    with pytest.raises(UcumError):
        evaluator.evaluate("[foo]")


def test_the_unit_text_is_case_sensitive_and_never_normalized() -> None:
    assert EVALUATOR.evaluate("mL").scale == Fraction(1, 10**6)
    assert EVALUATOR.evaluate("ml").scale == Fraction(1, 10**6)  # «l» es otro átomo, también válido
    assert EVALUATOR.evaluate("ML").scale == Fraction(1000)  # mega-litro: otro código, otro valor
    for wrong in ("Ml ", "MM", "Kg", "KM", "Kel"):
        with pytest.raises(UcumError):
            EVALUATOR.evaluate(wrong)


def test_every_ucum_code_of_the_published_example_is_evaluated() -> None:
    document = json.loads(EXAMPLE.read_text("utf-8"))
    codes = [row["ucum_code"] for row in document["units"] if row["ucum_code"] is not None]
    assert len(codes) >= 50
    for code in codes:
        result = EVALUATOR.evaluate(code)
        assert result.scale > 0, code


def test_every_atom_of_the_table_either_evaluates_or_fails_with_a_ucum_error() -> None:
    table = ucum_table()
    evaluated = 0
    for code in table.atoms:
        try:
            result = EVALUATOR.evaluate(code)
        except UcumError:
            continue
        assert result.scale > 0
        evaluated += 1
    assert evaluated > 200


def test_a_prefix_on_a_non_metric_atom_is_always_rejected() -> None:
    table = ucum_table()
    checked = 0
    for code, atom in table.atoms.items():
        if atom.is_metric or atom.is_special or atom.is_arbitrary or code[0] in "[{":
            continue
        with pytest.raises(UcumError):
            EVALUATOR.evaluate("k" + code)
        checked += 1
    assert checked > 5


def test_a_prefix_on_a_metric_atom_scales_it() -> None:
    assert EVALUATOR.evaluate("km").scale == 1000 * EVALUATOR.evaluate("m").scale
    assert EVALUATOR.evaluate("kg").scale == 1000 * EVALUATOR.evaluate("g").scale
    assert EVALUATOR.evaluate("mmol").scale == EVALUATOR.evaluate("mol").scale / 1000
    assert EVALUATOR.evaluate("daL").scale == 10 * EVALUATOR.evaluate("L").scale
