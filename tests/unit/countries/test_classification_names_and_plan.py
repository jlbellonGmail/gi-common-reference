"""T6: clasificación, localizaciones, procedencia, banderas declaradas y plan.

RF-6, RF-19, RF-28, RF-29, RF-31–RF-36, RF-48.
"""

import copy
from typing import Any

import pytest

from tests.fixtures.countries import (
    build_snapshot,
    country,
    country_id,
    flag,
    flag_exception,
    locale_catalog,
    names,
    provenance,
    recoding,
    region_catalog,
)
from tests.fixtures.regions import EN, ES, FR, region_id, subregion_id
from tests.unit.countries.helpers import messages, plan, published, rules

ALL = ("AR", "NA", "AQ", "TW", "US", "CA", "PR", "BV")


def with_country(**overrides: Any) -> dict[str, Any]:
    """El snapshot por defecto con AR modificado."""
    countries = [country("AR", **overrides), *(country(k) for k in ALL if k != "AR")]
    return build_snapshot(countries=countries)


# --- clasificación (RF-6, RF-48) -----------------------------------------------------------------


def test_countries_without_classification_are_valid() -> None:
    """CL-1, CL-2: AQ (sin M49) y TW (ausente en M49) no llevan región ni subregión."""
    result = plan(build_snapshot())
    assert result.ok, messages(result)
    by_code = {c.alpha2: c for c in result.new_countries}
    assert by_code["AQ"].region_id is None and by_code["AQ"].subregion_id is None
    assert by_code["TW"].region_id is None and by_code["TW"].subregion_id is None
    assert by_code["NA"].region_id is not None


def test_a_region_without_subregion_is_valid() -> None:
    result = plan(with_country(subregion_id=None))
    assert result.ok, messages(result)


def test_a_subregion_without_its_region_is_rejected() -> None:
    result = plan(with_country(region_id=None))
    assert rules(result) == {"RF-6"} and "subregion" in messages(result)


def test_unknown_region_or_subregion_is_rejected() -> None:
    nobody = "00000000-0000-4000-8000-000000000000"
    assert rules(plan(with_country(region_id=nobody, subregion_id=None))) == {"RF-6"}
    assert rules(plan(with_country(subregion_id=nobody))) == {"RF-6"}


def test_an_incoherent_region_subregion_pair_is_rejected() -> None:
    """La subregión 419 pertenece a la región 019, no a 002."""
    result = plan(with_country(region_id=region_id("002")))
    assert rules(result) == {"RF-6"} and "pertenece" in messages(result)


def test_an_active_country_cannot_point_to_an_inactive_classification() -> None:
    """CL-18."""
    assert rules(plan(build_snapshot(), regions=region_catalog(inactive=["419"]))) == {"RF-48"}
    assert rules(plan(build_snapshot(), regions=region_catalog(inactive=["019"]))) == {"RF-48"}


def test_an_inactive_country_may_keep_an_inactive_classification_if_it_exists() -> None:
    document = with_country(status="inactive")
    result = plan(document, regions=region_catalog(inactive=["419", "019"]))
    assert rules(result) == {"RF-48"} and country_id("AR") not in messages(result)
    only_inactive = build_snapshot(keys=("AR",), countries=[country("AR", status="inactive")])
    assert plan(only_inactive, regions=region_catalog(inactive=["419", "019"])).ok


def test_the_classification_is_checked_against_the_current_regions_catalog_not_the_declared() -> (
    None
):
    """RF-47/RF-48: el catálogo vigente decide, no la versión declarada."""
    document = build_snapshot(region_snapshot_version=1)
    assert rules(
        plan(document, regions=region_catalog(2, incorporated=[1, 2], inactive=["419"]))
    ) == {"RF-48"}


# --- localizaciones (RF-31–RF-36) ----------------------------------------------------------------


def test_every_country_needs_a_name_in_each_required_locale() -> None:
    document = build_snapshot()
    document["country_names"] = [
        n
        for n in document["country_names"]
        if not (n["country_id"] == country_id("AR") and n["locale_id"] == ES)
    ]
    result = plan(document)
    assert rules(result) == {"RF-35"} and country_id("AR") in messages(result)


def test_optional_official_name_and_extra_locales_without_translation_are_allowed() -> None:
    result = plan(build_snapshot())
    assert result.ok, messages(result)
    assert all(
        n.official_name is None for n in result.new_names if n.country_id == country_id("CA")
    )
    assert len(result.new_names) == 16  # fr no obligatorio: sin traducción permitida


def test_a_name_for_a_country_not_in_the_snapshot_is_rejected() -> None:
    document = build_snapshot()
    document["country_names"].append(
        {
            "country_id": country_id("TL"),
            "locale_id": EN,
            "name": "Timor-Leste",
            "official_name": None,
        }
    )
    assert rules(plan(document)) == {"RF-31"}


def test_a_localization_with_an_unknown_locale_is_rejected() -> None:
    document = build_snapshot()
    document["country_names"].append(
        {
            "country_id": country_id("AR"),
            "locale_id": "00000000-0000-4000-8000-000000000000",
            "name": "x",
            "official_name": None,
        }
    )
    assert rules(plan(document)) == {"RF-36"}


def test_a_duplicate_country_locale_pair_is_rejected() -> None:
    document = build_snapshot()
    document["country_names"].append(copy.deepcopy(document["country_names"][0]))
    assert rules(plan(document)) == {"RF-31"}


@pytest.mark.parametrize(
    "text", ["", " ", " Argentina", "Argentina ", "\tArgentina", "Argentina\n"]
)
def test_names_and_official_names_are_not_empty_nor_padded(text: str) -> None:
    document = build_snapshot()
    document["country_names"][0]["name"] = text
    assert rules(plan(document)) == {"RF-32"}
    document = build_snapshot()
    document["country_names"][0]["official_name"] = text
    assert rules(plan(document)) == {"RF-32"}


def test_a_new_name_with_an_inactive_locale_is_rejected_but_a_published_one_is_kept() -> None:
    fr = {
        "country_id": country_id("AR"),
        "locale_id": FR,
        "name": "Argentine",
        "official_name": None,
    }
    first = build_snapshot()
    first["country_names"].append(fr)
    current = published(first)
    inactive_fr = locale_catalog(inactive=["fr"])

    assert plan(first, locales=locale_catalog()).ok
    assert rules(plan(first, locales=inactive_fr)) == {"RF-36"}  # nuevo con locale inactive

    kept = copy.deepcopy(first)
    kept["snapshot_version"] = 2
    result = plan(kept, current, locales=inactive_fr)
    assert result.ok, messages(result)  # publicado: se conserva y sigue resolviéndose

    changed = copy.deepcopy(kept)
    changed["country_names"][-1]["name"] = "Argentine (FR)"
    result = plan(changed, current, locales=inactive_fr)
    assert result.ok, messages(result)  # cambiar el texto de un par publicado no es uno nuevo
    assert [n.name for n in result.updated_names] == ["Argentine (FR)"]


# --- procedencia (RF-28, RF-29) ------------------------------------------------------------------


def broken_provenance(mutate: Any) -> dict[str, Any]:
    value = provenance()
    mutate(value)
    return build_snapshot(catalog_provenance=value)


@pytest.mark.parametrize(
    "field", ["role", "name", "edition", "retrieved_at", "location", "checksum", "license"]
)
def test_each_source_must_declare_all_its_fields(field: str) -> None:
    for value in ("", "  ", None):
        document = broken_provenance(lambda p, v=value: p["sources"][0].__setitem__(field, v))
        assert rules(plan(document)) == {"RF-28"}, (field, value)
    document = broken_provenance(lambda p: p["sources"][0].pop(field))
    assert rules(plan(document)) == {"RF-28"}


@pytest.mark.parametrize("role", ["identity", "names", "calling_code", "classification", "flags"])
def test_a_required_role_missing_is_rejected(role: str) -> None:
    document = broken_provenance(
        lambda p: p.__setitem__("sources", [s for s in p["sources"] if s["role"] != role])
    )
    result = plan(document)
    assert rules(result) == {"RF-28"} and role in messages(result)


def test_roles_for_unused_data_are_not_required() -> None:
    """Sin códigos de llamada, sin clasificación y sin banderas solo se exigen identity y names."""
    document = build_snapshot(
        keys=("AQ",),
        countries=[country("AQ", calling_code=None)],
        flags=[],
        flag_exceptions=[flag_exception("AQ")],
        catalog_provenance={
            **provenance(),
            "sources": [s for s in provenance()["sources"] if s["role"] in ("identity", "names")],
        },
    )
    result = plan(document)
    assert result.ok, messages(result)


def test_an_unresolved_conflict_blocks_the_snapshot() -> None:
    """RF-29: un conflicto declarado sin resolver no se resuelve en silencio."""
    document = broken_provenance(
        lambda p: p["unresolved_conflicts"].append({"field": "numeric_code", "country": "XX"})
    )
    assert rules(plan(document)) == {"RF-29"}


def test_missing_or_malformed_provenance_is_rejected() -> None:
    values: list[Any] = [None, [], {"sources": "ISO"}, {"sources": [], "unresolved_conflicts": []}]
    for value in values:
        document = build_snapshot(catalog_provenance=value)
        document["provenance"] = value
        assert rules(plan(document)) == {"RF-28"}, value


# --- banderas declaradas (RF-19) -----------------------------------------------------------------


def test_an_active_country_without_flag_nor_exception_is_rejected() -> None:
    document = build_snapshot(flags=[flag(k) for k in ("AR", "NA", "TW", "US", "CA")])
    result = plan(document)
    assert rules(result) == {"RF-19"} and country_id("PR") in messages(result)


def test_a_country_with_both_a_flag_and_an_exception_is_rejected() -> None:
    document = build_snapshot()
    document["flag_exceptions"].append(flag_exception("AQ", identity="AR"))
    assert rules(plan(document)) == {"RF-19"}


def test_a_country_with_one_flag_or_one_exception_is_accepted() -> None:
    result = plan(build_snapshot())
    assert result.ok, messages(result)
    assert len(result.new_flags) == 8
    assert {f.exception_reason is None for f in result.new_flags} == {True, False}


def test_an_exception_needs_a_trimmed_reason_and_a_flag_a_country_and_svg_media_type() -> None:
    document = build_snapshot()
    document["flag_exceptions"][0]["reason"] = " "
    assert rules(plan(document)) == {"RF-19"}
    document = build_snapshot()
    document["flags"].append(flag("AR", identity="TL"))
    assert rules(plan(document)) == {"RF-19"}
    document = build_snapshot()
    document["flags"][0]["media_type"] = "image/png"
    assert rules(plan(document)) == {"RF-49"}


def test_a_flag_must_reference_a_declared_source_role() -> None:
    document = build_snapshot()
    document["flags"][0]["source"] = "identity"
    assert plan(document).ok
    document["provenance"]["sources"] = [
        s for s in document["provenance"]["sources"] if s["role"] != "flags"
    ]
    assert rules(plan(document)) == {"RF-28"}


@pytest.mark.parametrize(
    "path", ["../ar.svg", "/ar.svg", "a//b.svg", "ar.png", "a\\b.svg", "x/../y.svg", ""]
)
def test_an_unsafe_asset_path_is_rejected(path: str) -> None:
    document = build_snapshot()
    document["flags"][0]["asset_path"] = path
    assert rules(plan(document)) == {"RF-49"}


# --- plan exacto ----------------------------------------------------------------------------------


def test_the_plan_of_a_name_change_touches_only_that_name() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(2)
    document["country_names"][1]["name"] = "Argentina (AR)"
    result = plan(document, current)
    assert result.ok and [n.name for n in result.updated_names] == ["Argentina (AR)"]
    assert not (result.new_countries or result.updated_countries or result.recodings)
    assert not (result.new_names or result.new_flags or result.updated_flags)


def test_the_plan_of_a_classification_change_updates_only_that_country() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(
        2,
        countries=[
            country("AR", region_id=region_id("142"), subregion_id=subregion_id("035")),
            *(country(k) for k in ALL if k != "AR"),
        ],
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    (updated,) = result.updated_countries
    assert (updated.country_id, updated.subregion_id) == (country_id("AR"), subregion_id("035"))
    assert not result.recodings and not result.updated_names


def test_the_plan_of_a_flag_change_between_exception_and_asset() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(
        2,
        flags=[flag(k) for k in ("AR", "NA", "TW", "US", "CA", "PR", "BV")],
        flag_exceptions=[flag_exception("AQ")],
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    (changed,) = result.updated_flags
    assert changed.country_id == country_id("BV") and changed.exception_reason is None


def test_resending_the_published_state_produces_an_empty_plan() -> None:
    current = published(build_snapshot(1))
    result = plan(build_snapshot(2), current)
    assert result.ok and result.is_empty


def test_the_plan_of_a_recoding_carries_the_trace_and_changes_only_the_codes() -> None:
    tp = ("TP", "TMP", "626")
    tl = ("TL", "TLS", "626")
    v1 = build_snapshot(1, keys=(*ALL, "TP"))
    v2 = build_snapshot(
        2,
        countries=[*(country(k) for k in ALL), country("TL", identity="TP")],
        country_names=[*(n for k in ALL for n in names(k)), *names("TP")],
        flags=[*(flag(k) for k in ALL if k not in ("AQ", "BV")), flag("TP")],
        flag_exceptions=[flag_exception("AQ"), flag_exception("BV")],
        recodings=[recoding("TP", tp, tl)],
    )
    result = plan(v2, published(v1))
    assert result.ok, messages(result)
    (trace,) = result.recodings
    assert trace.country_id == country_id("TP") and trace.new.alpha2 == "TL"
    assert [c.alpha2 for c in result.updated_countries] == ["TL"]
    assert not result.new_names and not result.updated_names
