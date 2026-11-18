"""T7: consultas de Units (RF-20, RF-32 a RF-37, CL-14, CL-15, CA-5, CA-7)."""

from typing import Any

import pytest

from gi_common_reference.units.application.queries import (
    LookupStatus,
    get_catalog_version,
    get_quantity_kind,
    get_unit,
    list_quantity_kinds,
    list_units,
)
from gi_common_reference.units.domain.ports import ReaderUnavailable
from tests.fixtures.units import EN, ES, build_snapshot, kind_id, unit_id
from tests.fixtures.units_reader import FR, InMemoryUnitsReader
from tests.fixtures.units_variants import retired_oz, sack_snapshot

MISSING = "00000000-0000-4000-8000-000000000000"


def reader(version: int = 1, retired: bool = False) -> InMemoryUnitsReader:
    return InMemoryUnitsReader(retired_oz(version) if retired else build_snapshot(version))


def symbols(listing: Any) -> list[str]:
    return [view.record.symbol for view in listing.items]


# --- magnitudes


def test_the_default_list_has_only_active_kinds_ordered_by_code() -> None:
    listing = list_quantity_kinds(reader())
    codes = [v.record.code for v in listing.items]
    assert listing.status is LookupStatus.FOUND and listing.snapshot_version == 1
    assert codes == sorted(codes) and len(codes) == 14
    assert all(v.name is None for v in listing.items)  # sin locale no hay nombre


def test_inactive_kinds_are_listed_only_on_request() -> None:
    document = build_snapshot(2)
    document["quantity_kinds"][0]["status"] = "inactive"
    r = InMemoryUnitsReader(document)
    assert len(list_quantity_kinds(r).items) == 13
    assert len(list_quantity_kinds(r, include_inactive=True).items) == 14


def test_the_code_filter_is_exact() -> None:
    r = reader()
    assert [v.record.code for v in list_quantity_kinds(r, code="mass").items] == ["mass"]
    assert list_quantity_kinds(r, code="Mass").items == ()
    assert list_quantity_kinds(r, code="mas").items == ()


def test_names_in_en_es_and_none_without_fallback() -> None:
    r = reader()
    en = list_quantity_kinds(r, code="mass", locale_id=EN).items[0].name
    es = list_quantity_kinds(r, code="mass", locale_id=ES).items[0].name
    fr = list_quantity_kinds(r, code="mass", locale_id=FR).items[0].name
    assert (en, es, fr) == ("Mass", "Masa", None)


def test_the_kind_by_id_carries_reference_type_status_and_name() -> None:
    result = get_quantity_kind(reader(), kind_id("temperature"), ES)
    assert result.status is LookupStatus.FOUND and result.item is not None
    record = result.item.record
    assert (record.code, record.conversion_type, record.status) == (
        "temperature",
        "affine",
        "active",
    )
    assert record.reference_unit_id == unit_id("K") and result.item.name == "Temperatura"


def test_the_kind_by_id_resolves_uppercase_and_inactive_kinds() -> None:
    document = build_snapshot(2)
    document["quantity_kinds"][0]["status"] = "inactive"
    r = InMemoryUnitsReader(document)
    first = document["quantity_kinds"][0]["quantity_kind_id"]
    result = get_quantity_kind(r, first.upper())
    assert result.status is LookupStatus.FOUND and result.item.record.status == "inactive"  # type: ignore[union-attr]


def test_a_kind_id_error_is_a_validation_error_and_a_missing_one_is_not_found() -> None:
    r = reader()
    for bad in ("", "nope", kind_id("mass") + "0", " " + kind_id("mass")):
        result = get_quantity_kind(r, bad)
        assert (result.status, result.error) == (LookupStatus.INVALID, "invalid_quantity_kind_id")
    missing = get_quantity_kind(r, MISSING)
    assert (missing.status, missing.error) == (LookupStatus.NOT_FOUND, "quantity_kind_not_found")


# --- unidades


def test_the_default_unit_list_is_active_and_ordered_by_symbol_then_id() -> None:
    document = build_snapshot(2)
    for row in document["units"]:
        if row["unit_id"] == unit_id("oz"):
            row["status"] = "inactive"
    r = InMemoryUnitsReader(document)
    listing = list_units(r)
    ordered = [(v.record.symbol.encode(), v.record.unit_id) for v in listing.items]
    assert ordered == sorted(ordered) and len(listing.items) == 49
    assert len(list_units(r, include_inactive=True).items) == 50


def test_the_kind_filter_keeps_only_units_with_an_active_association_to_it() -> None:
    r = reader(2, retired=True)
    default = list_units(r, quantity_kind_id=kind_id("mass"))
    assert default.status is LookupStatus.FOUND
    assert set(symbols(default)) == {"kg", "g", "mg", "t", "lb"}
    everything = list_units(r, quantity_kind_id=kind_id("mass"), include_inactive=True)
    assert set(symbols(everything)) == {"kg", "g", "mg", "t", "lb", "oz"}
    shared = list_units(r, quantity_kind_id=kind_id("temperature_difference"))
    assert set(symbols(shared)) == {"K", "°C", "°F"}


def test_an_active_unit_with_an_inactive_association_is_not_listed_for_that_kind() -> None:
    document = sack_snapshot(2, inactive_links=(("temperature_difference", "degF"),))
    r = InMemoryUnitsReader(document)
    kind = kind_id("temperature_difference")
    assert set(symbols(list_units(r, quantity_kind_id=kind))) == {"K", "°C"}
    assert set(symbols(list_units(r, quantity_kind_id=kind, include_inactive=True))) == {
        "K",
        "°C",
        "°F",
    }
    assert "°F" in symbols(list_units(r, quantity_kind_id=kind_id("temperature")))


def test_a_nonexistent_kind_in_the_filter_is_not_found_and_a_malformed_one_is_invalid() -> None:
    r = reader()
    missing = list_units(r, quantity_kind_id=MISSING)
    assert (missing.status, missing.error) == (LookupStatus.NOT_FOUND, "quantity_kind_not_found")
    bad = list_units(r, quantity_kind_id="mass")
    assert (bad.status, bad.error) == (LookupStatus.INVALID, "invalid_quantity_kind_id")


def test_the_code_filters_are_exact_and_case_sensitive() -> None:
    r = reader()
    assert symbols(list_units(r, ucum_code="[lb_av]")) == ["lb"]
    assert list_units(r, ucum_code="[LB_AV]").items == ()
    assert list_units(r, ucum_code="Kg").items == ()
    assert symbols(list_units(r, unece_code="KGM")) == ["kg"]
    assert list_units(r, unece_code="kgm").items == ()
    assert list_units(r, ucum_code="kg", unece_code="GRM").items == ()  # se combinan con AND


def test_units_without_codes_are_listed_and_resolved_with_null_codes() -> None:
    result = list_units(reader(), unece_code=None)
    ha = next(v for v in result.items if v.record.symbol == "ha")
    assert ha.record.unece_code is None and ha.record.ucum_code == "har"


def test_unit_names_and_plurals_come_only_from_the_requested_locale() -> None:
    r = reader()
    lb = unit_id("lb")
    es = get_unit(r, lb, ES).item
    en = get_unit(r, lb, EN).item
    fr = get_unit(r, lb, FR).item
    none = get_unit(r, lb).item
    assert (es.name, es.plural) == ("libra", "libras")  # type: ignore[union-attr]
    assert (en.name, en.plural) == ("pound", "pounds")  # type: ignore[union-attr]
    assert (fr.name, fr.plural) == (None, None)  # type: ignore[union-attr]
    assert (none.name, none.plural) == (None, None)  # type: ignore[union-attr]
    assert es.record.symbol == fr.record.symbol == "lb"  # type: ignore[union-attr]


def test_the_unit_by_id_lists_its_associations_with_the_reference_flag() -> None:
    result = get_unit(reader(), unit_id("K"))
    assert result.status is LookupStatus.FOUND and result.item is not None
    by_kind = {a.quantity_kind_id: a for a in result.item.quantity_kinds}
    assert set(by_kind) == {kind_id("temperature"), kind_id("temperature_difference")}
    assert all(a.reference and a.status == "active" for a in by_kind.values())
    cel = get_unit(reader(), unit_id("Cel")).item
    assert cel is not None and not any(a.reference for a in cel.quantity_kinds)


def test_a_retired_unit_still_resolves_with_inactive_association() -> None:
    result = get_unit(reader(2, retired=True), unit_id("oz"))
    assert result.item is not None and result.item.record.status == "inactive"
    assert [(a.status, a.reference) for a in result.item.quantity_kinds] == [("inactive", False)]


def test_the_unit_id_errors() -> None:
    r = reader()
    for bad in ("", "kg", unit_id("kg") + "0"):
        result = get_unit(r, bad)
        assert (result.status, result.error) == (LookupStatus.INVALID, "invalid_unit_id")
    missing = get_unit(r, MISSING)
    assert (missing.status, missing.error) == (LookupStatus.NOT_FOUND, "unit_not_found")
    assert missing.snapshot_version == 1


# --- localización inválida


@pytest.mark.parametrize(
    ("locale", "error"),
    [("es", "invalid_locale_id"), ("", "invalid_locale_id"), (MISSING, "unknown_locale")],
)
def test_an_invalid_or_unknown_locale_is_a_validation_error_everywhere(
    locale: str, error: str
) -> None:
    r = reader()
    results: list[Any] = [
        list_quantity_kinds(r, locale_id=locale),
        get_quantity_kind(r, kind_id("mass"), locale),
        list_units(r, locale_id=locale),
        get_unit(r, unit_id("kg"), locale),
    ]
    for result in results:
        assert (result.status, result.error) == (LookupStatus.INVALID, error)


def test_an_uppercase_locale_id_is_accepted() -> None:
    assert get_unit(reader(), unit_id("kg"), EN.upper()).item.name == "kilogram"  # type: ignore[union-attr]


# --- versión, catálogo vacío y fallas técnicas


def test_the_catalog_version_and_an_empty_catalog() -> None:
    assert get_catalog_version(reader(7)) == 7
    empty = InMemoryUnitsReader()
    assert get_catalog_version(empty) is None
    assert list_quantity_kinds(empty).items == () and list_units(empty).items == ()
    assert get_unit(empty, unit_id("kg")).status is LookupStatus.NOT_FOUND
    assert get_quantity_kind(empty, MISSING).snapshot_version is None


def test_every_query_uses_one_session() -> None:
    r = reader()
    list_units(r, quantity_kind_id=kind_id("mass"), locale_id=EN)
    get_unit(r, unit_id("kg"), ES)
    list_quantity_kinds(r, locale_id=EN)
    get_quantity_kind(r, kind_id("mass"))
    get_catalog_version(r)
    assert r.sessions == 5


def test_a_technical_failure_is_not_swallowed_as_not_found_or_invalid() -> None:
    r = reader()
    r.unavailable = True
    for call in (
        lambda: list_quantity_kinds(r),
        lambda: get_quantity_kind(r, kind_id("mass")),
        lambda: list_units(r),
        lambda: get_unit(r, unit_id("kg")),
        lambda: get_catalog_version(r),
    ):
        with pytest.raises(ReaderUnavailable):
            call()
