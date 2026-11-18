"""T5: validación del catálogo como función pura, pasos 3 a 10 del plan (RF-3 a RF-19, RF-43)."""

import copy
import uuid
from typing import Any

import pytest
from tests.fixtures.units import (
    EN,
    ES,
    build_snapshot,
    kind_id,
    provenance,
    unit,
    unit_id,
    unit_names,
)
from tests.unit.units.helpers import (
    FR,
    association_row,
    edit,
    kind_row,
    locale_view,
    messages,
    plan,
    published,
    rules,
    snapshot,
    unit_row,
)

from gi_common_reference.units.domain.catalog import CatalogPlan, incoming_from
from gi_common_reference.units.domain.model import LocaleCatalog, LocaleInfo

OTHER = str(uuid.uuid4())


def only(result: CatalogPlan, *expected: str) -> None:
    assert not result.ok
    assert rules(result) == set(expected), messages(result)


# --- documento válido -----------------------------------------------------------------------------


def test_the_published_example_creates_everything() -> None:
    result = plan(snapshot())
    assert result.ok, messages(result)
    assert len(result.new_quantity_kinds) == 14
    assert len(result.new_units) == 50
    assert len(result.new_associations) == 54
    assert len(result.new_kind_names) == 28 and len(result.new_unit_names) == 100
    assert not result.updated_units and not result.updated_quantity_kinds
    assert not result.is_empty


def test_the_plan_lists_units_before_kinds_before_associations() -> None:
    result = plan(snapshot())
    assert result.new_units[0].unit_id == unit_id("kg")
    assert result.new_quantity_kinds[0].quantity_kind_id == kind_id("mass")
    assert result.new_associations[0].factor == "1"


def test_resubmitting_the_same_content_is_an_empty_plan() -> None:
    document = snapshot()
    result = plan(document, published(document))
    assert result.ok and result.is_empty


def test_a_plan_accepts_the_domain_view_of_the_document_too() -> None:
    document = snapshot()
    assert plan(incoming_from(document)).ok  # type: ignore[arg-type]


def test_a_second_version_with_a_status_change_updates_only_that_record() -> None:
    first = snapshot()
    second = edit(first, lambda d: unit_row(d, "g").update(status="inactive"))
    result = plan(second, published(first))
    assert result.ok, messages(result)
    assert [u.unit_id for u in result.updated_units] == [unit_id("g")]
    assert not result.new_units and not result.updated_associations


# --- paso 3: contexto -----------------------------------------------------------------------------


def test_step_3_requires_a_published_locale_catalog() -> None:
    only(plan(snapshot(), locales=locale_view(version=None)), "RF-19")


@pytest.mark.parametrize("status", ["inactive"])
def test_step_3_requires_en_and_es_active(status: str) -> None:
    only(plan(snapshot(), locales=locale_view(en=status)), "RF-19")
    only(plan(snapshot(), locales=locale_view(es=status)), "RF-19")


def test_step_3_requires_en_and_es_to_exist_with_the_expected_code() -> None:
    result = plan(snapshot(), locales=locale_view(en_code="xx"))
    only(result, "RF-19")
    assert "xx" in " ".join(messages(result))
    missing = plan(snapshot(), locales=LocaleCatalog(1, (LocaleInfo(EN, "en", "active"),)))
    only(missing, "RF-19")


def test_step_3_failure_hides_later_steps() -> None:
    bad = edit(snapshot(), lambda d: kind_row(d, "mass").update(code="Mass"))
    only(plan(bad, locales=locale_view(es="inactive")), "RF-19")


# --- paso 4: identidad y completitud --------------------------------------------------------------


def test_step_4_rejects_malformed_and_repeated_identities() -> None:
    only(plan(edit(snapshot(), lambda d: unit_row(d, "g").update(unit_id="nope"))), "RF-2")
    only(
        plan(edit(snapshot(), lambda d: d["units"].append(copy.deepcopy(d["units"][0])))),
        "RF-2",
    )
    only(
        plan(edit(snapshot(), lambda d: d["quantity_kinds"].append(d["quantity_kinds"][0]))),
        "RF-2",
    )
    only(
        plan(
            edit(snapshot(), lambda d: kind_row(d, "mass").update(quantity_kind_id=OTHER.upper()))
        ),
        "RF-2",
    )


def test_step_4_rejects_repeated_association_and_localization_pairs() -> None:
    only(
        plan(
            edit(snapshot(), lambda d: d["quantity_kind_units"].append(d["quantity_kind_units"][0]))
        ),
        "RF-10",
    )
    only(
        plan(edit(snapshot(), lambda d: d["unit_names"].append(d["unit_names"][0]))),
        "RF-18",
    )
    only(
        plan(
            edit(snapshot(), lambda d: d["quantity_kind_names"].append(d["quantity_kind_names"][0]))
        ),
        "RF-18",
    )


def remove_kind(d: dict[str, Any]) -> None:
    d["quantity_kinds"] = [k for k in d["quantity_kinds"] if k["code"] != "count"]


def remove_unit(d: dict[str, Any]) -> None:
    d["units"] = [u for u in d["units"] if u["unit_id"] != unit_id("ppm")]


def remove_association(d: dict[str, Any]) -> None:
    gone = association_row(d, "mass", "oz")
    d["quantity_kind_units"] = [r for r in d["quantity_kind_units"] if r is not gone]


def remove_kind_name(d: dict[str, Any]) -> None:
    d["quantity_kind_names"] = d["quantity_kind_names"][1:]


def remove_unit_name(d: dict[str, Any]) -> None:
    d["unit_names"] = d["unit_names"][1:]


@pytest.mark.parametrize(
    ("remove", "needle"),
    [
        (remove_kind, "count"),
        (remove_unit, unit_id("ppm")),
        (remove_association, unit_id("oz")),
        (remove_kind_name, kind_id("mass")),
        (remove_unit_name, unit_id("kg")),
    ],
)
def test_step_4_rejects_omissions_of_every_published_entity(remove: Any, needle: str) -> None:
    first = snapshot()
    result = plan(edit(first, remove), published(first))
    only(result, "RF-43")
    assert any(needle in message for message in messages(result))


def test_step_4_is_the_first_failing_step_and_reports_all_its_violations() -> None:
    first = snapshot()

    def change(d: dict[str, Any]) -> None:
        remove_kind(d)
        remove_unit(d)
        kind_row(d, "mass").update(code="Mass")  # paso 5: no debe aparecer
        unit_row(d, "kg").update(ucum_code="KG//")  # paso 8: no debe aparecer

    result = plan(edit(first, change), published(first))
    only(result, "RF-43")
    assert len(result.violations) == 2


# --- paso 5: códigos ------------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["Mass", "m", "1mass", "mass-x", "mass x", "a" * 65, "", "ñ"])
def test_step_5_rejects_malformed_kind_codes(code: str) -> None:
    only(plan(edit(snapshot(), lambda d: kind_row(d, "mass").update(code=code))), "RF-4")


@pytest.mark.parametrize("code", ["kgm", "K", "KGMM", "K-M", "KG ", "", "KGÑ"])
def test_step_5_rejects_malformed_unece_codes(code: str) -> None:
    only(plan(edit(snapshot(), lambda d: unit_row(d, "kg").update(unece_code=code))), "RF-4")


@pytest.mark.parametrize("symbol", ["", " ", " kg", "kg ", "\tkg"])
def test_step_5_rejects_empty_or_untrimmed_symbols(symbol: str) -> None:
    only(plan(edit(snapshot(), lambda d: unit_row(d, "kg").update(symbol=symbol))), "RF-4")


def test_step_5_rejects_the_same_ucum_code_in_two_units() -> None:
    """CL-13."""
    only(plan(edit(snapshot(), lambda d: unit_row(d, "g").update(ucum_code="kg"))), "RF-3")


def test_step_5_rejects_the_same_unece_code_in_two_units() -> None:
    only(plan(edit(snapshot(), lambda d: unit_row(d, "g").update(unece_code="KGM"))), "RF-3")


def test_step_5_rejects_the_same_kind_code_even_when_one_is_inactive() -> None:
    def change(d: dict[str, Any]) -> None:
        kind_row(d, "length").update(code="mass", status="inactive")

    only(plan(edit(snapshot(), change)), "RF-3")


def test_step_5_counts_inactive_units_for_uniqueness() -> None:
    def change(d: dict[str, Any]) -> None:
        unit_row(d, "g").update(ucum_code="kg", status="inactive")

    only(plan(edit(snapshot(), change)), "RF-3")


@pytest.mark.parametrize("field", ["ucum_code", "unece_code"])
def test_step_5_rejects_changing_or_removing_a_published_unit_code(field: str) -> None:
    first = snapshot()
    changed = edit(first, lambda d: unit_row(d, "kg").update({field: "ZZ"}))
    only(plan(changed, published(first)), "RF-5")
    removed = edit(first, lambda d: unit_row(d, "kg").update({field: None}))
    only(plan(removed, published(first)), "RF-5")


def test_step_5_rejects_changing_a_published_kind_code() -> None:
    first = snapshot()
    changed = edit(first, lambda d: kind_row(d, "mass").update(code="mass2"))
    only(plan(changed, published(first)), "RF-5")


def test_step_5_rejects_assigning_a_published_code_to_another_identity() -> None:
    first = snapshot()

    def change(d: dict[str, Any]) -> None:
        unit_row(d, "ha").update(unece_code="HAR")  # completar: permitido
        unit_row(d, "oz").update(ucum_code="[oz_av]x")  # cambio: RF-5
        d["units"].append(
            {**unit("ppm"), "unit_id": OTHER, "ucum_code": "[oz_av]", "unece_code": None}
        )

    result = plan(edit(first, change), published(first))
    only(result, "RF-5")
    assert any("[oz_av]" in message for message in messages(result))


def test_step_5_rejects_a_published_kind_code_on_another_kind() -> None:
    first = snapshot()

    def change(d: dict[str, Any]) -> None:
        kind_row(d, "length").update(code="mass_x")
        d["quantity_kinds"].append(
            {**kind_row(d, "count"), "quantity_kind_id": OTHER, "code": "length"}
        )

    only(plan(edit(first, change), published(first)), "RF-5")


def test_step_5_allows_completing_a_null_unece_code_once() -> None:
    first = snapshot()  # «ha» no tiene UNECE
    assert unit_row(first, "ha")["unece_code"] is None
    second = edit(first, lambda d: unit_row(d, "ha").update(unece_code="HAR"))
    result = plan(second, published(first))
    assert result.ok, messages(result)
    assert [u.unit_id for u in result.updated_units] == [unit_id("ha")]
    assert result.updated_units[0].unece_code == "HAR"
    # una vez completado, no se cambia
    third = edit(second, lambda d: unit_row(d, "ha").update(unece_code="HA2"))
    only(plan(third, published(second)), "RF-5")


def test_step_5_allows_completing_a_null_ucum_code_once() -> None:
    first = edit(snapshot(), lambda d: unit_row(d, "lb").update(ucum_code=None))
    second = edit(first, lambda d: unit_row(d, "lb").update(ucum_code="[lb_av]"))
    result = plan(second, published(first))
    assert result.ok, messages(result)
    assert result.updated_units[0].ucum_code == "[lb_av]"


def test_step_5_allows_many_units_without_any_code() -> None:
    def change(d: dict[str, Any]) -> None:
        for key in ("lb", "oz"):
            unit_row(d, key).update(ucum_code=None, unece_code=None)

    assert plan(edit(snapshot(), change)).ok


# --- paso 6: magnitudes ---------------------------------------------------------------------------


def test_step_6_rejects_changing_the_conversion_type_of_a_published_kind() -> None:
    first = snapshot()
    changed = edit(
        first, lambda d: kind_row(d, "temperature_difference").update(conversion_type="affine")
    )
    only(plan(changed, published(first)), "RF-5")


def test_step_6_rejects_changing_the_reference_unit_of_a_published_kind() -> None:
    first = snapshot()
    changed = edit(first, lambda d: kind_row(d, "mass").update(reference_unit_id=unit_id("g")))
    result = plan(changed, published(first))
    assert "RF-5" in rules(result) and not result.ok


def test_step_6_rejects_an_invalid_conversion_type_or_status() -> None:
    only(
        plan(edit(snapshot(), lambda d: kind_row(d, "mass").update(conversion_type="exotic"))),
        "RF-12",
    )
    only(plan(edit(snapshot(), lambda d: kind_row(d, "mass").update(status="retired"))), "RF-7")
    only(plan(edit(snapshot(), lambda d: unit_row(d, "kg").update(status="retired"))), "RF-7")


def test_step_6_requires_the_reference_to_be_an_association_of_the_kind() -> None:
    only(
        plan(
            edit(snapshot(), lambda d: kind_row(d, "mass").update(reference_unit_id=unit_id("L")))
        ),
        "RF-8",
    )
    only(
        plan(edit(snapshot(), lambda d: kind_row(d, "mass").update(reference_unit_id=OTHER))),
        "RF-8",
    )


def test_step_6_requires_the_reference_association_to_have_factor_1_and_offset_0() -> None:
    only(
        plan(edit(snapshot(), lambda d: association_row(d, "mass", "kg").update(factor="2"))),
        "RF-8",
    )
    only(
        plan(edit(snapshot(), lambda d: association_row(d, "temperature", "K").update(offset="5"))),
        "RF-8",
    )
    only(
        plan(edit(snapshot(), lambda d: association_row(d, "mass", "kg").update(factor="1.0"))),
        "RF-8",
    )


def test_step_6_requires_an_active_kind_to_have_an_active_reference() -> None:
    inactive_association = edit(
        snapshot(), lambda d: association_row(d, "mass", "kg").update(status="inactive")
    )
    only(plan(inactive_association), "RF-8")
    inactive_unit = edit(snapshot(), lambda d: unit_row(d, "kg").update(status="inactive"))
    only(plan(inactive_unit), "RF-8")


def test_step_6_allows_an_inactive_kind_with_an_inactive_reference() -> None:
    def change(d: dict[str, Any]) -> None:
        kind_row(d, "mass").update(status="inactive")
        unit_row(d, "kg").update(status="inactive")
        association_row(d, "mass", "kg").update(status="inactive")

    result = plan(edit(snapshot(), change))
    assert result.ok, messages(result)


# --- paso 7: asociaciones -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factor", ["1.0", "01", "+1", "2/4", "1/2", "1/1", "0", "-1", "1e3", "0.0", "", "1/0", "5/9 "]
)
def test_step_7_rejects_non_canonical_factors(factor: str) -> None:
    only(
        plan(edit(snapshot(), lambda d: association_row(d, "mass", "g").update(factor=factor))),
        "RF-13",
    )


@pytest.mark.parametrize("offset", ["-0", "0.0", "+1", "1e2", "1/3", "5/9", "", "1.50", "00"])
def test_step_7_rejects_non_canonical_offsets(offset: str) -> None:
    only(
        plan(
            edit(
                snapshot(), lambda d: association_row(d, "temperature", "Cel").update(offset=offset)
            )
        ),
        "RF-13",
    )


@pytest.mark.parametrize("factor", ["0.45359237", "5/9", "5/18", "1/3", "1000", "0.000001"])
def test_step_7_accepts_canonical_factors(factor: str) -> None:
    # sin UCUM no hay verificación cruzada
    def change(d: dict[str, Any]) -> None:
        unit_row(d, "g").update(ucum_code=None)
        association_row(d, "mass", "g").update(factor=factor)

    assert plan(edit(snapshot(), change)).ok


def test_step_7_rejects_an_offset_in_a_linear_kind() -> None:
    only(
        plan(edit(snapshot(), lambda d: association_row(d, "mass", "g").update(offset="5"))),
        "RF-12",
    )
    only(
        plan(
            edit(
                snapshot(),
                lambda d: association_row(d, "temperature_difference", "Cel").update(
                    offset="273.15"
                ),
            )
        ),
        "RF-12",
    )


def test_step_7_accepts_offsets_in_an_affine_kind() -> None:
    assert plan(snapshot()).ok
    assert association_row(snapshot(), "temperature", "Cel")["offset"] == "273.15"


def test_step_7_rejects_associations_to_missing_units_or_kinds() -> None:
    only(
        plan(edit(snapshot(), lambda d: association_row(d, "mass", "g").update(unit_id=OTHER))),
        "RF-10",
    )
    only(
        plan(
            edit(
                snapshot(), lambda d: association_row(d, "mass", "g").update(quantity_kind_id=OTHER)
            )
        ),
        "RF-10",
    )


def test_step_7_rejects_an_invalid_association_status() -> None:
    only(
        plan(edit(snapshot(), lambda d: association_row(d, "mass", "g").update(status="x"))), "RF-7"
    )


# --- paso 8: UCUM y verificación cruzada ----------------------------------------------------------


@pytest.mark.parametrize(
    "code", ["kg//m", "KG", "[foo]", "k[lb_av]", "Cel/s", "kCel", "Cel2", "k g", "m/", "{x"]
)
def test_step_8_rejects_every_invalid_ucum_form_of_cl_12(code: str) -> None:
    result = plan(edit(snapshot(), lambda d: unit_row(d, "kg").update(ucum_code=code)))
    only(result, "RF-15")
    assert any(code in message for message in messages(result))


def test_step_8_rejects_a_declared_factor_that_differs_from_ucum() -> None:
    result = plan(
        edit(snapshot(), lambda d: association_row(d, "mass", "lb").update(factor="0.4536"))
    )
    only(result, "RF-16")
    assert any("0.4536" in message and "0.45359237" in message for message in messages(result))


def test_step_8_rejects_a_decimal_approximation_of_a_rational_factor() -> None:
    result = plan(
        edit(
            snapshot(),
            lambda d: association_row(d, "temperature_difference", "degF").update(
                factor="0.5555555555555556"
            ),
        )
    )
    only(result, "RF-16")


def test_step_8_rejects_different_dimensions() -> None:
    def change(d: dict[str, Any]) -> None:
        unit_row(d, "gal").update(ucum_code="[yd_i]")

    result = plan(edit(snapshot(), change))
    only(result, "RF-16")
    assert any("dimensión" in message for message in messages(result))


def test_step_8_rejects_a_declared_offset_that_differs_from_ucum() -> None:
    only(
        plan(
            edit(
                snapshot(),
                lambda d: association_row(d, "temperature", "Cel").update(offset="273.16"),
            )
        ),
        "RF-16",
    )
    only(
        plan(
            edit(
                snapshot(),
                lambda d: association_row(d, "temperature", "degF").update(offset="459.6"),
            )
        ),
        "RF-16",
    )


def test_step_8_skips_the_cross_check_when_a_unit_has_no_ucum_code() -> None:
    def change(d: dict[str, Any]) -> None:
        unit_row(d, "lb").update(ucum_code=None)
        association_row(d, "mass", "lb").update(factor="0.4536")

    assert plan(edit(snapshot(), change)).ok


def test_step_8_skips_the_cross_check_when_the_reference_has_no_ucum_code() -> None:
    def change(d: dict[str, Any]) -> None:
        unit_row(d, "kg").update(ucum_code=None)
        association_row(d, "mass", "g").update(factor="0.002")

    assert plan(edit(snapshot(), change)).ok


def test_step_8_derives_the_affine_offset_from_a_reference_other_than_kelvin() -> None:
    """D9: con °C de referencia, K = (x − 273.15) y °F = (x − 32) × 5/9."""

    def change(d: dict[str, Any]) -> None:
        kind_row(d, "temperature").update(reference_unit_id=unit_id("Cel"))
        rows = [
            r for r in d["quantity_kind_units"] if r["quantity_kind_id"] == kind_id("temperature")
        ]
        rows[0].update(unit_id=unit_id("Cel"), factor="1", offset="0")
        rows[1].update(unit_id=unit_id("K"), factor="1", offset="-273.15")
        rows[2].update(unit_id=unit_id("degF"), factor="5/9", offset="-32")

    result = plan(edit(snapshot(), change))
    assert result.ok, messages(result)


def test_step_8_uses_special_units_by_scale_only_in_linear_kinds() -> None:
    assert plan(snapshot()).ok  # temperature_difference: °C factor 1, °F 5/9, offset 0


# --- paso 9: localizaciones -----------------------------------------------------------------------


def test_step_9_requires_en_and_es_for_every_kind_and_unit() -> None:
    def drop_kind_es(d: dict[str, Any]) -> None:
        d["quantity_kind_names"] = [
            r
            for r in d["quantity_kind_names"]
            if not (r["quantity_kind_id"] == kind_id("mass") and r["locale_id"] == ES)
        ]

    def drop_unit_en(d: dict[str, Any]) -> None:
        d["unit_names"] = [
            r
            for r in d["unit_names"]
            if not (r["unit_id"] == unit_id("kg") and r["locale_id"] == EN)
        ]

    only(plan(edit(snapshot(), drop_kind_es)), "RF-19")
    only(plan(edit(snapshot(), drop_unit_en)), "RF-19")


def test_step_9_rejects_localizations_of_unknown_entities_or_locales() -> None:
    only(
        plan(
            edit(
                snapshot(),
                lambda d: d["unit_names"].append(
                    {"unit_id": OTHER, "locale_id": EN, "name": "x", "plural": None}
                ),
            )
        ),
        "RF-18",
    )
    only(
        plan(
            edit(
                snapshot(),
                lambda d: d["quantity_kind_names"].append(
                    {"quantity_kind_id": OTHER, "locale_id": EN, "name": "x"}
                ),
            )
        ),
        "RF-18",
    )
    only(
        plan(
            edit(
                snapshot(),
                lambda d: d["unit_names"].append(
                    {"unit_id": unit_id("kg"), "locale_id": OTHER, "name": "x", "plural": None}
                ),
            )
        ),
        "RF-18",
    )


@pytest.mark.parametrize("name", ["", " ", " kilogram", "kilogram "])
def test_step_9_rejects_empty_or_untrimmed_names_and_plurals(name: str) -> None:
    only(plan(edit(snapshot(), lambda d: d["unit_names"][0].update(name=name))), "RF-18")
    only(plan(edit(snapshot(), lambda d: d["unit_names"][0].update(plural=name))), "RF-18")
    only(plan(edit(snapshot(), lambda d: d["quantity_kind_names"][0].update(name=name))), "RF-18")


def test_step_9_plural_may_be_absent() -> None:
    assert plan(edit(snapshot(), lambda d: d["unit_names"][0].update(plural=None))).ok


def test_step_9_rejects_a_new_localization_in_an_inactive_locale() -> None:
    document = edit(
        snapshot(),
        lambda d: d["unit_names"].append(
            {"unit_id": unit_id("kg"), "locale_id": FR, "name": "kilogramme", "plural": None}
        ),
    )
    locales = locale_view(LocaleInfo(FR, "fr", "inactive"))
    only(plan(document, locales=locales), "RF-19")
    assert plan(document, locales=locale_view(LocaleInfo(FR, "fr", "active"))).ok


def test_step_9_keeps_published_localizations_of_a_locale_that_became_inactive() -> None:
    first = edit(
        snapshot(),
        lambda d: d["unit_names"].append(
            {"unit_id": unit_id("kg"), "locale_id": FR, "name": "kilogramme", "plural": None}
        ),
    )
    locales = locale_view(LocaleInfo(FR, "fr", "inactive"))
    result = plan(first, published(first), locales=locales)
    assert result.ok, messages(result)
    assert result.is_empty


# --- paso 10: procedencia -------------------------------------------------------------------------


def with_provenance(value: Any) -> dict[str, Any]:
    document = snapshot()
    document["provenance"] = value
    return document


def sources(*, drop: str | None = None, **changes: Any) -> dict[str, Any]:
    value = copy.deepcopy(provenance())
    value["sources"] = [s for s in value["sources"] if s["role"] != drop]
    value.update(changes)
    return value


@pytest.mark.parametrize("role", ["definitions", "ucum", "names", "unece"])
def test_step_10_requires_each_source_role(role: str) -> None:
    result = plan(with_provenance(sources(drop=role)))
    only(result, "RF-41")
    assert any(role in message for message in messages(result))


def test_step_10_does_not_require_unece_when_no_unit_has_an_unece_code() -> None:
    def change(d: dict[str, Any]) -> None:
        for row in d["units"]:
            row["unece_code"] = None
        d["provenance"] = sources(drop="unece")

    assert plan(edit(snapshot(), change)).ok


@pytest.mark.parametrize(
    "field", ["name", "edition", "retrieved_at", "location", "checksum", "license"]
)
def test_step_10_requires_every_source_field(field: str) -> None:
    value = sources()
    value["sources"][1][field] = ""
    only(plan(with_provenance(value)), "RF-41")
    value = sources()
    del value["sources"][1][field]
    only(plan(with_provenance(value)), "RF-41")


def test_step_10_rejects_unresolved_conflicts() -> None:
    only(plan(with_provenance(sources(unresolved_conflicts=["x vs y"]))), "RF-41")


def test_step_10_rejects_a_missing_or_malformed_provenance() -> None:
    only(plan(with_provenance(None)), "RF-41")
    only(plan(with_provenance("x")), "RF-41")
    only(plan(with_provenance({"sources": "x", "unresolved_conflicts": []})), "RF-41")
    only(plan(with_provenance({"sources": [], "unresolved_conflicts": None})), "RF-41")


# --- orden de los pasos ---------------------------------------------------------------------------


def test_only_the_violations_of_the_first_failing_step_are_reported() -> None:
    def change(d: dict[str, Any]) -> None:
        kind_row(d, "mass").update(code="Mass")  # paso 5
        association_row(d, "mass", "g").update(factor="1.0")  # paso 7
        unit_row(d, "kg").update(ucum_code="KG")  # paso 8
        d["provenance"] = None  # paso 10

    result = plan(edit(snapshot(), change))
    only(result, "RF-4")
    result = plan(edit(edit(snapshot(), change), lambda d: kind_row(d, "Mass").update(code="mass")))
    only(result, "RF-13")


def test_unit_names_builder_matches_the_fixture_shape() -> None:
    assert [r["locale_id"] for r in unit_names("kg")] == [EN, ES]
    assert build_snapshot(codes=("mass",))["quantity_kinds"][0]["code"] == "mass"
