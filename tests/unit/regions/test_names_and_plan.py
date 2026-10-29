"""T6: localizaciones y plan de cambios (paso 7; RF-9–RF-13, RF-24, RF-28, RF-32–RF-34, RF-39)."""

import uuid

import pytest

from gi_common_reference.regions.domain.model import CatalogState, NameRecord
from tests.fixtures.regions import (
    EN,
    ES,
    FR,
    build_snapshot,
    locale_catalog,
    recoding,
    region,
    region_id,
    seal,
    subregion,
    subregion_id,
)
from tests.unit.regions.helpers import messages, plan, published, rules


@pytest.fixture
def current() -> CatalogState:
    return published(build_snapshot(1))


def test_a_name_of_an_entity_that_is_not_in_the_snapshot_is_rejected() -> None:
    document = build_snapshot()
    document["region_names"].append(
        {"region_id": region_id("142"), "locale_id": EN, "name": "Asia"}
    )
    document["subregion_names"].append(
        {"subregion_id": region_id("019"), "locale_id": EN, "name": "Americas"}
    )
    result = plan(seal(document))
    assert rules(result) == {"RF-10"}
    assert messages(result).count("RF-10") == 2


def test_a_name_with_an_unknown_locale_is_rejected() -> None:
    document = build_snapshot()
    document["subregion_names"].append(
        {"subregion_id": subregion_id("419"), "locale_id": str(uuid.uuid4()), "name": "x"}
    )
    assert rules(plan(seal(document))) == {"RF-28"}


def test_two_names_for_the_same_entity_and_locale_are_rejected() -> None:
    document = build_snapshot()
    document["region_names"].append(
        {"region_id": region_id("019"), "locale_id": EN, "name": "The Americas"}
    )
    assert rules(plan(seal(document))) == {"RF-9"}


@pytest.mark.parametrize("name", ["", " ", " Americas", "Americas ", "\tAmericas", "Americas "])
def test_empty_or_padded_names_are_rejected(name: str) -> None:
    document = build_snapshot()
    for item in document["region_names"]:
        if item["region_id"] == region_id("019") and item["locale_id"] == EN:
            item["name"] = name
    assert rules(plan(seal(document))) == {"RF-11"}


def test_a_new_name_with_an_inactive_locale_is_rejected() -> None:
    document = build_snapshot()
    document["region_names"].append(
        {"region_id": region_id("019"), "locale_id": FR, "name": "Amériques"}
    )
    result = plan(seal(document), locales=locale_catalog(inactive=["fr"]))
    assert rules(result) == {"RF-33"}


def test_a_published_name_whose_locale_became_inactive_is_kept() -> None:
    first = build_snapshot(1)
    first["region_names"].append(
        {"region_id": region_id("019"), "locale_id": FR, "name": "Amériques"}
    )
    first = seal(first)
    second = build_snapshot(2)
    second["region_names"].append(
        {"region_id": region_id("019"), "locale_id": FR, "name": "Amériques"}
    )
    result = plan(seal(second), published(first), locales=locale_catalog(inactive=["fr"]))
    assert result.ok, messages(result)
    assert not result.new_region_names and not result.updated_region_names


def test_every_entity_needs_a_name_in_every_required_locale() -> None:
    document = build_snapshot()
    document["subregion_names"] = [
        n
        for n in document["subregion_names"]
        if not (n["subregion_id"] == subregion_id("419") and n["locale_id"] == ES)
    ]
    result = plan(seal(document))
    assert rules(result) == {"RF-32"} and subregion_id("419") in messages(result)
    document = build_snapshot()
    document["region_names"] = [n for n in document["region_names"] if n["locale_id"] != EN]
    assert rules(plan(seal(document))) == {"RF-32"}


def test_a_non_required_locale_without_translation_is_allowed() -> None:
    document = build_snapshot()
    document["region_names"].append(
        {"region_id": region_id("019"), "locale_id": FR, "name": "Amériques"}
    )
    result = plan(seal(document))
    assert result.ok, messages(result)


def test_two_regions_may_share_a_name_in_a_locale() -> None:
    document = build_snapshot()
    for item in document["region_names"]:
        if item["locale_id"] == EN:
            item["name"] = "Same"
    result = plan(seal(document))
    assert result.ok, messages(result)


def test_a_rename_is_planned_as_an_update_and_keeps_the_id(current: CatalogState) -> None:
    document = build_snapshot(2)
    for item in document["region_names"]:
        if item["region_id"] == region_id("019") and item["locale_id"] == ES:
            item["name"] = "América"
    result = plan(seal(document), current)
    assert result.ok, messages(result)
    assert result.updated_region_names == (NameRecord(region_id("019"), ES, "América"),)
    assert not result.updated_regions and not result.new_region_names


def test_adding_a_locale_is_planned_as_new_names(current: CatalogState) -> None:
    document = build_snapshot(2)
    document["subregion_names"].append(
        {"subregion_id": subregion_id("419"), "locale_id": FR, "name": "Amérique latine"}
    )
    result = plan(seal(document), current)
    assert result.ok, messages(result)
    assert result.new_subregion_names == (NameRecord(subregion_id("419"), FR, "Amérique latine"),)


def test_resending_the_published_state_plans_nothing(current: CatalogState) -> None:
    result = plan(build_snapshot(2), current)
    assert result.ok, messages(result)
    assert result.is_empty


def test_the_plan_of_a_mixed_snapshot_is_exact(current: CatalogState) -> None:
    """Reclasificación + recodificación + entidad nueva + cambio de status en un mismo snapshot."""
    document = build_snapshot(
        2,
        regions=[region("002"), region("019"), region("142")],
        subregions=[
            subregion("015", "002", status="inactive"),
            subregion("202"),
            subregion("419", "002"),
            subregion("021", code="456"),
            subregion("030"),
        ],
        recodings=[recoding("subregion", "021", "021", "456")],
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    assert [r.region_id for r in result.new_regions] == [region_id("142")]
    assert [s.subregion_id for s in result.new_subregions] == [subregion_id("030")]
    assert {s.subregion_id for s in result.updated_subregions} == {
        subregion_id("015"),
        subregion_id("419"),
        subregion_id("021"),
    }
    assert [r.subregion_id for r in result.reclassifications] == [subregion_id("419")]
    assert [r.entity_id for r in result.recodings] == [subregion_id("021")]
    assert len(result.new_region_names) == 2 and len(result.new_subregion_names) == 2
