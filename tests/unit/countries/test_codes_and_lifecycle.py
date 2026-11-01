"""T5: códigos, recodificación, reasignación y ciclo de vida (RF-3–RF-5, RF-22, RF-39–RF-46)."""

from typing import Any

import pytest

from gi_common_reference.countries.domain.codes import (
    is_valid_alpha2,
    is_valid_alpha3,
    is_valid_calling_code,
    is_valid_numeric_code,
)
from gi_common_reference.countries.domain.model import CodeKind
from tests.fixtures.countries import (
    build_snapshot,
    country,
    country_id,
    flag,
    flag_exception,
    names,
    reassignment,
    recoding,
    seal,
)
from tests.unit.countries.helpers import messages, plan, published, rules

ALL = ("AR", "NA", "AQ", "TW", "US", "CA", "PR", "BV")
History = tuple[tuple[CodeKind, str, str], ...]


def extra(identity: str, **overrides: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Un país sintético nuevo (sin clasificación) con sus nombres; devuelve (país, nombres)."""
    base = {"alpha2": "ZZ", "alpha3": "ZZZ", "numeric_code": "999", "region_id": None}
    item = country("AQ", identity=identity, **{**base, "subregion_id": None, **overrides})
    return item, names("AQ", identity=identity)


def with_extra(
    version: int, items: list[tuple[dict[str, Any], list[dict[str, Any]]]], **kwargs: Any
) -> dict[str, Any]:
    """El snapshot por defecto más países extra con su excepción de bandera."""
    base = build_snapshot(version)
    countries = [*base["countries"], *(c for c, _ in items)]
    country_names = [*base["country_names"], *(n for _, ns in items for n in ns)]
    exceptions = [
        *base["flag_exceptions"],
        *({"country_id": c["country_id"], "reason": "x"} for c, _ in items),
    ]
    return build_snapshot(
        version,
        countries=countries,
        country_names=country_names,
        flags=base["flags"],
        flag_exceptions=exceptions,
        **kwargs,
    )


# --- formatos (RF-5) -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("check", "valid", "invalid"),
    [
        (
            is_valid_alpha2,
            ["AR", "NA", "US"],
            ["ar", "Na", " AR", "AR ", "A", "ARG", "A1", "Ñ1", ""],
        ),
        (is_valid_alpha3, ["ARG", "NAM"], ["arg", "AR", "ARGE", "AR1", "AR\n", " ARG", ""]),
        (
            is_valid_numeric_code,
            ["004", "032", "840"],
            ["4", "04", "0004", "abc", "٣٢٠", " 32", ""],
        ),
        (is_valid_calling_code, ["1", "54", "264", "599"], ["+54", "054", "0", "5400", "5 4", ""]),
    ],
)
def test_code_formats(check: Any, valid: list[str], invalid: list[str]) -> None:
    assert all(check(code) for code in valid)
    assert not any(check(code) for code in invalid)


def test_namibia_and_leading_zero_codes_are_valid_in_a_snapshot() -> None:
    """CL-5, CL-6: `NA` no es nulo y `004` conserva sus ceros."""
    document = build_snapshot(
        keys=("NA", "AQ"),
        countries=[country("NA"), country("AQ", numeric_code="004")],
    )
    result = plan(document)
    assert result.ok, messages(result)
    assert {c.alpha2 for c in result.new_countries} == {"NA", "AQ"}
    assert "004" in {c.numeric_code for c in result.new_countries}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("alpha2", "ar"),
        ("alpha2", "AR1"),
        ("alpha3", "arg"),
        ("alpha3", "AR"),
        ("numeric_code", "32"),
        ("numeric_code", "4"),
        ("numeric_code", "0032"),
        ("calling_code", "+54"),
        ("calling_code", "054"),
        ("calling_code", "5400"),
    ],
)
def test_malformed_codes_are_rejected_without_normalizing(field: str, value: str) -> None:
    document = build_snapshot(keys=("AR",), countries=[country("AR", **{field: value})])
    assert rules(plan(document)) == {"RF-5"}


def test_shared_calling_codes_are_not_treated_as_unique() -> None:
    """CL-3: US, CA y PR comparten `1`; BV no tiene código (CL-4)."""
    result = plan(build_snapshot())
    assert result.ok, messages(result)
    ones = [c for c in result.new_countries if c.calling_code == "1"]
    assert {c.alpha2 for c in ones} == {"US", "CA", "PR"}
    assert any(c.calling_code is None for c in result.new_countries)


# --- unicidad entre active (RF-3, RF-44) ---------------------------------------------------------


@pytest.mark.parametrize("field", ["alpha2", "alpha3", "numeric_code"])
def test_two_active_countries_cannot_share_a_code(field: str) -> None:
    other, other_names = extra("ZZ", **{field: country("AR")[field]})
    result = plan(with_extra(1, [(other, other_names)]))
    assert rules(result) == {"RF-3"} and field in messages(result)


def test_an_inactive_country_may_share_a_code_with_an_active_one() -> None:
    other, other_names = extra("ZZ", alpha2="AR", status="inactive")
    result = plan(with_extra(1, [(other, other_names)]))
    assert result.ok, messages(result)


# --- cambios de código sin declarar (RF-4, RF-42) ------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"alpha2": "AX"},
        {"alpha3": "ARX"},
        {"numeric_code": "033"},
        {"alpha2": "AX", "alpha3": "AXX"},
    ],
)
def test_changing_any_component_without_declaring_it_is_rejected(change: dict[str, str]) -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(
        2, countries=[country("AR", **change), *[country(k) for k in ALL if k != "AR"]]
    )
    result = plan(document, current)
    assert rules(result) == {"RF-42"} and country_id("AR") in messages(result)


def test_a_name_change_with_the_same_codes_needs_no_recoding() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(2)
    document["country_names"][0]["name"] = "La Argentina"
    result = plan(document, current)
    assert result.ok, messages(result)
    assert len(result.updated_names) == 1 and not result.recodings
    assert not result.updated_countries


# --- recodificación (RF-41, RF-42, RF-46) --------------------------------------------------------

TP = ("TP", "TMP", "626")
TL = ("TL", "TLS", "626")


def timor_v1() -> dict[str, Any]:
    return build_snapshot(1, keys=(*ALL, "TP"))


def timor_v2(**kwargs: Any) -> dict[str, Any]:
    """Timor se recodifica TP/TMP/626 → TL/TLS/626 conservando id, estado y nombres."""
    kwargs.setdefault("recodings", [recoding("TP", TP, TL)])
    return build_snapshot(
        2,
        countries=[*(country(k) for k in ALL), country("TL", identity="TP")],
        country_names=[*(n for k in ALL for n in names(k)), *names("TP")],
        flags=[*(flag(k) for k in ALL if k not in ("AQ", "BV")), flag("TP")],
        flag_exceptions=[flag_exception("AQ"), flag_exception("BV")],
        **kwargs,
    )


def test_a_declared_recoding_keeps_the_id_status_and_names() -> None:
    """CL-10: mismo country_id, otros códigos, traza registrada."""
    current = published(timor_v1())
    result = plan(timor_v2(), current)
    assert result.ok, messages(result)
    assert not result.new_countries and not result.new_names and not result.updated_names
    (updated,) = result.updated_countries
    assert (updated.country_id, updated.status) == (country_id("TP"), "active")
    assert (updated.alpha2, updated.alpha3, updated.numeric_code) == TL
    (trace,) = result.recodings
    assert (trace.previous.alpha2, trace.new.alpha2) == ("TP", "TL")


def test_a_recoding_without_provenance_is_rejected() -> None:
    current = published(timor_v1())
    for provenance in (None, {}, {"source": ""}, {"source": "   "}, "ISO"):
        document = timor_v2(recodings=[recoding("TP", TP, TL, provenance=provenance)])
        assert rules(plan(document, current)) == {"RF-42"}, provenance


def test_a_recoding_with_a_wrong_previous_triple_is_rejected() -> None:
    current = published(timor_v1())
    document = timor_v2(recodings=[recoding("TP", ("TX", "TMP", "626"), TL)])
    result = plan(document, current)
    assert rules(result) == {"RF-42"} and "TX" in messages(result)


def test_a_recoding_whose_new_triple_differs_from_the_snapshot_is_rejected() -> None:
    current = published(timor_v1())
    document = timor_v2(recodings=[recoding("TP", TP, ("TL", "TLS", "627"))])
    assert rules(plan(document, current)) == {"RF-41"}


def test_a_recoding_that_changes_nothing_is_rejected() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(
        2, recodings=[recoding("AR", ("AR", "ARG", "032"), ("AR", "ARG", "032"))]
    )
    assert rules(plan(document, current)) == {"RF-42"}


def test_a_recoding_of_an_unpublished_country_is_rejected() -> None:
    other, other_names = extra("ZZ")
    document = with_extra(
        1,
        [(other, other_names)],
        recodings=[recoding("ZZ", ("ZY", "ZZY", "998"), ("ZZ", "ZZZ", "999"))],
    )
    assert rules(plan(document)) == {"RF-42"}


def test_a_recoding_declared_twice_is_rejected() -> None:
    current = published(timor_v1())
    document = timor_v2(recodings=[recoding("TP", TP, TL), recoding("TP", TP, TL)])
    assert "RF-41" in rules(plan(document, current))


# --- reasignaciones (RF-43, RF-44) ---------------------------------------------------------------


def swapped() -> dict[str, Any]:
    """AR y NA intercambian `alpha2` en un mismo snapshot."""
    return build_snapshot(
        2,
        countries=[
            country("AR", alpha2="NA"),
            country("NA", alpha2="AR"),
            *(country(k) for k in ALL if k not in ("AR", "NA")),
        ],
    )


def test_a_declared_swap_of_codes_is_accepted_on_the_final_state() -> None:
    """CL-13."""
    current = published(build_snapshot(1))
    document = build_snapshot(
        2,
        countries=swapped()["countries"],
        recodings=[
            recoding("AR", ("AR", "ARG", "032"), ("NA", "ARG", "032")),
            recoding("NA", ("NA", "NAM", "516"), ("AR", "NAM", "516")),
        ],
        code_reassignments=[
            reassignment("AR", "alpha2", "NA"),
            reassignment("NA", "alpha2", "AR"),
        ],
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    assert len(result.recodings) == 2 and len(result.updated_countries) == 2


def test_an_undeclared_swap_is_rejected() -> None:
    current = published(build_snapshot(1))
    result = plan(swapped(), current)
    assert rules(result) == {"RF-42", "RF-43"}


def test_a_swap_with_recodings_but_without_reassignments_is_rejected() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(
        2,
        countries=swapped()["countries"],
        recodings=[
            recoding("AR", ("AR", "ARG", "032"), ("NA", "ARG", "032")),
            recoding("NA", ("NA", "NAM", "516"), ("AR", "NAM", "516")),
        ],
    )
    result = plan(document, current)
    assert rules(result) == {"RF-43"} and len(result.violations) == 2


def test_reusing_a_current_code_of_another_country_needs_a_declared_reassignment() -> None:
    """Un país nuevo toma el `alpha2` de un `inactive` (CL-7)."""
    first, first_names = extra(
        "ZZ", alpha2="ZA", alpha3="ZAA", numeric_code="900", status="inactive"
    )
    current = published(with_extra(1, [(first, first_names)]))
    newcomer, newcomer_names = extra("ZY", alpha2="ZA", alpha3="ZYY", numeric_code="901")
    keep = [(first, first_names), (newcomer, newcomer_names)]
    assert rules(plan(with_extra(2, keep), current)) == {"RF-43"}
    declared = with_extra(2, keep, code_reassignments=[reassignment("ZY", "alpha2", "ZA")])
    assert plan(declared, current).ok


def test_reusing_a_historical_code_needs_a_declared_reassignment() -> None:
    history: History = (("alpha2", "TP", country_id("TP")),)
    current = published(build_snapshot(1), history)
    newcomer, newcomer_names = extra("ZY", alpha2="TP", alpha3="ZYY", numeric_code="901")
    assert rules(plan(with_extra(2, [(newcomer, newcomer_names)]), current)) == {"RF-43"}
    declared = with_extra(
        2, [(newcomer, newcomer_names)], code_reassignments=[reassignment("ZY", "alpha2", "TP")]
    )
    assert plan(declared, current).ok


def test_a_reassignment_that_does_not_correspond_is_rejected() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(2, code_reassignments=[reassignment("AR", "alpha2", "QQ")])
    assert rules(plan(document, current)) == {"RF-43"}
    other, other_names = extra("ZY")
    document = with_extra(
        2, [(other, other_names)], code_reassignments=[reassignment("ZY", "alpha2", "ZZ")]
    )
    assert rules(plan(document, current)) == {"RF-43"}


def test_a_reassignment_without_provenance_or_repeated_is_rejected() -> None:
    history: History = (("alpha2", "TP", country_id("TP")),)
    current = published(build_snapshot(1), history)
    newcomer, newcomer_names = extra("ZY", alpha2="TP", alpha3="ZYY", numeric_code="901")
    bare = with_extra(
        2,
        [(newcomer, newcomer_names)],
        code_reassignments=[reassignment("ZY", "alpha2", "TP", provenance={"source": " "})],
    )
    assert rules(plan(bare, current)) == {"RF-43"}
    twice = with_extra(
        2,
        [(newcomer, newcomer_names)],
        code_reassignments=[reassignment("ZY", "alpha2", "TP"), reassignment("ZY", "alpha2", "TP")],
    )
    assert rules(plan(twice, current)) == {"RF-43"}


def test_an_active_collision_on_the_final_state_is_rejected_even_if_declared() -> None:
    current = published(build_snapshot(1))
    newcomer, newcomer_names = extra("ZY", alpha2="AR", alpha3="ZYY", numeric_code="901")
    document = with_extra(
        2, [(newcomer, newcomer_names)], code_reassignments=[reassignment("ZY", "alpha2", "AR")]
    )
    assert rules(plan(document, current)) == {"RF-3"}


# --- retiro, división, fusión y reactivación (RF-22, RF-45) --------------------------------------


def test_retiring_a_country_keeps_its_id_and_codes() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(
        2, countries=[country("AR", status="inactive"), *(country(k) for k in ALL if k != "AR")]
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    (retired,) = result.updated_countries
    assert (retired.country_id, retired.alpha2, retired.status) == (
        country_id("AR"),
        "AR",
        "inactive",
    )
    assert not result.recodings and not result.new_countries


def test_a_split_creates_new_ids_and_leaves_the_old_one_inactive_without_replacement() -> None:
    """CL-12: AN → CW, SX y BQ."""
    v1 = build_snapshot(1, keys=(*ALL, "AN"))
    current = published(v1)
    keys = (*ALL, "CW", "SX", "BQ")
    document = build_snapshot(
        2,
        countries=[*(country(k) for k in keys), country("AN", status="inactive")],
        country_names=[*(n for k in keys for n in names(k)), *names("AN")],
        flags=[*(flag(k) for k in keys if k not in ("AQ", "BV")), flag("AN")],
        flag_exceptions=[flag_exception("AQ"), flag_exception("BV")],
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    assert {c.alpha2 for c in result.new_countries} == {"CW", "SX", "BQ"}
    assert len({c.country_id for c in result.new_countries}) == 3
    (old,) = result.updated_countries
    assert (old.alpha2, old.status, old.replacement_country_ids) == ("AN", "inactive", ())


def test_a_merge_into_a_successor_records_an_unambiguous_replacement() -> None:
    v1 = build_snapshot(1, keys=(*ALL, "AN"))
    current = published(v1)
    document = build_snapshot(
        2,
        countries=[
            *(country(k) for k in ALL),
            country("AN", status="inactive", replacement_country_ids=[country_id("AR")]),
        ],
        country_names=[*(n for k in ALL for n in names(k)), *names("AN")],
        flags=[*(flag(k) for k in ALL if k not in ("AQ", "BV")), flag("AN")],
        flag_exceptions=[flag_exception("AQ"), flag_exception("BV")],
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    assert result.updated_countries[0].replacement_country_ids == (country_id("AR"),)


def test_reactivating_an_inactive_country_is_accepted_when_the_final_state_is_valid() -> None:
    inactive = build_snapshot(
        1,
        countries=[
            country("AR", status="inactive", replacement_country_ids=[country_id("NA")]),
            country("NA"),
        ],
        keys=("AR", "NA"),
    )
    current = published(inactive)
    reactivated = build_snapshot(2, keys=("AR", "NA"))
    result = plan(reactivated, current)
    assert result.ok, messages(result)
    (back,) = result.updated_countries
    assert (back.status, back.replacement_country_ids) == ("active", ())


def test_reactivating_with_a_colliding_code_or_a_leftover_replacement_is_rejected() -> None:
    inactive = build_snapshot(
        1, countries=[country("AR", status="inactive"), country("NA")], keys=("AR", "NA")
    )
    current = published(inactive)
    other, other_names = extra("ZY", alpha2="AR", alpha3="ZYY", numeric_code="901")
    colliding = build_snapshot(
        2,
        countries=[country("AR"), country("NA"), other],
        country_names=[*names("AR"), *names("NA"), *other_names],
        flag_exceptions=[flag_exception("AQ", identity="ZY")],
        flags=[flag("AR"), flag("NA")],
    )
    assert "RF-3" in rules(plan(colliding, current))
    leftover = build_snapshot(
        2,
        countries=[country("AR", replacement_country_ids=[country_id("NA")]), country("NA")],
        keys=("AR", "NA"),
    )
    assert rules(plan(leftover, current)) == {"RF-40"}


# --- estado y reemplazo (RF-39, RF-40) -----------------------------------------------------------


@pytest.mark.parametrize("status", ["enabled", "ACTIVE", "", "deprecated"])
def test_status_is_only_active_or_inactive(status: str) -> None:
    document = build_snapshot(keys=("AR",), countries=[country("AR", status=status)])
    assert rules(plan(document)) == {"RF-39"}


def test_replacement_rules() -> None:
    nobody = "00000000-0000-4000-8000-000000000000"
    cases = {
        "active with replacement": [
            country("AR", replacement_country_ids=[country_id("NA")]),
            country("NA"),
        ],
        "to itself": [
            country("AR", status="inactive", replacement_country_ids=[country_id("AR")]),
            country("NA"),
        ],
        "nonexistent": [
            country("AR", status="inactive", replacement_country_ids=[nobody]),
            country("NA"),
        ],
    }
    for label, countries in cases.items():
        document = build_snapshot(countries=countries, keys=("AR", "NA"))
        assert rules(plan(document)) == {"RF-40"}, label


def test_a_replacement_cycle_is_rejected() -> None:
    document = build_snapshot(
        countries=[
            country("AR", status="inactive", replacement_country_ids=[country_id("NA")]),
            country("NA", status="inactive", replacement_country_ids=[country_id("AR")]),
        ],
        keys=("AR", "NA"),
    )
    result = plan(document)
    assert rules(result) == {"RF-40"} and "ciclo" in messages(result)


def test_a_replacement_to_a_country_of_the_same_snapshot_is_accepted() -> None:
    document = build_snapshot(
        countries=[
            country("AR", status="inactive", replacement_country_ids=[country_id("NA")]),
            country("NA"),
        ],
        keys=("AR", "NA"),
    )
    assert plan(document).ok


def test_the_status_never_creates_a_new_country_id() -> None:
    current = published(build_snapshot(1))
    document = build_snapshot(
        2, countries=[country("AR", status="inactive"), *(country(k) for k in ALL if k != "AR")]
    )
    result = plan(document, current)
    assert {c.country_id for c in result.updated_countries} <= {
        c.country_id for c in current.countries
    }


# --- reemplazo 0..N (RF-52, CL-12, CL-22, CL-23) ------------------------------------------------


def split_document(version: int, *, successors: list[str], extra_status: str = "active") -> Any:
    """AN `inactive` con los sucesores indicados; CW, SX y BQ existen en el snapshot."""
    keys = (*ALL, "CW", "SX", "BQ")
    ids = {"CW": country_id("CW"), "SX": country_id("SX"), "BQ": country_id("BQ")}
    return build_snapshot(
        version,
        countries=[
            *(country(k) for k in keys),
            country("AN", status="inactive", replacement_country_ids=[ids[k] for k in successors]),
        ],
        country_names=[*(n for k in keys for n in names(k)), *names("AN")],
        flags=[*(flag(k) for k in keys if k not in ("AQ", "BV")), flag("AN")],
        flag_exceptions=[flag_exception("AQ"), flag_exception("BV")],
    )


def test_a_split_records_every_successor_in_ascending_id_order() -> None:
    """CL-12, CA-21: AN → CW, SX y BQ."""
    current = published(build_snapshot(1, keys=(*ALL, "AN")))
    result = plan(split_document(2, successors=["SX", "CW", "BQ"]), current)
    assert result.ok, messages(result)
    (old,) = result.updated_countries
    expected = tuple(sorted(country_id(k) for k in ("CW", "SX", "BQ")))
    assert old.replacement_country_ids == expected and len(expected) == 3


def test_zero_one_or_many_successors_are_all_valid() -> None:
    current = published(build_snapshot(1, keys=(*ALL, "AN")))
    for successors, size in (([], 0), (["CW"], 1), (["CW", "SX"], 2), (["CW", "SX", "BQ"], 3)):
        result = plan(split_document(2, successors=successors), current)
        assert result.ok, messages(result)
        assert len(result.updated_countries[0].replacement_country_ids) == size


def test_the_same_successors_in_another_order_are_not_a_change() -> None:
    first = split_document(1, successors=["CW", "SX", "BQ"])
    current = published(first)
    reordered = split_document(2, successors=["BQ", "CW", "SX"])
    result = plan(reordered, current)
    assert result.ok and result.is_empty, messages(result)


def test_adding_or_removing_a_successor_is_a_change_of_the_country() -> None:
    current = published(split_document(1, successors=["CW", "SX"]))
    added = plan(split_document(2, successors=["CW", "SX", "BQ"]), current)
    removed = plan(split_document(2, successors=["CW"]), current)
    assert [c.alpha2 for c in added.updated_countries] == ["AN"]
    assert [c.alpha2 for c in removed.updated_countries] == ["AN"]


def test_a_repeated_successor_is_rejected() -> None:
    """CL-22."""
    result = plan(split_document(1, successors=["CW", "CW"]))
    assert rules(result) == {"RF-40"} and "repetido" in messages(result)


def test_a_null_successor_inside_the_set_is_rejected() -> None:
    document = split_document(1, successors=["CW"])
    an = next(c for c in document["countries"] if c["alpha2"] == "AN")
    an["replacement_country_ids"] = [None, country_id("CW")]
    assert rules(plan(seal(document))) == {"RF-40"}


def test_an_active_country_cannot_have_any_successor() -> None:
    document = build_snapshot(
        countries=[
            country("AR", replacement_country_ids=[country_id("NA"), country_id("US")]),
            country("NA"),
            country("US"),
        ],
        keys=("AR", "NA", "US"),
    )
    assert rules(plan(document)) == {"RF-40"}


def test_every_nonexistent_successor_is_reported() -> None:
    nobody = "00000000-0000-4000-8000-000000000000"
    other = "00000000-0000-4000-8000-000000000001"
    document = build_snapshot(
        countries=[
            country(
                "AR", status="inactive", replacement_country_ids=[nobody, other, country_id("NA")]
            ),
            country("NA"),
        ],
        keys=("AR", "NA"),
    )
    result = plan(document)
    assert rules(result) == {"RF-40"} and len(result.violations) == 2


def test_a_successor_may_be_inactive_in_a_chain_but_a_longer_cycle_is_rejected() -> None:
    """CL-23."""
    chain = build_snapshot(
        countries=[
            country("AR", status="inactive", replacement_country_ids=[country_id("NA")]),
            country("NA", status="inactive", replacement_country_ids=[country_id("US")]),
            country("US"),
        ],
        keys=("AR", "NA", "US"),
    )
    assert plan(chain).ok
    cycle = build_snapshot(
        countries=[
            country("AR", status="inactive", replacement_country_ids=[country_id("NA")]),
            country("NA", status="inactive", replacement_country_ids=[country_id("US")]),
            country("US", status="inactive", replacement_country_ids=[country_id("AR")]),
        ],
        keys=("AR", "NA", "US"),
    )
    result = plan(cycle)
    assert rules(result) == {"RF-40"} and "ciclo" in messages(result)


def test_a_cycle_through_one_of_several_successors_is_rejected() -> None:
    document = build_snapshot(
        countries=[
            country(
                "AR",
                status="inactive",
                replacement_country_ids=[country_id("US"), country_id("NA")],
            ),
            country("NA", status="inactive", replacement_country_ids=[country_id("AR")]),
            country("US"),
        ],
        keys=("AR", "NA", "US"),
    )
    assert "ciclo" in messages(plan(document))


def test_reactivating_a_country_clears_every_successor() -> None:
    current = published(split_document(1, successors=["CW", "SX", "BQ"]))
    keys = (*ALL, "CW", "SX", "BQ")
    reactivated = build_snapshot(
        2,
        countries=[*(country(k) for k in keys), country("AN")],
        country_names=[*(n for k in keys for n in names(k)), *names("AN")],
        flags=[*(flag(k) for k in keys if k not in ("AQ", "BV")), flag("AN")],
        flag_exceptions=[flag_exception("AQ"), flag_exception("BV")],
    )
    result = plan(reactivated, current)
    assert result.ok, messages(result)
    (back,) = result.updated_countries
    assert (back.status, back.replacement_country_ids) == ("active", ())
