"""T5: semántica temporal pura de CountryCurrency (RF-44 a RF-49, RF-51)."""

from datetime import date

import pytest

from gi_common_reference.currencies.domain.model import CountryCurrencyRecord
from gi_common_reference.currencies.domain.temporal import (
    Period,
    extreme_change_allowed,
    history_order_key,
    history_violations,
    in_force_on,
    overlapping_pairs,
    period_of,
)
from tests.fixtures.temporal_vectors import CONTAINS_VECTORS, OVERLAP_VECTORS, Bound

D = date


def record(
    key: str,
    start: Bound = None,
    end: Bound = None,
    *,
    country: str = "c1",
    currency: str = "m1",
    status: str = "active",
) -> CountryCurrencyRecord:
    return CountryCurrencyRecord(key, country, currency, status, start, end)


@pytest.mark.parametrize(("a0", "a1", "b0", "b1", "expected"), OVERLAP_VECTORS)
def test_overlap_follows_the_half_open_semantics(
    a0: Bound, a1: Bound, b0: Bound, b1: Bound, expected: bool
) -> None:
    assert Period(a0, a1).overlaps(Period(b0, b1)) is expected
    assert Period(b0, b1).overlaps(Period(a0, a1)) is expected  # simétrica


@pytest.mark.parametrize(("start", "end", "day", "expected"), CONTAINS_VECTORS)
def test_contains_includes_the_start_and_excludes_the_end(
    start: Bound, end: Bound, day: date, expected: bool
) -> None:
    assert Period(start, end).contains(day) is expected


def test_a_same_day_transition_has_no_gap_and_no_overlap() -> None:
    """CL-20: HRK termina el 2023-01-01 y EUR empieza ese día."""
    hrk, eur = Period(D(1994, 5, 30), D(2023, 1, 1)), Period(D(2023, 1, 1), None)
    assert not hrk.overlaps(eur)
    assert hrk.contains(D(2022, 12, 31)) and not eur.contains(D(2022, 12, 31))
    assert not hrk.contains(D(2023, 1, 1)) and eur.contains(D(2023, 1, 1))
    for day in (D(2022, 12, 31), D(2023, 1, 1)):  # exactamente una de las dos, nunca ninguna
        assert hrk.contains(day) != eur.contains(day)


@pytest.mark.parametrize(
    ("start", "end", "ordered"),
    [
        (D(2020, 1, 1), D(2021, 1, 1), True),
        (D(2020, 1, 1), D(2020, 1, 1), False),
        (D(2021, 1, 1), D(2020, 1, 1), False),
        (None, D(2020, 1, 1), True),
        (D(2020, 1, 1), None, True),
        (None, None, True),
    ],
)
def test_the_start_must_precede_the_end_when_both_exist(
    start: Bound, end: Bound, ordered: bool
) -> None:
    assert Period(start, end).is_ordered is ordered


def test_a_period_without_end_is_open() -> None:
    assert Period(D(2020, 1, 1), None).is_open and not Period(None, D(2020, 1, 1)).is_open


# --- solapamiento entre registros (RF-45) --------------------------------------------------------


def test_only_active_records_of_the_same_pair_are_compared() -> None:
    same_pair = [record("a", D(2020, 1, 1)), record("b", D(2021, 1, 1))]
    assert len(overlapping_pairs(same_pair)) == 1
    other_currency = [record("a", D(2020, 1, 1)), record("b", D(2021, 1, 1), currency="m2")]
    assert overlapping_pairs(other_currency) == []  # monedas simultáneas (CL-21)
    other_country = [record("a", D(2020, 1, 1)), record("b", D(2021, 1, 1), country="c2")]
    assert overlapping_pairs(other_country) == []  # misma moneda en varios países
    retired = [record("a", D(2020, 1, 1)), record("b", D(2021, 1, 1), status="inactive")]
    assert overlapping_pairs(retired) == []  # los retirados no participan (CL-26)


def test_readoption_with_disjoint_periods_is_not_an_overlap() -> None:
    """CL-22."""
    rows = [
        record("a", None, D(2010, 1, 1)),
        record("b", D(2010, 1, 1), D(2015, 6, 1)),
        record("c", D(2020, 1, 1)),
    ]
    assert overlapping_pairs(rows) == []


def test_three_way_overlap_is_reported_pairwise() -> None:
    rows = [record("a"), record("b"), record("c")]
    assert len(overlapping_pairs(rows)) == 3


def test_a_malformed_period_is_not_reported_as_an_overlap() -> None:
    """Se informa por RF-44; no se duplica como solapamiento."""
    rows = [record("a", D(2021, 1, 1), D(2020, 1, 1)), record("b")]
    assert overlapping_pairs(rows) == []


# --- inmutabilidad de extremos (RF-46, RF-47)


@pytest.mark.parametrize(
    ("before", "after", "allowed"),
    [
        (None, None, True),
        (None, D(2023, 1, 1), True),  # completar un extremo ausente
        (D(2023, 1, 1), D(2023, 1, 1), True),
        (D(2023, 1, 1), D(2023, 6, 1), False),
        (D(2023, 1, 1), None, False),  # no se vacía ni se reabre
    ],
)
def test_an_extreme_can_be_completed_once_and_never_changed(
    before: Bound, after: Bound, allowed: bool
) -> None:
    assert extreme_change_allowed(before, after) is allowed


def test_history_violations_report_what_is_rewritten() -> None:
    before = record("a", D(2000, 1, 1), D(2023, 1, 1))
    assert history_violations(before, before) == []
    assert (
        history_violations(before, record("a", D(2000, 1, 1), D(2023, 1, 1), status="inactive"))
        == []
    )
    assert len(history_violations(before, record("a", D(2000, 1, 1), D(2024, 1, 1)))) == 1
    assert len(history_violations(before, record("a", D(2000, 1, 1), None))) == 1
    assert len(history_violations(before, record("a", D(1999, 1, 1), D(2023, 1, 1)))) == 1
    assert (
        len(history_violations(before, record("a", D(2000, 1, 1), D(2023, 1, 1), country="c2")))
        == 1
    )
    open_before = record("a", None, None)
    assert history_violations(open_before, record("a", D(2000, 1, 1), D(2023, 1, 1))) == []


# --- consulta por fecha e historial (RF-48, RF-49, RF-51)


def test_in_force_on_selects_active_records_whose_period_contains_the_day() -> None:
    rows = [
        record("hrk", D(1994, 5, 30), D(2023, 1, 1), currency="hrk"),
        record("eur", D(2023, 1, 1), currency="eur"),
        record("old", None, D(1990, 1, 1), currency="old"),
        record("gone", D(2000, 1, 1), currency="gone", status="inactive"),
    ]
    assert [r.currency_id for r in in_force_on(rows, D(2022, 12, 31))] == ["hrk"]
    assert [r.currency_id for r in in_force_on(rows, D(2023, 1, 1))] == ["eur"]
    assert [r.currency_id for r in in_force_on(rows, D(1980, 1, 1))] == ["old"]
    assert [r.currency_id for r in in_force_on(rows, D(2030, 1, 1), include_inactive=True)] == [
        "eur",
        "gone",
    ]


def test_a_date_before_every_association_returns_nothing() -> None:
    """CL-25."""
    assert in_force_on([record("a", D(2000, 1, 1))], D(1999, 12, 31)) == []
    assert in_force_on([], D(2026, 1, 1)) == []


def test_a_future_association_is_not_in_force_today_but_is_in_the_history() -> None:
    """CL-24."""
    future = record("f", D(2099, 1, 1))
    assert in_force_on([future], D(2026, 11, 1)) == []
    assert in_force_on([future], D(2099, 1, 1)) == [future]


def test_status_and_validity_are_independent() -> None:
    """RF-51: una cerrada sigue `active`; una `inactive` no se vuelve vigente por su período."""
    closed = record("c", D(2000, 1, 1), D(2001, 1, 1))
    assert closed.status == "active" and in_force_on([closed], D(2026, 1, 1)) == []
    retired = record("r", None, None, status="inactive")
    assert (
        period_of(retired).contains(D(2026, 1, 1)) and in_force_on([retired], D(2026, 1, 1)) == []
    )


def test_the_history_order_puts_missing_starts_first_then_by_start_and_id() -> None:
    rows = [
        record("c", D(2010, 1, 1)),
        record("b", D(2000, 1, 1)),
        record("z", None),
        record("a", D(2000, 1, 1)),
        record("y", None),
    ]
    assert [r.country_currency_id for r in sorted(rows, key=history_order_key)] == [
        "y",
        "z",
        "a",
        "b",
        "c",
    ]
