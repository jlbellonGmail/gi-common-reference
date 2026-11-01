"""T4: admisión e identidad del snapshot (RF-2, RF-21, RF-25, RF-27, RF-35, RF-36, RF-45, RF-47)."""

import copy
import uuid

import pytest

from gi_common_reference.countries.domain.model import LocaleCatalog, RegionCatalog
from gi_common_reference.countries.domain.policy import RequiredLocale, RequiredLocales
from gi_common_reference.countries.domain.snapshot import (
    Classification,
    HistoricalSnapshot,
    evaluate_snapshot,
)
from tests.fixtures.countries import (
    build_snapshot,
    country,
    country_id,
    flag,
    locale_catalog,
    names,
    region_catalog,
    seal,
)
from tests.fixtures.regions import EN, ES
from tests.unit.countries.helpers import messages, plan, published, rules


def history(*documents: dict[str, object]) -> list[HistoricalSnapshot]:
    return [
        HistoricalSnapshot(int(str(d["snapshot_version"])), str(d["content_digest"]))
        for d in documents
    ]


# --- digest y clasificación (RF-25, RF-27) ------------------------------------------------------


def test_the_first_snapshot_proceeds_with_any_version() -> None:
    decision = evaluate_snapshot(build_snapshot(7), [])
    assert decision.classification is Classification.D and decision.proceeds


def test_the_same_snapshot_again_is_a_noop() -> None:
    v1 = build_snapshot(1)
    decision = evaluate_snapshot(copy.deepcopy(v1), history(v1))
    assert decision.classification is Classification.A and decision.is_noop


def test_an_earlier_snapshot_resent_after_a_later_one_is_a_noop() -> None:
    v1, v2 = build_snapshot(1), build_snapshot(2, keys=("AR",))
    assert evaluate_snapshot(v1, history(v1, v2)).is_noop


def test_the_same_version_with_other_content_is_rejected() -> None:
    v1 = build_snapshot(1)
    other = build_snapshot(1, keys=("AR",))
    decision = evaluate_snapshot(other, history(v1))
    assert decision.classification is Classification.B and decision.rejected
    assert {v.rule for v in decision.violations} == {"RF-25"}


def test_a_new_version_older_than_the_last_is_rejected() -> None:
    decision = evaluate_snapshot(build_snapshot(2), history(build_snapshot(1), build_snapshot(3)))
    assert decision.classification is Classification.C and decision.rejected
    assert {v.rule for v in decision.violations} == {"RF-25"}


def test_a_gap_in_versions_is_accepted() -> None:
    assert evaluate_snapshot(build_snapshot(7), history(build_snapshot(3))).proceeds


def test_a_wrong_content_digest_is_rejected_before_classifying() -> None:
    v1 = build_snapshot(1)
    tampered = copy.deepcopy(v1)
    tampered["countries"][0]["status"] = "inactive"
    decision = evaluate_snapshot(tampered, history(v1))
    assert decision.classification is None and decision.rejected
    assert {v.rule for v in decision.violations} == {"RF-27"}


# --- contexto de Locale (RF-35, RF-36) ----------------------------------------------------------


def test_an_empty_locale_catalog_rejects_the_snapshot() -> None:
    result = plan(build_snapshot(), locales=LocaleCatalog(None, ()))
    assert rules(result) == {"RF-36"}


def test_a_required_locale_missing_from_locale_is_rejected() -> None:
    policy = RequiredLocales(1, (RequiredLocale(EN, "en"), RequiredLocale(str(uuid.uuid4()), "pt")))
    assert rules(plan(build_snapshot(), policy=policy)) == {"RF-35"}
    assert rules(plan(build_snapshot(), locales=locale_catalog(missing=["es"]))) == {"RF-35"}


def test_a_required_locale_whose_code_does_not_match_is_rejected() -> None:
    policy = RequiredLocales(1, (RequiredLocale(EN, "en"), RequiredLocale(ES, "pt")))
    result = plan(build_snapshot(), policy=policy)
    assert rules(result) == {"RF-35"} and "pt" in messages(result)


def test_an_inactive_required_locale_is_rejected() -> None:
    result = plan(build_snapshot(), locales=locale_catalog(inactive=["es"]))
    assert rules(result) == {"RF-36"}


# --- contexto de Region/Subregion (RF-47) -------------------------------------------------------


def test_an_empty_regions_catalog_rejects_the_snapshot() -> None:
    result = plan(build_snapshot(), regions=RegionCatalog(None))
    assert rules(result) == {"RF-47"}


def test_a_declared_regions_version_not_incorporated_or_later_than_current_is_rejected() -> None:
    absent = plan(
        build_snapshot(region_snapshot_version=2), regions=region_catalog(3, incorporated=[1, 3])
    )
    assert rules(absent) == {"RF-47"} and "no está incorporada" in messages(absent)
    later = plan(
        build_snapshot(region_snapshot_version=4), regions=region_catalog(3, incorporated=[1, 3])
    )
    assert rules(later) == {"RF-47"} and "posterior" in messages(later)


def test_an_older_incorporated_regions_version_is_accepted() -> None:
    result = plan(
        build_snapshot(region_snapshot_version=1), regions=region_catalog(3, incorporated=[1, 2, 3])
    )
    assert result.ok, messages(result)


# --- orden de los pasos --------------------------------------------------------------------------


def test_the_first_failing_step_is_the_only_one_reported() -> None:
    """El contexto falla antes que la identidad: no se informan ambos."""
    broken = build_snapshot(countries=[country("AR"), country("AR")], keys=("AR",))
    result = plan(broken, locales=LocaleCatalog(None, ()))
    assert rules(result) == {"RF-36"}
    assert rules(plan(broken)) == {"RF-2"}


# --- identidad y completitud (RF-2, RF-21, RF-45) -----------------------------------------------


def test_a_valid_first_snapshot_plans_every_country_name_and_flag_as_new() -> None:
    result = plan(build_snapshot())
    assert result.ok, messages(result)
    assert len(result.new_countries) == 8 and not result.updated_countries
    assert len(result.new_names) == 16 and not result.updated_names
    assert len(result.new_flags) == 8 and not result.updated_flags


def test_omitting_a_published_country_is_rejected() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(2, keys=("AR", "NA", "AQ", "TW", "US", "CA", "PR"))
    result = plan(document, current)
    assert rules(result) == {"RF-21"}
    assert "BV" in messages(result) or country_id("BV") in messages(result)


def test_omitting_a_published_name_is_rejected_even_in_a_non_required_locale() -> None:
    first = build_snapshot(1)
    first["country_names"].append(
        {
            "country_id": country_id("AR"),
            "locale_id": "b8756f67-cbc0-4499-b3b6-453605c505b2",
            "name": "Argentine",
            "official_name": None,
        }
    )
    current = published(seal(first))
    result = plan(build_snapshot(2), current)
    assert rules(result) == {"RF-21"} and "Argentine" not in messages(result)


def test_omitting_a_published_flag_or_exception_is_rejected() -> None:
    current = published(build_snapshot(1))
    without_flag = build_snapshot(2, flags=[flag(k) for k in ("AR", "NA", "TW", "US", "CA")])
    result = plan(without_flag, current)
    assert rules(result) == {"RF-21"} and country_id("PR") in messages(result)
    without_exception = build_snapshot(2, flag_exceptions=[])
    result = plan(without_exception, current)
    assert rules(result) == {"RF-21"} and country_id("AQ") in messages(result)


def test_changing_a_flag_into_an_exception_or_back_is_not_an_omission() -> None:
    current = published(build_snapshot(1))
    swapped_flags = [flag(k) for k in ("AR", "NA", "TW", "US", "CA")]
    document = build_snapshot(
        2,
        flags=swapped_flags,
        flag_exceptions=[
            {"country_id": country_id(k), "reason": "ya no hay bandera"} for k in ("AQ", "BV", "PR")
        ],
    )
    result = plan(document, current)
    assert "RF-21" not in rules(result), messages(result)


@pytest.mark.parametrize("bad_id", ["", "not-a-uuid", "6F9619FF-8B86-D011-B42D-00C04FC964FF"])
def test_a_new_id_must_be_a_lowercase_uuid(bad_id: str) -> None:
    document = build_snapshot(
        keys=("AR",), countries=[country("AR", country_id=bad_id)], country_names=[]
    )
    document["country_names"] = [{**n, "country_id": bad_id} for n in names("AR")]
    document["flags"] = []
    document["flag_exceptions"] = [{"country_id": bad_id, "reason": "x"}]
    assert "RF-2" in rules(plan(seal(document)))


def test_a_repeated_country_id_in_the_snapshot_is_rejected() -> None:
    document = build_snapshot(
        keys=("AR", "NA"), countries=[country("AR"), country("NA", country_id=country_id("AR"))]
    )
    assert "RF-2" in rules(plan(document))


def test_a_published_country_keeps_its_id_and_new_ones_bring_new_ids() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(2, keys=(*("AR", "NA", "AQ", "TW", "US", "CA", "PR", "BV"), "TL"))
    result = plan(document, current)
    assert result.ok, messages(result)
    assert [c.country_id for c in result.new_countries] == [country_id("TL")]
    assert not result.updated_countries
