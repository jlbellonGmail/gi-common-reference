"""T5: diff legible y de solo lectura contra la versión aplicada (RF-45, CL-11)."""

from typing import Any

from tests.fixtures.units import EN, ES, kind_id, unit, unit_id
from tests.unit.units.helpers import (
    association_row,
    edit,
    kind_row,
    messages,
    plan,
    published,
    snapshot,
    unit_row,
)

from gi_common_reference.units.domain.catalog import CatalogPlan
from gi_common_reference.units.domain.diff import diff_catalog
from gi_common_reference.units.domain.model import CatalogState


def lines(first: dict[str, Any], second: dict[str, Any]) -> list[str]:
    current: CatalogState = published(first)
    result: CatalogPlan = plan(second, current)
    assert result.ok, messages(result)
    return diff_catalog(result, current).lines()


def base() -> dict[str, Any]:
    """Versión 1 sin código UCUM en la libra: su factor puede corregirse (CL-11)."""
    return edit(snapshot(), lambda d: unit_row(d, "lb").update(ucum_code=None))


def test_an_unchanged_snapshot_has_an_empty_diff() -> None:
    document = snapshot()
    assert lines(document, document) == []


def test_the_diff_of_the_first_snapshot_lists_every_addition() -> None:
    result = plan(snapshot())
    entries = diff_catalog(result, CatalogState()).entries
    assert sum(1 for e in entries if e.category == "alta" and e.subject.startswith("unidad")) == 50
    assert (
        sum(1 for e in entries if e.category == "alta" and e.subject.startswith("magnitud")) == 14
    )
    assert sum(1 for e in entries if e.category == "asociación") == 54
    assert sum(1 for e in entries if e.category == "nombre") == 128


def test_the_diff_shows_the_old_and_the_new_factor() -> None:
    first = base()
    second = edit(first, lambda d: association_row(d, "mass", "lb").update(factor="0.4536"))
    [line] = lines(first, second)
    assert "factor 0.45359237 → 0.4536" in line
    assert "mass" in line and "lb" in line and line.startswith("factor")


def test_the_diff_shows_the_old_and_the_new_offset() -> None:
    first = snapshot()

    def change(d: dict[str, Any]) -> None:
        # una magnitud afín sin UCUM en la unidad para poder cambiar el desplazamiento
        unit_row(d, "Cel").update(ucum_code=None)

    first = edit(first, change)
    second = edit(first, lambda d: association_row(d, "temperature", "Cel").update(offset="273.16"))
    [line] = lines(first, second)
    assert "desplazamiento 273.15 → 273.16" in line


def test_the_diff_shows_a_rational_factor_change() -> None:
    first = edit(base(), lambda d: unit_row(d, "degF").update(ucum_code=None))
    second = edit(
        first, lambda d: association_row(d, "temperature_difference", "degF").update(factor="5/18")
    )
    [line] = lines(first, second)
    assert "factor 5/9 → 5/18" in line


def test_the_diff_shows_status_changes_of_units_kinds_and_associations() -> None:
    first = snapshot()
    second = edit(first, lambda d: unit_row(d, "g").update(status="inactive"))
    second = edit(second, lambda d: association_row(d, "mass", "mg").update(status="inactive"))
    second = edit(second, lambda d: kind_row(d, "count").update(status="inactive"))
    second = edit(second, lambda d: unit_row(d, "each").update(status="inactive"))
    second = edit(second, lambda d: association_row(d, "count", "each").update(status="inactive"))
    out = lines(first, second)
    assert any(
        "status active → inactive" in ln and "g" in ln and ln.startswith("estado") for ln in out
    )
    assert len([ln for ln in out if ln.startswith("estado")]) == 5


def test_the_diff_shows_symbol_changes() -> None:
    first = snapshot()
    second = edit(first, lambda d: unit_row(d, "kg").update(symbol="KG"))
    [line] = lines(first, second)
    assert line.startswith("símbolo") and "kg → KG" in line


def test_the_diff_shows_completed_codes() -> None:
    first = snapshot()
    second = edit(first, lambda d: unit_row(d, "ha").update(unece_code="HAR"))
    [line] = lines(first, second)
    assert line.startswith("código") and "unece_code — → HAR" in line


def test_the_diff_shows_name_and_plural_changes() -> None:
    first = snapshot()

    def change(d: dict[str, Any]) -> None:
        row = next(
            r for r in d["unit_names"] if r["unit_id"] == unit_id("kg") and r["locale_id"] == EN
        )
        row.update(name="kilo", plural="kilos")
        kind = next(
            r
            for r in d["quantity_kind_names"]
            if r["quantity_kind_id"] == kind_id("mass") and r["locale_id"] == ES
        )
        kind.update(name="Masa total")

    out = lines(first, edit(first, change))
    assert len(out) == 2 and all(ln.startswith("nombre") for ln in out)
    assert any("kilogram → kilo" in ln and "kilograms → kilos" in ln for ln in out)
    assert any("Masa → Masa total" in ln for ln in out)


def test_the_diff_shows_new_entities() -> None:
    first = snapshot()
    new_unit = "6b0b1f0e-0a52-4f8e-9f55-7f1c8d6d9a11"

    def change(d: dict[str, Any]) -> None:
        d["units"].append(
            {
                **unit("kg"),
                "unit_id": new_unit,
                "ucum_code": "[stone_av]",
                "unece_code": None,
                "symbol": "st",
            }
        )
        d["quantity_kind_units"].append(
            {
                "quantity_kind_id": kind_id("mass"),
                "unit_id": new_unit,
                "factor": "6.35029318",
                "offset": "0",
                "status": "active",
            }
        )
        d["unit_names"] += [
            {"unit_id": new_unit, "locale_id": EN, "name": "stone", "plural": "stones"},
            {"unit_id": new_unit, "locale_id": ES, "name": "stone", "plural": None},
        ]

    out = lines(first, edit(first, change))
    assert any(ln.startswith("alta") and "st" in ln and "[stone_av]" in ln for ln in out)
    assert any(
        ln.startswith("asociación") and "mass" in ln and "factor 6.35029318" in ln for ln in out
    )
    assert sum(1 for ln in out if ln.startswith("nombre")) == 2


def test_the_diff_does_not_modify_the_plan_or_the_state() -> None:
    first = snapshot()
    second = edit(first, lambda d: unit_row(d, "g").update(status="inactive"))
    current = published(first)
    result = plan(second, current)
    before = (result, current)
    diff_catalog(result, current)
    assert (result, current) == before
