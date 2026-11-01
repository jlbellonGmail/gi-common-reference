"""T4: admisión e identidad del snapshot (RF-2, RF-22, RF-23, RF-26, RF-31, RF-33)."""

import copy
import uuid

import pytest

from gi_common_reference.regions.domain.model import LocaleCatalog
from gi_common_reference.regions.domain.policy import RequiredLocale, RequiredLocales
from gi_common_reference.regions.domain.snapshot import (
    Classification,
    HistoricalSnapshot,
    evaluate_snapshot,
)
from tests.fixtures.regions import (
    EN,
    ES,
    build_snapshot,
    locale_catalog,
    names_for_regions,
    region,
    region_id,
    seal,
    subregion,
    subregion_id,
)
from tests.unit.regions.helpers import messages, plan, published, rules


def history(*documents: dict[str, object]) -> list[HistoricalSnapshot]:
    return [
        HistoricalSnapshot(int(str(d["snapshot_version"])), str(d["content_digest"]))
        for d in documents
    ]


# --- digest y clasificación (RF-21, RF-26) ------------------------------------------------------


def test_the_first_snapshot_proceeds_with_any_version() -> None:
    decision = evaluate_snapshot(build_snapshot(7), [])
    assert decision.classification is Classification.D and decision.proceeds


def test_the_same_snapshot_again_is_a_noop() -> None:
    v1 = build_snapshot(1)
    decision = evaluate_snapshot(copy.deepcopy(v1), history(v1))
    assert decision.classification is Classification.A and decision.is_noop


def test_an_earlier_snapshot_resent_after_a_later_one_is_a_noop() -> None:
    v1, v2 = build_snapshot(1), build_snapshot(2, regions=[region("002")], subregions=[])
    assert evaluate_snapshot(v1, history(v1, v2)).is_noop


def test_the_same_version_with_other_content_is_rejected() -> None:
    v1 = build_snapshot(1)
    other = build_snapshot(1, regions=[region("019")], subregions=[subregion("419")])
    decision = evaluate_snapshot(other, history(v1))
    assert decision.classification is Classification.B and decision.rejected
    assert {v.rule for v in decision.violations} == {"RF-26"}


def test_a_new_version_older_than_the_last_is_rejected() -> None:
    decision = evaluate_snapshot(build_snapshot(2), history(build_snapshot(1), build_snapshot(3)))
    assert decision.classification is Classification.C and decision.rejected


def test_a_gap_in_versions_is_accepted() -> None:
    assert evaluate_snapshot(build_snapshot(7), history(build_snapshot(3))).proceeds


def test_a_wrong_content_digest_is_rejected_before_classifying() -> None:
    v1 = build_snapshot(1)
    tampered = copy.deepcopy(v1)
    tampered["regions"][0]["status"] = "inactive"
    decision = evaluate_snapshot(tampered, history(v1))
    assert decision.classification is None and decision.rejected
    assert {v.rule for v in decision.violations} == {"RF-21"}


# --- contexto de Locale (RF-31, RF-33, RF-38) ---------------------------------------------------


def test_an_empty_locale_catalog_rejects_the_snapshot() -> None:
    result = plan(build_snapshot(), locales=LocaleCatalog(None, ()))
    assert rules(result) == {"RF-38"}


def test_a_required_locale_missing_from_locale_is_rejected() -> None:
    policy = RequiredLocales(1, (RequiredLocale(EN, "en"), RequiredLocale(str(uuid.uuid4()), "pt")))
    assert rules(plan(build_snapshot(), policy=policy)) == {"RF-31"}


def test_a_required_locale_whose_code_does_not_match_is_rejected() -> None:
    policy = RequiredLocales(1, (RequiredLocale(EN, "en"), RequiredLocale(ES, "pt")))
    result = plan(build_snapshot(), policy=policy)
    assert rules(result) == {"RF-31"} and "pt" in messages(result)


def test_an_inactive_required_locale_is_rejected() -> None:
    assert rules(plan(build_snapshot(), locales=locale_catalog(inactive=["es"]))) == {"RF-33"}


# --- identidad y completitud (RF-2, RF-22, RF-23) -----------------------------------------------


def test_a_valid_first_snapshot_plans_every_entity_and_name_as_new() -> None:
    result = plan(build_snapshot())
    assert result.ok, messages(result)
    assert len(result.new_regions) == 2 and len(result.new_subregions) == 4
    assert len(result.new_region_names) == 4 and len(result.new_subregion_names) == 8
    assert not (result.updated_regions or result.updated_subregions or result.reclassifications)


def test_omitting_a_published_region_subregion_or_name_is_rejected() -> None:
    current = published(build_snapshot(1))
    without_region = build_snapshot(
        2, regions=[region("019")], subregions=[subregion("419"), subregion("021")]
    )
    assert "RF-22" in rules(plan(without_region, current))
    without_subregion = build_snapshot(
        2, subregions=[subregion("015"), subregion("202"), subregion("419")]
    )
    assert rules(plan(without_subregion, current)) == {"RF-22"}
    names = build_snapshot(2)
    names["region_names"] = [n for n in names["region_names"] if n["locale_id"] != ES]
    names["region_names"].append({"region_id": region_id("002"), "locale_id": ES, "name": "África"})
    assert rules(plan(seal(names), current)) == {"RF-22"}


def test_dropping_a_published_name_in_a_non_required_locale_is_rejected() -> None:
    from tests.fixtures.regions import FR

    first = build_snapshot(1)
    first["region_names"].append(
        {"region_id": region_id("002"), "locale_id": FR, "name": "Afrique"}
    )
    current = published(seal(first))
    result = plan(build_snapshot(2), current)
    assert rules(result) == {"RF-22"} and "Afrique" not in messages(result)


@pytest.mark.parametrize("bad_id", ["", "not-a-uuid", "6F9619FF-8B86-D011-B42D-00C04FC964FF"])
def test_a_new_id_must_be_a_lowercase_uuid(bad_id: str) -> None:
    document = build_snapshot(
        regions=[region("002", region_id=bad_id), region("019")], subregions=[subregion("419")]
    )
    document["region_names"] = names_for_regions([bad_id, region_id("019")])
    assert "RF-23" in rules(plan(seal(document)))


def test_a_repeated_id_in_the_snapshot_is_rejected() -> None:
    document = build_snapshot(regions=[region("002"), region("002", code="003")], subregions=[])
    assert "RF-2" in rules(plan(document))
    document = build_snapshot(subregions=[subregion("419"), subregion("419", code="420")])
    assert "RF-2" in rules(plan(document))


def test_the_same_id_cannot_be_a_region_and_a_subregion() -> None:
    shared = region_id("019")
    document = build_snapshot(subregions=[subregion("419", subregion_id=shared)])
    assert "RF-23" in rules(plan(document))


def test_a_new_entity_cannot_reuse_an_id_already_used_by_the_other_type() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(
        2,
        regions=[region("002"), region("019"), region("142", region_id=subregion_id("419"))],
    )
    assert "RF-23" in rules(plan(document, current))


def test_a_published_entity_keeps_its_id_and_new_ones_bring_new_ids() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(
        2,
        regions=[region("002"), region("019"), region("142")],
        subregions=[
            subregion("015"),
            subregion("202"),
            subregion("419"),
            subregion("021"),
            subregion("030"),
        ],
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    assert [r.region_id for r in result.new_regions] == [region_id("142")]
    assert [s.subregion_id for s in result.new_subregions] == [subregion_id("030")]
    assert not result.updated_regions and not result.updated_subregions
