"""T5: CountryCurrency temporal en el plan de cambios."""

from datetime import date
from typing import Any

import pytest

from gi_common_reference.currencies.domain.model import CatalogState
from tests.fixtures.currencies import (
    DEFAULT_ASSOCIATIONS,
    association,
    association_id,
    build_snapshot,
    country_catalog,
    country_id,
    currency,
    currency_id,
    provenance,
)
from tests.fixtures.temporal_vectors import Bound
from tests.unit.currencies.helpers import messages, plan, published, rules

D = date


def snapshot(
    associations: list[dict[str, Any]],
    *,
    version: int = 1,
    codes: tuple[str, ...] = ("ARS", "USD", "EUR", "PAB", "HRK"),
    currencies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return build_snapshot(
        version, codes=codes, currencies=currencies, country_currencies=associations
    )


# --- cardinalidad N:N sin unicidad por país (RF-18, CL-4 a CL-7)


def test_a_country_without_currency_is_valid() -> None:
    """CL-6: AQ no tiene asociaciones y existe en el catálogo de Countries."""
    result = plan(snapshot([association("AR", "ARS")]))
    assert result.ok, messages(result)
    assert all(a.country_id != country_id("AQ") for a in result.new_associations)


def test_a_currency_without_country_is_valid() -> None:
    """CL-7: XDR, XAU."""
    result = plan(build_snapshot(codes=("XDR", "XAU"), country_currencies=[]))
    assert result.ok and not result.new_associations


def test_several_simultaneous_currencies_in_one_country_are_accepted() -> None:
    """CL-5, CL-21: PA con PAB y USD; BO con BOB y BOV; ninguna es principal."""
    rows = [
        association("PA", "PAB", D(1904, 1, 1)),
        association("PA", "USD", D(1904, 1, 1)),
        association("PA", "EUR", D(1904, 1, 1)),
    ]
    result = plan(snapshot(rows))
    assert result.ok, messages(result)
    assert len(result.new_associations) == 3


def test_one_currency_in_many_countries_is_accepted() -> None:
    """CL-4."""
    rows = [association(c, "EUR", D(1999, 1, 1)) for c in ("DE", "FR", "HR")]
    assert plan(snapshot(rows)).ok


def test_the_default_snapshot_associations_are_all_planned() -> None:
    result = plan(build_snapshot())
    assert result.ok, messages(result)
    assert len(result.new_associations) == len(DEFAULT_ASSOCIATIONS)


# --- vigencia: orden y formato (RF-44)


@pytest.mark.parametrize(
    ("start", "end"),
    [(D(2023, 1, 1), D(2023, 1, 1)), (D(2024, 1, 1), D(2023, 1, 1))],
)
def test_start_not_before_end_is_rejected(start: date, end: date) -> None:
    result = plan(snapshot([association("HR", "HRK", start, end)]))
    assert rules(result) == {"RF-44"}


@pytest.mark.parametrize(
    "text", ["2023-02-30", "2023-13-01", "2023-00-10", "2023-04-31", "0000-01-01"]
)
def test_a_date_that_is_not_a_real_day_is_rejected(text: str) -> None:
    row = association("HR", "HRK", valid_from=None)
    row["valid_from"] = text
    result = plan(snapshot([row]))
    assert rules(result) == {"RF-44"} and text in messages(result)


@pytest.mark.parametrize("text", ["2023-W01-1", "20230101", "2023-1-1", "2023-01-01T00:00"])
def test_other_iso_forms_are_not_accepted_as_a_calendar_day(text: str) -> None:
    row = association("HR", "HRK")
    row["valid_to"] = text
    assert rules(plan(snapshot([row]))) == {"RF-44"}


def test_missing_extremes_mean_unbounded_and_are_valid() -> None:
    """CL-23."""
    rows = [
        association("AR", "ARS"),
        association("HR", "HRK", None, D(2023, 1, 1)),
        association("PA", "USD", D(1904, 1, 1), None),
    ]
    assert plan(snapshot(rows)).ok


# --- solapamiento (RF-45)


def test_active_periods_of_the_same_pair_that_overlap_are_rejected() -> None:
    rows = [
        association("HR", "EUR", D(2023, 1, 1), n=1),
        association("HR", "EUR", D(2025, 1, 1), n=2),
    ]
    result = plan(snapshot(rows))
    assert rules(result) == {"RF-45"} and "se solapan" in messages(result)


def test_adjacent_periods_and_readoption_of_the_same_pair_are_accepted() -> None:
    """CL-22."""
    rows = [
        association("HR", "EUR", None, D(2010, 1, 1), n=1),
        association("HR", "EUR", D(2010, 1, 1), D(2015, 6, 1), n=2),
        association("HR", "EUR", D(2020, 1, 1), n=3),
    ]
    assert plan(snapshot(rows)).ok


def test_the_same_day_transition_between_two_currencies_is_accepted() -> None:
    """CL-20, CA-18: HRK hasta 2023-01-01 (excluido), EUR desde 2023-01-01."""
    rows = [
        association("HR", "HRK", D(1994, 5, 30), D(2023, 1, 1)),
        association("HR", "EUR", D(2023, 1, 1)),
    ]
    assert plan(snapshot(rows)).ok


def test_an_inactive_record_may_overlap_its_correction() -> None:
    """CL-26: el registro erróneo se retira y se publica uno nuevo."""
    wrong = association("HR", "EUR", D(2023, 1, 1), D(2024, 1, 1), n=1, status="inactive")
    right = association("HR", "EUR", D(2023, 1, 1), n=2)
    assert plan(snapshot([wrong, right])).ok


# --- referencias (RF-17, RF-40)


def test_an_unknown_country_is_rejected_not_resolved_silently() -> None:
    result = plan(snapshot([association("AR", "ARS")]), countries=country_catalog(missing=["AR"]))
    assert rules(result) == {"RF-40"}


def test_an_unknown_currency_or_a_malformed_id_is_rejected() -> None:
    ghost = association("AR", "ARS", currency_id="00000000-0000-4000-8000-000000000000")
    assert "RF-17" in rules(plan(snapshot([ghost])))
    bad = association("AR", "ARS", country_currency_id="nope")
    assert "RF-17" in rules(plan(snapshot([bad])))


def test_a_repeated_association_id_is_rejected() -> None:
    first = association("AR", "ARS")
    second = association("US", "USD", country_currency_id=first["country_currency_id"])
    assert "RF-17" in rules(plan(snapshot([first, second])))


def test_an_invalid_association_status_is_rejected() -> None:
    for status in ("retired", "vigente", "not_found", ""):
        assert "RF-9" in rules(plan(snapshot([association("AR", "ARS", status=status)])))


# --- RF-19 / RF-38: vigencia abierta sobre entidades inactive


def test_an_open_active_association_over_an_inactive_country_is_rejected() -> None:
    result = plan(snapshot([association("AR", "ARS")]), countries=country_catalog(inactive=["AR"]))
    assert rules(result) == {"RF-19"} and "Country inactive" in messages(result)


def test_a_closed_association_over_an_inactive_country_is_history_and_is_accepted() -> None:
    """CL-13, CL-27."""
    closed = association("AR", "ARS", None, D(2023, 1, 1))
    assert plan(snapshot([closed]), countries=country_catalog(inactive=["AR"])).ok


def test_an_open_active_association_over_an_inactive_currency_is_rejected() -> None:
    retired = currency("HRK", status="inactive")
    result = plan(
        snapshot([association("HR", "HRK", D(1994, 5, 30))], codes=("HRK",), currencies=[retired])
    )
    assert rules(result) == {"RF-19"} and "RF-38" in messages(result)


def test_retiring_a_currency_requires_closing_its_associations_and_keeps_them_active() -> None:
    """CL-8, CA-9, RF-38: HRK pasa a inactive; HR–HRK queda `active` y cerrada; HR–EUR abre."""
    before = snapshot([association("HR", "HRK", D(1994, 5, 30))], codes=("HRK", "EUR"), version=1)
    eur = currency("EUR")
    hrk = currency("HRK", status="inactive", replacement_currency_ids=[eur["currency_id"]])
    after = snapshot(
        [
            association("HR", "HRK", D(1994, 5, 30), D(2023, 1, 1)),
            association("HR", "EUR", D(2023, 1, 1)),
        ],
        version=2,
        codes=("HRK", "EUR"),
        currencies=[hrk, eur],
    )
    result = plan(after, published(before))
    assert result.ok, messages(result)
    assert [(a.currency_id, a.status, a.valid_to) for a in result.updated_associations] == [
        (currency_id("HRK"), "active", D(2023, 1, 1))
    ]
    assert [(a.currency_id, a.valid_from) for a in result.new_associations] == [
        (currency_id("EUR"), D(2023, 1, 1))
    ]
    assert [c.alphabetic_code for c in result.updated_currencies] == ["HRK"]


def test_retiring_a_currency_without_closing_the_association_is_rejected() -> None:
    before = snapshot([association("HR", "HRK", D(1994, 5, 30))], codes=("HRK", "EUR"))
    eur = currency("EUR")
    hrk = currency("HRK", status="inactive", replacement_currency_ids=[eur["currency_id"]])
    after = snapshot(
        [association("HR", "HRK", D(1994, 5, 30))],
        version=2,
        codes=("HRK", "EUR"),
        currencies=[hrk, eur],
    )
    assert rules(plan(after, published(before))) == {"RF-19"}


# --- historia inmutable (RF-7, RF-37, RF-46, RF-47)


def closed_state() -> tuple[dict[str, Any], CatalogState]:
    document = snapshot(
        [
            association("HR", "HRK", D(1994, 5, 30), D(2023, 1, 1)),
            association("HR", "EUR", D(2023, 1, 1)),
        ],
        codes=("HRK", "EUR"),
        currencies=[
            currency("HRK", status="inactive", replacement_currency_ids=[currency_id("EUR")]),
            currency("EUR"),
        ],
    )
    return document, published(document)


def test_resubmitting_a_closed_history_changes_nothing() -> None:
    document, state = closed_state()
    assert plan(document, state).is_empty


def test_closing_an_open_period_is_allowed_once() -> None:
    """RF-46: cerrar una vigencia abierta."""
    before = snapshot([association("PA", "USD", D(1904, 1, 1))], codes=("USD",))
    after = snapshot(
        [association("PA", "USD", D(1904, 1, 1), D(2030, 1, 1))], codes=("USD",), version=2
    )
    result = plan(after, published(before))
    assert result.ok, messages(result)
    assert [a.valid_to for a in result.updated_associations] == [D(2030, 1, 1)]


def test_completing_a_missing_start_is_allowed_once() -> None:
    before = snapshot([association("AR", "ARS")], codes=("ARS",))
    after = snapshot([association("AR", "ARS", D(1992, 1, 1))], codes=("ARS",), version=2)
    assert plan(after, published(before)).ok


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (D(1994, 5, 30), D(2023, 6, 1)),  # modificar el fin
        (D(1994, 5, 30), None),  # reabrir
        (D(1990, 1, 1), D(2023, 1, 1)),  # modificar el inicio
        (None, D(2023, 1, 1)),  # vaciar el inicio
    ],
)
def test_a_published_closed_period_cannot_be_modified_or_reopened(start: Bound, end: Bound) -> None:
    document, state = closed_state()
    changed = snapshot(
        [association("HR", "HRK", start, end), association("HR", "EUR", D(2023, 1, 1))],
        version=2,
        codes=("HRK", "EUR"),
        currencies=document["currencies"],
    )
    result = plan(changed, state)
    assert "RF-47" in rules(result)


def test_correcting_a_published_period_is_retiring_it_and_publishing_a_new_record() -> None:
    """CL-26, CA-19."""
    document, state = closed_state()
    corrected = snapshot(
        [
            association("HR", "HRK", D(1994, 5, 30), D(2023, 1, 1), status="inactive"),
            association("HR", "HRK", D(1994, 5, 30), D(2022, 12, 31), n=2),
            association("HR", "EUR", D(2023, 1, 1)),
        ],
        version=2,
        codes=("HRK", "EUR"),
        currencies=document["currencies"],
    )
    result = plan(corrected, state)
    assert result.ok, messages(result)
    assert [a.status for a in result.updated_associations] == ["inactive"]
    assert [a.country_currency_id for a in result.new_associations] == [
        association_id("HR", "HRK", 2)
    ]


def test_changing_the_country_or_currency_of_a_published_association_is_rejected() -> None:
    document, state = closed_state()
    moved = association("HR", "HRK", D(1994, 5, 30), D(2023, 1, 1), country_id=country_id("AR"))
    changed = snapshot(
        [moved, association("HR", "EUR", D(2023, 1, 1))],
        version=2,
        codes=("HRK", "EUR"),
        currencies=document["currencies"],
    )
    assert "RF-47" in rules(plan(changed, state))


def test_omitting_a_published_association_is_rejected_even_if_it_is_history() -> None:
    document, state = closed_state()
    omitted = snapshot(
        [association("HR", "EUR", D(2023, 1, 1))],
        version=2,
        codes=("HRK", "EUR"),
        currencies=document["currencies"],
    )
    result = plan(omitted, state)
    assert rules(result) == {"RF-37"} and "cierre de su vigencia" in messages(result)


def test_status_never_changes_by_itself_nor_follows_the_validity() -> None:
    """RF-51, CL-28: el plan no toca `status` de una asociación solo porque su vigencia terminó."""
    document, state = closed_state()
    assert {a.status for a in state.associations} == {"active"}
    result = plan(document, state)
    assert result.is_empty and not result.updated_associations


def test_retiring_a_record_keeps_its_validity() -> None:
    before = snapshot([association("AR", "ARS", D(1992, 1, 1))], codes=("ARS",))
    after = snapshot(
        [association("AR", "ARS", D(1992, 1, 1), status="inactive")], codes=("ARS",), version=2
    )
    result = plan(after, published(before))
    assert result.ok, messages(result)
    assert [(a.status, a.valid_from) for a in result.updated_associations] == [
        ("inactive", D(1992, 1, 1))
    ]


# --- procedencia de la vigencia (D-20, RF-52)


def test_country_currency_and_validity_sources_are_required_when_used() -> None:
    base = provenance()
    only_identity = {
        **base,
        "sources": [s for s in base["sources"] if s["role"] in ("identity", "names")],
    }
    with_dates = build_snapshot(catalog_provenance=only_identity)
    result = plan(with_dates)
    assert rules(result) == {"RF-41"}
    assert "country_currency" in messages(result) and "validity" in messages(result)


def test_validity_source_is_not_required_when_no_association_declares_a_date() -> None:
    base = provenance()
    sources = [s for s in base["sources"] if s["role"] != "validity"]
    document = build_snapshot(
        codes=("ARS",),
        country_currencies=[association("AR", "ARS")],
        catalog_provenance={**base, "sources": sources},
    )
    assert plan(document).ok


def test_a_validity_conflict_between_sources_rejects_the_snapshot() -> None:
    conflicted = provenance(
        unresolved_conflicts=[{"what": "CLDR e ISO difieren en el fin de HRK en HR"}]
    )
    assert rules(plan(build_snapshot(catalog_provenance=conflicted))) == {"RF-41"}


def test_no_primary_currency_or_extra_attributes_exist_on_the_record() -> None:
    """D-10: sin moneda principal ni otros atributos en v1."""
    from gi_common_reference.currencies.domain.model import CountryCurrencyRecord

    assert set(CountryCurrencyRecord.__dataclass_fields__) == {
        "country_currency_id",
        "country_id",
        "currency_id",
        "status",
        "valid_from",
        "valid_to",
    }
