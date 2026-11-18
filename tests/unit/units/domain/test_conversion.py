"""T4: conversión pura sobre un `ConversionCatalog` inmutable (RF-21 a RF-30, CL-1 a CL-9)."""

import copy
import json
import uuid
from fractions import Fraction

import pytest
from tests.fixtures.units import (
    EXAMPLE,
    UNITS,
    associations,
    build_snapshot,
    kind_id,
    quantity_kind,
    unit,
    unit_id,
)

from gi_common_reference.units.domain.conversion import (
    ConversionCatalog,
    ConversionRejection,
    ConversionRequest,
    ConversionSuccess,
    convert,
    transform,
)
from gi_common_reference.units.domain.numeric import format_result

CATALOG = ConversionCatalog.from_snapshot(json.loads(EXAMPLE.read_text("utf-8")))


def run(
    catalog: ConversionCatalog,
    kind: str | None,
    value: str,
    source: str,
    target: str,
) -> ConversionSuccess | ConversionRejection:
    kind_ref = None if kind is None else (kind if "-" in kind else kind_id(kind))
    return convert(
        catalog,
        ConversionRequest(
            quantity_kind_id=kind_ref,
            value=value,
            from_unit_id=source if "-" in source else unit_id(source),
            to_unit_id=target if "-" in target else unit_id(target),
        ),
    )


def ok(
    kind: str, value: str, source: str, target: str, catalog: ConversionCatalog = CATALOG
) -> ConversionSuccess:
    result = run(catalog, kind, value, source, target)
    assert isinstance(result, ConversionSuccess), result
    return result


def rejected(
    code: str,
    kind: str | None,
    value: str,
    source: str,
    target: str,
    catalog: ConversionCatalog = CATALOG,
) -> None:
    result = run(catalog, kind, value, source, target)
    assert isinstance(result, ConversionRejection), result
    assert result.code == code, result


# --- casos del brief §13 (CA-1 a CA-3) -----------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "value", "source", "target", "expected"),
    [
        ("mass", "1000", "g", "kg", "1"),
        ("mass", "1", "t", "kg", "1000"),
        ("area", "1", "ha", "m2", "10000"),
        ("volume", "1", "m3", "L", "1000"),
        ("duration", "1", "h", "min", "60"),
        ("temperature", "0", "Cel", "K", "273.15"),
        ("temperature", "32", "degF", "Cel", "0"),
        ("temperature_difference", "1", "Cel", "K", "1"),
        ("mass_per_area", "150", "kg/ha", "g/m2", "15"),
        ("temperature", "-40", "Cel", "degF", "-40"),
        ("temperature", "-40", "degF", "Cel", "-40"),
        ("temperature", "100", "Cel", "degF", "212"),
        ("temperature", "273.15", "K", "Cel", "0"),
        ("speed", "36", "km/h", "m/s", "10"),
        ("mass_concentration", "5", "kg/m3", "g/L", "5"),
        ("mass_concentration", "1000", "mg/L", "kg/m3", "1"),
        ("density", "1", "g/cm3", "kg/L", "1"),
        ("mass", "1", "lb", "g", "453.59237"),
        ("length", "1", "mi", "km", "1.609344"),
        ("dimensionless_ratio", "50", "%", "one", "0.5"),
        ("dimensionless_ratio", "1", "ppm", "ppth", "0.001"),
    ],
)
def test_exact_conversions_of_the_catalog(
    kind: str, value: str, source: str, target: str, expected: str
) -> None:
    result = ok(kind, value, source, target)
    assert (result.result, result.exact) == (expected, True)
    assert result.unit_id == unit_id(target)
    assert result.quantity_kind_id == kind_id(kind)
    assert result.catalog_version == 1


@pytest.mark.parametrize(
    ("kind", "value", "source", "target", "expected"),
    [
        ("speed", "1", "km/h", "m/s", "0.2777777777777777777777777777777778"),
        ("temperature_difference", "1", "degF", "K", "0.5555555555555555555555555555555556"),
        ("temperature_difference", "1", "K", "degF", "1.8"),
    ],
)
def test_rounded_conversions_are_reported_as_not_exact(
    kind: str, value: str, source: str, target: str, expected: str
) -> None:
    result = ok(kind, value, source, target)
    assert result.result == expected
    assert result.exact is (expected == "1.8")


def test_one_km_per_hour_has_34_significant_digits_and_is_not_exact() -> None:
    result = ok("speed", "1", "km/h", "m/s")
    assert len(result.result.removeprefix("0.")) == 34
    assert result.exact is False


# --- magnitud, unidades e incompatibilidad (CA-4, CL-4, CL-5) -------------------------------------


def test_kg_to_liter_is_rejected_as_incompatible_in_either_kind() -> None:
    rejected("incompatible_units", "mass", "1", "kg", "L")
    rejected("incompatible_units", "volume", "1", "kg", "L")
    rejected("incompatible_units", "density", "1", "kg", "L")


def test_density_and_mass_concentration_share_a_dimension_but_not_the_units() -> None:
    rejected("incompatible_units", "density", "1", "kg/m3", "g/L")
    assert ok("mass_concentration", "1", "kg/m3", "g/L").result == "1"
    assert ok("mass_concentration", "1", "g/L", "kg/m3").result == "1"
    assert ok("density", "1", "g/cm3", "kg/m3").result == "1000"


def test_count_and_dimensionless_ratio_are_not_interchangeable() -> None:
    rejected("incompatible_units", "dimensionless_ratio", "1", "each", "one")
    rejected("incompatible_units", "count", "1", "%", "each")
    rejected("incompatible_units", "count", "1", "each", "one")


def test_units_of_different_kinds_are_rejected() -> None:
    rejected("incompatible_units", "mass", "1", "kg", "m")
    rejected("incompatible_units", "mass", "1", "m", "kg")


def test_the_kind_is_required_and_never_inferred() -> None:
    rejected("quantity_kind_required", None, "1", "g", "kg")
    rejected("quantity_kind_required", None, "1", "Cel", "K")


# --- identidad y conversión de una unidad a sí misma (CL-17, CL-18) ------------------------------


@pytest.mark.parametrize(
    ("kind", "key", "value", "expected"),
    [
        ("count", "each", "7", "7"),
        ("mass", "kg", "1.50", "1.5"),
        ("mass", "lb", "0", "0"),
        ("temperature", "Cel", "12.5", "12.5"),
        ("temperature", "degF", "-0", "0"),
        ("speed", "km/h", "36", "36"),
        ("temperature", "degF", "0.1", "0.1"),
    ],
)
def test_converting_a_unit_to_itself_returns_the_normalized_value(
    kind: str, key: str, value: str, expected: str
) -> None:
    result = ok(kind, value, key, key)
    assert (result.result, result.exact) == (expected, True)


def test_identity_of_a_60_digit_value_is_rounded_once_to_34_digits() -> None:
    result = ok("mass", "9" * 30 + "." + "9" * 30, "kg", "kg")
    assert result.exact is False
    assert result.result == "1" + "0" * 30  # redondea hacia arriba a 10^30


# --- negativo, cero y -0 (CL-7) ------------------------------------------------------------------


def test_negative_zero_input_is_accepted_and_returns_zero() -> None:
    assert ok("mass", "-0", "g", "kg").result == "0"
    assert ok("mass", "-0.0", "g", "kg").result == "0"
    assert ok("mass", "0", "g", "kg").result == "0"


def test_trailing_fractional_zeros_in_the_input_are_accepted() -> None:
    assert ok("mass", "1000.000", "g", "kg").result == "1"


def test_negative_values_convert() -> None:
    assert ok("mass", "-1500", "g", "kg").result == "-1.5"


@pytest.mark.parametrize(
    "value", ["1e3", "+1", "1,5", ".5", "5.", "007", " 1", "NaN", "Infinity", "", "9" * 31]
)
def test_invalid_input_values_are_rejected(value: str) -> None:
    rejected("invalid_value", "mass", value, "g", "kg")


def test_a_non_text_value_is_invalid() -> None:
    request = ConversionRequest(kind_id("mass"), 1000, unit_id("g"), unit_id("kg"))  # type: ignore[arg-type]
    result = convert(CATALOG, request)
    assert isinstance(result, ConversionRejection) and result.code == "invalid_value"


# --- rango (CL-8) --------------------------------------------------------------------------------


def scaled_catalog(factor: str) -> ConversionCatalog:
    """Magnitud con la unidad de referencia `u` y una unidad `big` de factor `factor`."""
    k = str(uuid.UUID(int=1))
    ref, big = str(uuid.UUID(int=2)), str(uuid.UUID(int=3))
    return ConversionCatalog.from_content(
        7,
        quantity_kinds=[
            {
                "quantity_kind_id": k,
                "code": "x",
                "conversion_type": "linear",
                "reference_unit_id": ref,
                "status": "active",
            }
        ],
        units=[{"unit_id": ref, "status": "active"}, {"unit_id": big, "status": "active"}],
        quantity_kind_units=[
            {
                "quantity_kind_id": k,
                "unit_id": ref,
                "factor": "1",
                "offset": "0",
                "status": "active",
            },
            {
                "quantity_kind_id": k,
                "unit_id": big,
                "factor": factor,
                "offset": "0",
                "status": "active",
            },
        ],
    )


KIND = str(uuid.UUID(int=1))
REF, BIG = str(uuid.UUID(int=2)), str(uuid.UUID(int=3))


def test_a_result_of_10_to_the_40_is_not_representable_and_just_below_is_not() -> None:
    catalog = scaled_catalog("1000000000000")  # 10^12
    rejected("result_not_representable", KIND, "1" + "0" * 28, BIG, REF, catalog)  # 10^40
    rejected("result_not_representable", KIND, "-1" + "0" * 28, BIG, REF, catalog)
    result = ok_raw(catalog, "1" + "0" * 27, BIG, REF)  # 10^39
    assert result.result == "1" + "0" * 39 and result.exact is True


def test_a_nonzero_result_below_10_to_the_minus_40_is_not_representable() -> None:
    catalog = scaled_catalog("1" + "0" * 40)  # 10^40
    result = ok_raw(catalog, "1", REF, BIG)  # 1 / 10^40 = 10^-40
    assert result.result == "0." + "0" * 39 + "1" and result.exact is True
    rejected("result_not_representable", KIND, "0.9", REF, BIG, catalog)
    rejected("result_not_representable", KIND, "-0.9", REF, BIG, catalog)
    assert ok_raw(catalog, "0", REF, BIG).result == "0"  # el cero sí


def ok_raw(catalog: ConversionCatalog, value: str, source: str, target: str) -> ConversionSuccess:
    result = run(catalog, KIND, value, source, target)
    assert isinstance(result, ConversionSuccess), result
    return result


# --- half-even en el dígito 34 a través de convert ------------------------------------------------


def halved_catalog() -> ConversionCatalog:
    return scaled_catalog("2")  # BIG vale 2 REF: REF → BIG divide por 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # …1235 / 2 = …94506175 (35 dígitos, empate; el anterior, 7, es impar → sube)
        ("223456789012345678901234567.8901235", "111728394506172839450617283.9450618"),
        # …1225 / 2 = …94506125 (empate; el anterior, 2, es par → baja)
        ("223456789012345678901234567.8901225", "111728394506172839450617283.9450612"),
        ("-223456789012345678901234567.8901225", "-111728394506172839450617283.9450612"),
        ("-223456789012345678901234567.8901235", "-111728394506172839450617283.9450618"),
    ],
)
def test_ties_through_convert_round_half_even(value: str, expected: str) -> None:
    result = ok_raw(halved_catalog(), value, REF, BIG)
    assert (result.result, result.exact) == (expected, False)


def test_a_value_of_34_digits_halved_with_a_final_five_is_exact_when_it_fits() -> None:
    result = ok_raw(halved_catalog(), "1.5", REF, BIG)
    assert (result.result, result.exact) == ("0.75", True)


# --- rechazos y su orden --------------------------------------------------------------------------


def test_ids_with_a_bad_format_are_rejected_before_anything_else() -> None:
    other = str(uuid.uuid4())
    rejected("invalid_quantity_kind_id", "not-a-uuid", "1", "g", "kg")
    rejected("invalid_quantity_kind_id", kind_id("mass").upper(), "1", "g", "kg")
    rejected("invalid_unit_id", "mass", "1", "bad-unit", "kg")
    rejected("invalid_unit_id", "mass", "1", "g", "bad-unit")
    rejected("invalid_unit_id", "mass", "x", "bad-unit", "kg")  # el id antes que el valor
    rejected("invalid_quantity_kind_id", "bad-kind", "x", "g", "kg")
    rejected("invalid_value", "mass", "x", other, other)  # el valor antes que la existencia
    rejected("invalid_value", other, "x", "g", "kg")


def test_an_unknown_kind_is_distinguished_from_an_unknown_unit() -> None:
    other = str(uuid.uuid4())
    rejected("quantity_kind_not_found", other, "1", "g", "kg")
    rejected("quantity_kind_not_found", other, "1", other, other)  # la magnitud antes que unidades
    rejected("unit_not_found", "mass", "1", other, "kg")
    rejected("unit_not_found", "mass", "1", "g", other)


def test_unit_existence_is_checked_before_compatibility() -> None:
    other = str(uuid.uuid4())
    rejected("unit_not_found", "mass", "1", "L", other)  # L existe pero no es de mass
    rejected("unit_not_found", "mass", "1", other, "L")


def test_an_inactive_kind_is_rejected_for_every_unit_pair() -> None:
    catalog = ConversionCatalog.from_snapshot(
        build_snapshot(
            codes=("mass",),
            quantity_kinds=[quantity_kind("mass", status="inactive")],
        )
    )
    rejected("inactive_quantity_kind", "mass", "1", "g", "kg", catalog)
    rejected("inactive_quantity_kind", "mass", "1", "kg", "kg", catalog)


def test_an_inactive_kind_is_checked_before_association_compatibility() -> None:
    catalog = ConversionCatalog.from_snapshot(
        build_snapshot(
            codes=("mass", "volume"),
            quantity_kinds=[
                quantity_kind("mass", status="inactive"),
                quantity_kind("volume"),
            ],
        )
    )
    rejected("inactive_quantity_kind", "mass", "1", "kg", "L", catalog)


def test_an_inactive_unit_is_rejected_as_source_or_target() -> None:
    document = build_snapshot(
        codes=("mass",),
        units=[
            unit("kg"),
            unit("g", status="inactive"),
            unit("mg"),
            unit("t"),
            unit("lb"),
            unit("oz"),
        ],
    )
    catalog = ConversionCatalog.from_snapshot(document)
    rejected("inactive_unit", "mass", "1", "g", "kg", catalog)
    rejected("inactive_unit", "mass", "1", "kg", "g", catalog)
    assert ok("mass", "1", "t", "kg", catalog).result == "1000"
    # el servicio no reactiva una unidad retirada: una conversión nueva se rechaza (RF-25)
    rejected("inactive_unit", "mass", "1", "g", "g", catalog)


def test_an_inactive_association_is_rejected_even_when_the_unit_is_active() -> None:
    rows = associations("mass")
    rows[1] = {**rows[1], "status": "inactive"}  # g
    document = build_snapshot(codes=("mass",), quantity_kind_units=rows)
    catalog = ConversionCatalog.from_snapshot(document)
    rejected("inactive_unit", "mass", "1", "g", "kg", catalog)
    rejected("inactive_unit", "mass", "1", "kg", "g", catalog)
    assert ok("mass", "1", "t", "kg", catalog).result == "1000"


def test_incompatibility_is_checked_before_inactivity() -> None:
    document = build_snapshot(
        codes=("mass", "volume"),
        units=[
            unit(key, status="inactive" if key == "L" else "active")
            for key in ("kg", "g", "mg", "t", "lb", "oz", "m3", "cm3", "mL", "L", "gal")
        ],
    )
    catalog = ConversionCatalog.from_snapshot(document)
    rejected("incompatible_units", "mass", "1", "kg", "L", catalog)
    rejected("inactive_unit", "volume", "1", "m3", "L", catalog)


def test_an_inactive_unit_in_the_old_version_still_works_in_that_version() -> None:
    """CL-10: cada versión tiene su propio catálogo inmutable; el estado de una no afecta a otra."""
    old = CATALOG
    new = ConversionCatalog.from_snapshot(
        build_snapshot(
            2,
            codes=("mass",),
            units=[
                unit("kg"),
                unit("g", status="inactive"),
                unit("mg"),
                unit("t"),
                unit("lb"),
                unit("oz"),
            ],
        )
    )
    assert ok("mass", "1000", "g", "kg", old).catalog_version == 1
    assert ok("mass", "1000", "g", "kg", old).result == "1"
    rejected("inactive_unit", "mass", "1000", "g", "kg", new)
    assert new.snapshot_version == 2 and old.snapshot_version == 1


def test_a_factor_correction_changes_only_the_new_catalog() -> None:
    """CL-11: dos catálogos, dos resultados; el anterior no cambia."""
    rows = [dict(r) for r in associations("mass")]
    rows[4] = {**rows[4], "factor": "0.4536"}  # lb
    new = ConversionCatalog.from_snapshot(
        build_snapshot(2, codes=("mass",), quantity_kind_units=rows)
    )
    assert ok("mass", "1", "lb", "kg").result == "0.45359237"
    assert ok("mass", "1", "lb", "kg", new).result == "0.4536"
    assert ok("mass", "1", "lb", "kg", new).catalog_version == 2


# --- inmutabilidad y determinismo -----------------------------------------------------------------


def test_the_catalog_does_not_change_when_the_source_document_changes() -> None:
    document = build_snapshot()
    catalog = ConversionCatalog.from_snapshot(document)
    before = ok("mass", "1000", "g", "kg", catalog).result
    document["quantity_kind_units"][1]["factor"] = "5"
    document["units"][1]["status"] = "inactive"
    assert ok("mass", "1000", "g", "kg", catalog).result == before == "1"


def test_the_catalog_exposes_no_mutating_api() -> None:
    with pytest.raises((AttributeError, TypeError)):
        CATALOG.snapshot_version = 9  # type: ignore[misc]
    with pytest.raises(TypeError):
        CATALOG.associations[(kind_id("mass"), unit_id("g"))] = None  # type: ignore[index]


def test_the_same_request_always_gives_the_same_result() -> None:
    results = {repr(run(CATALOG, "speed", "1", "km/h", "m/s")) for _ in range(5)}
    assert len(results) == 1


def test_building_from_content_equals_building_from_the_document() -> None:
    document = build_snapshot()
    built = ConversionCatalog.from_content(
        document["snapshot_version"],
        quantity_kinds=document["quantity_kinds"],
        units=document["units"],
        quantity_kind_units=document["quantity_kind_units"],
    )
    assert built == ConversionCatalog.from_snapshot(copy.deepcopy(document))


def test_a_malformed_factor_in_the_content_is_a_construction_error() -> None:
    document = build_snapshot(codes=("mass",))
    document["quantity_kind_units"][0]["factor"] = "1.0"
    with pytest.raises(ValueError, match="factor"):
        ConversionCatalog.from_snapshot(document)


# --- ida y vuelta sobre todos los pares del ejemplo (CL-9, CA-8) ---

VALUES = ["0", "1", "-1", "2.5", "123.456", "-273.15", "0.000123", "99999", "1000000.000001"]


def half_ulp(value: Fraction) -> Fraction:
    """Medio ulp a 34 dígitos significativos de `value` (exacto, con fracciones)."""
    magnitude = abs(value)
    if magnitude == 0:
        return Fraction(0)
    exponent = len(str(magnitude.numerator)) - len(str(magnitude.denominator))
    while Fraction(10) ** exponent > magnitude:
        exponent -= 1
    while Fraction(10) ** (exponent + 1) <= magnitude:
        exponent += 1
    return Fraction(10) ** (exponent - 33) / 2


def kind_pairs() -> list[tuple[str, str, str]]:
    document = json.loads(EXAMPLE.read_text("utf-8"))
    keys = {unit_id(key): key for key in UNITS}
    pairs = []
    for kind in document["quantity_kinds"]:
        members = [
            row["unit_id"]
            for row in document["quantity_kind_units"]
            if row["quantity_kind_id"] == kind["quantity_kind_id"]
        ]
        for source in members:
            for target in members:
                pairs.append((kind["code"], keys[source], keys[target]))
    return pairs


ALL_PAIRS = kind_pairs()


def test_the_example_covers_many_ordered_pairs() -> None:
    assert len(ALL_PAIRS) >= 150
    assert {kind for kind, _, _ in ALL_PAIRS} == {
        k["code"] for k in json.loads(EXAMPLE.read_text("utf-8"))["quantity_kinds"]
    }


@pytest.mark.parametrize("value", VALUES)
def test_round_trip_over_every_ordered_pair_of_every_kind(value: str) -> None:
    x0 = Fraction(value)
    for kind, source, target in ALL_PAIRS:
        forward = ok(kind, value, source, target)
        a_source = CATALOG.associations[(kind_id(kind), unit_id(source))]
        a_target = CATALOG.associations[(kind_id(kind), unit_id(target))]
        y1 = Fraction(forward.result)
        exact_forward = transform(a_source, a_target, x0)
        assert forward.exact is (y1 == exact_forward)
        # cota del primer redondeo, propagada a la unidad original por la transformación exacta
        err1 = Fraction(0) if forward.exact else half_ulp(y1)
        slope_back = a_target.factor / a_source.factor
        z = transform(a_target, a_source, y1)  # exacto, sin volver a redondear
        assert abs(z - x0) <= err1 * slope_back, (kind, source, target, value)
        text, exact_back = format_result(z)
        final = Fraction(text)
        # cota total: lo propagado más medio ulp del resultado final redondeado
        bound = err1 * slope_back + (Fraction(0) if exact_back else half_ulp(final))
        assert abs(final - x0) <= bound, (kind, source, target, value)
        if forward.exact and exact_back:
            assert final == x0, (kind, source, target, value)
        if forward.exact:
            assert z == x0


def test_round_trip_is_byte_exact_when_both_directions_are_exact_through_the_api() -> None:
    for kind, source, target in ALL_PAIRS:
        forward = ok(kind, "12.5", source, target)
        if not forward.exact or len(forward.result.split(".")[-1]) > 30:
            continue
        if len(forward.result.lstrip("-").split(".")[0]) > 30:
            continue
        back = ok(kind, forward.result, target, source)
        if back.exact:
            assert Fraction(back.result) == Fraction("12.5"), (kind, source, target)


def test_json_of_the_result_is_text() -> None:
    result = ok("mass", "1000", "g", "kg")
    assert (
        json.dumps({"result": result.result, "exact": result.exact})
        == '{"result": "1", "exact": true}'
    )
