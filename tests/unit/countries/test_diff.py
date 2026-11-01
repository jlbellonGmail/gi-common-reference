"""T6: diff legible contra la versión aplicada (RF-30)."""

from typing import Any

from gi_common_reference.countries.domain.diff import diff_catalog
from gi_common_reference.countries.domain.model import CatalogState
from tests.fixtures.countries import (
    build_snapshot,
    country,
    country_id,
    flag,
    flag_exception,
    names,
    recoding,
)
from tests.fixtures.regions import region_id, subregion_id
from tests.unit.countries.helpers import messages, plan, published

BASE = ("AR", "NA", "AQ", "TW", "US", "CA", "PR", "BV")


def changed_snapshot() -> dict[str, Any]:
    """Un snapshot que cambia un país de cada manera posible respecto de `base + TP`."""
    countries = [
        country("AR", region_id=region_id("142"), subregion_id=subregion_id("035")),
        country("NA", status="inactive", replacement_country_ids=[country_id("AR")]),
        country("AQ"),
        country("TW"),
        country("US"),
        country("CA", calling_code="2"),
        country("PR"),
        country("BV"),
        country("TL", identity="TP"),
        country("CW"),
    ]
    country_names = [n for k in (*BASE, "CW") for n in names(k)] + names("TP")
    country_names = [
        {**n, "name": "Estados Unidos (EE. UU.)"}
        if n["country_id"] == country_id("US") and n["name"] == "Estados Unidos"
        else n
        for n in country_names
    ]
    return build_snapshot(
        2,
        countries=countries,
        country_names=country_names,
        flags=[flag(k) for k in ("AR", "NA", "TW", "US", "CA", "PR", "BV", "CW")] + [flag("TP")],
        flag_exceptions=[flag_exception("AQ")],
        recodings=[recoding("TP", ("TP", "TMP", "626"), ("TL", "TLS", "626"))],
    )


def test_the_diff_lists_every_kind_of_change_without_touching_anything() -> None:
    current = published(build_snapshot(1, keys=(*BASE, "TP")))
    result = plan(changed_snapshot(), current)
    assert result.ok, messages(result)
    diff = diff_catalog(result, current)
    assert {entry.category for entry in diff.entries} == {
        "alta",
        "códigos",
        "clasificación",
        "atributos",
        "estado",
        "nombre",
        "bandera",
    }
    lines = "\n".join(diff.lines())
    assert "CW" in lines and "TP" in lines and "TL" in lines and "→" in lines
    assert "Estados Unidos (EE. UU.)" in lines


def test_each_entry_names_the_country_and_its_current_code() -> None:
    current = published(build_snapshot(1, keys=(*BASE, "TP")))
    diff = diff_catalog(plan(changed_snapshot(), current), current)
    by_category = {entry.category: entry for entry in diff.entries}
    assert by_category["códigos"].country_id == country_id("TP")
    assert by_category["códigos"].alpha2 == "TL"
    assert by_category["clasificación"].country_id == country_id("AR")
    assert by_category["atributos"].country_id == country_id("CA")
    assert by_category["estado"].country_id == country_id("NA")


def test_an_identical_snapshot_has_an_empty_diff() -> None:
    current = published(build_snapshot(1))
    diff = diff_catalog(plan(build_snapshot(2), current), current)
    assert diff.entries == () and diff.lines() == []


def test_the_first_snapshot_is_all_additions() -> None:
    diff = diff_catalog(plan(build_snapshot()), CatalogState())
    categories = {entry.category for entry in diff.entries}
    assert categories == {"alta", "nombre", "bandera"}
    assert sum(1 for e in diff.entries if e.category == "alta") == 8


def test_the_diff_lists_the_successors_added_and_removed() -> None:
    before = published(
        build_snapshot(
            1,
            countries=[
                country("AR", status="inactive", replacement_country_ids=[country_id("NA")]),
                country("NA"),
                country("US"),
            ],
            keys=("AR", "NA", "US"),
        )
    )
    document = build_snapshot(
        2,
        countries=[
            country("AR", status="inactive", replacement_country_ids=[country_id("US")]),
            country("NA"),
            country("US"),
        ],
        keys=("AR", "NA", "US"),
    )
    diff = diff_catalog(plan(document, before), before)
    (entry,) = diff.entries
    assert entry.category == "estado" and "agrega" in entry.detail and "quita" in entry.detail
    assert country_id("US") in entry.detail and country_id("NA") in entry.detail
