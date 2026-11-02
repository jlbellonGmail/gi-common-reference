"""T6: incorporación transaccional de Currency (RF-36 a RF-41, D16, D17, D22)."""

import copy
from datetime import date
from typing import Any

import pytest

from gi_common_reference.currencies.application.diff import check_integrity, preview_snapshot
from gi_common_reference.currencies.application.incorporate import (
    Outcome,
    incorporate_snapshot,
)
from gi_common_reference.currencies.domain.errors import ConstraintRejected
from tests.fixtures.currencies import (
    EN,
    POLICY,
    association,
    build_snapshot,
    country_catalog,
    country_id,
    currency,
    currency_id,
    names,
)
from tests.fixtures.currency_fakes import FakeCurrencyRepository

D = date
WRITE_ORDER = [
    "insert_snapshot",
    "insert_currencies",
    "update_currencies",
    "insert_names",
    "update_names",
    "insert_associations",
    "update_associations",
    "touch_currencies",
    "check_constraints",
]


def run(document: dict[str, Any], repository: FakeCurrencyRepository) -> Any:
    return incorporate_snapshot(document, repository, POLICY)


def dump(repository: FakeCurrencyRepository) -> Any:
    return copy.deepcopy(repository.state)


# --- primer snapshot, no-op e idempotencia


def test_the_first_snapshot_is_incorporated_and_registers_every_version() -> None:
    repository = FakeCurrencyRepository()
    result = run(build_snapshot(1), repository)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.new_currencies, result.new_associations, result.names) == (15, 15, 30)
    assert (result.locale_snapshot_version, result.country_snapshot_version) == (1, 1)
    stored = repository.state.snapshots[0]
    assert stored["_locale_snapshot_version"] == 1
    assert stored["_country_current_snapshot_version"] == 1
    assert stored["_policy_version"] == POLICY.version
    ids = repository.state.versions
    assert all(first == last == 1 for first, last in ids.values())


def test_the_writes_follow_the_planned_order_and_end_with_the_constraint_check() -> None:
    repository = FakeCurrencyRepository()
    run(build_snapshot(1), repository)
    assert repository.calls == WRITE_ORDER


def test_resubmitting_the_same_snapshot_is_a_noop_that_changes_nothing() -> None:
    repository = FakeCurrencyRepository()
    document = build_snapshot(1)
    run(document, repository)
    before, calls = dump(repository), len(repository.calls)
    again = run(copy.deepcopy(document), repository)
    assert again.outcome is Outcome.NOOP and not again.violations
    assert dump(repository) == before and len(repository.calls) == calls


def test_a_higher_version_with_no_changes_registers_the_snapshot_but_no_rows() -> None:
    repository = FakeCurrencyRepository()
    run(build_snapshot(1), repository)
    result = run(build_snapshot(5), repository)
    assert result.outcome is Outcome.INCORPORATED
    assert (result.new_currencies, result.updated_currencies, result.names) == (0, 0, 0)
    assert [s["snapshot_version"] for s in repository.state.snapshots] == [1, 5]
    assert all(last == 1 for _, last in repository.state.versions.values())


# --- rechazos sin escrituras


def rejected_without_writes(
    document: dict[str, Any], repository: FakeCurrencyRepository, rule: str
) -> None:
    before, calls = dump(repository), len(repository.calls)
    result = run(document, repository)
    assert result.outcome is Outcome.REJECTED
    assert rule in {v.rule for v in result.violations}, result.violations
    assert dump(repository) == before
    assert not {"insert_snapshot", "insert_currencies"} & set(repository.calls[calls:])


def test_the_same_version_with_another_digest_is_rejected() -> None:
    repository = FakeCurrencyRepository()
    run(build_snapshot(1), repository)
    rejected_without_writes(build_snapshot(1, codes=("ARS",)), repository, "RF-39")


def test_a_lower_version_not_applied_is_rejected_as_a_regression() -> None:
    repository = FakeCurrencyRepository()
    run(build_snapshot(5), repository)
    rejected_without_writes(build_snapshot(3), repository, "RF-39")


def test_a_tampered_digest_is_rejected() -> None:
    repository = FakeCurrencyRepository()
    document = build_snapshot(1)
    document["currencies"][0]["minor_units"] = 9
    rejected_without_writes(document, repository, "RF-41")


def test_a_missing_currency_id_is_rejected() -> None:
    document = build_snapshot(1)
    del document["currencies"][0]["currency_id"]
    from tests.fixtures.currencies import seal

    rejected_without_writes(seal(document), FakeCurrencyRepository(), "RF-2")


def test_an_unknown_country_is_rejected_and_nothing_is_written() -> None:
    repository = FakeCurrencyRepository(countries=country_catalog(missing=["AR"]))
    rejected_without_writes(build_snapshot(1), repository, "RF-40")


def test_missing_required_locale_names_are_rejected() -> None:
    kept = [n for n in names("ARS") if n["locale_id"] == EN]
    document = build_snapshot(1, codes=("ARS",), currency_names=kept, country_currencies=[])
    rejected_without_writes(document, FakeCurrencyRepository(), "RF-13")


def test_an_unresolved_source_conflict_is_rejected() -> None:
    from tests.fixtures.currencies import provenance

    conflicted = provenance(unresolved_conflicts=["nombre ISO ≠ CLDR"])
    rejected_without_writes(
        build_snapshot(1, catalog_provenance=conflicted), FakeCurrencyRepository(), "RF-41"
    )


# --- atomicidad


@pytest.mark.parametrize("step", WRITE_ORDER[:-1])
def test_a_failure_at_any_write_step_leaves_the_catalog_untouched(step: str) -> None:
    """RF-39: todo o nada dentro del catálogo Currency."""
    repository = FakeCurrencyRepository()
    run(build_snapshot(1), repository)
    before = dump(repository)
    repository.fail_at = step
    retired = currency("HRK", status="inactive")
    document = build_snapshot(
        2,
        currencies=[currency(c) for c in ("ARS", "USD", "EUR", "PAB", "JPY", "KWD", "CLF", "XAU")]
        + [currency(c) for c in ("XDR", "BOB", "BOV", "CHF", "CHE", "CHW")]
        + [retired],
        currency_names=[n for c in _codes() for n in names(c)],
        country_currencies=[association(a, c, f, t) for a, c, f, t in _associations() if c != "HRK"]
        + [association("HR", "HRK", D(1994, 5, 30), D(2023, 1, 1))],
    )
    if step in ("update_names", "touch_currencies"):
        # fuerza que el paso exista: cambia un nombre publicado
        for n in document["currency_names"]:
            if n["currency_id"] == currency_id("ARS") and n["locale_id"] == EN:
                n["name"] = "Peso"
        from tests.fixtures.currencies import seal

        document = seal(document)
    with pytest.raises(RuntimeError):
        run(document, repository)
    assert dump(repository) == before


def _codes() -> tuple[str, ...]:
    return (
        "ARS", "USD", "EUR", "PAB", "JPY", "KWD", "CLF", "XAU", "XDR", "BOB", "BOV", "CHF", "CHE",
        "CHW", "HRK",
    )  # fmt: skip


def _associations() -> Any:
    from tests.fixtures.currencies import DEFAULT_ASSOCIATIONS

    return DEFAULT_ASSOCIATIONS


def test_a_constraint_rejected_at_the_end_is_a_rejection_naming_the_requirement() -> None:
    cases = {
        "country_currency_active_no_overlap": "RF-45",
        "currency_replacement_acyclic": "RF-6",
        "country_currency_open_requires_active_targets": "RF-19",
        "currency_numeric_code_active_unique": "RF-3",
        "some_unknown_constraint": "RNF-5",
        None: "RNF-5",
    }
    for constraint, rule in cases.items():
        repository = FakeCurrencyRepository()
        repository.constraint_failure = ConstraintRejected(constraint, "23P01")
        result = run(build_snapshot(1), repository)
        assert result.outcome is Outcome.REJECTED
        assert [v.rule for v in result.violations] == [rule]
        assert repository.state.snapshots == []  # la fake descarta lo escrito al propagarse


# --- ciclo de vida: retiro, transición, división, reactivación


def seeded() -> FakeCurrencyRepository:
    repository = FakeCurrencyRepository()
    assert run(build_snapshot(1), repository).outcome is Outcome.INCORPORATED
    return repository


def test_hrk_to_eur_keeps_the_id_closes_the_period_and_opens_the_new_one() -> None:
    """CA-9, CL-8: HRK queda inactive con reemplazo EUR; HR–HRK active y cerrada; HR–EUR abierta."""
    repository = seeded()
    base = repository.state
    eur = base.currencies[currency_id("EUR")]
    hrk_retired = currency("HRK", status="inactive", replacement_currency_ids=[eur.currency_id])
    codes = [c for c in _codes() if c != "HRK"]
    associations = [association(a, c, f, t) for a, c, f, t in _associations() if c != "HRK"] + [
        association("HR", "HRK", D(1994, 5, 30), D(2023, 1, 1)),
        association("HR", "EUR", D(2023, 1, 1), n=2),
    ]
    document = build_snapshot(
        2,
        currencies=[currency(c) for c in codes] + [hrk_retired],
        currency_names=[n for c in _codes() for n in names(c)],
        country_currencies=associations,
    )
    result = run(document, repository)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.new_currencies, result.updated_currencies) == (0, 1)
    assert (result.new_associations, result.updated_associations) == (1, 1)
    state = repository.state
    hrk = state.currencies[currency_id("HRK")]
    assert (hrk.status, hrk.replacement_currency_ids) == ("inactive", (currency_id("EUR"),))
    closed = state.associations[document["country_currencies"][-2]["country_currency_id"]]
    assert (closed.status, closed.valid_to) == ("active", D(2023, 1, 1))
    assert state.versions[currency_id("HRK")] == [1, 2]
    assert state.versions[currency_id("ARS")] == [1, 1]


def test_retiring_a_currency_without_closing_its_association_is_rejected() -> None:
    repository = seeded()
    document = build_snapshot(
        2,
        currencies=[currency(c) for c in _codes() if c != "HRK"]
        + [currency("HRK", status="inactive")],
        currency_names=[n for c in _codes() for n in names(c)],
    )
    before = dump(repository)
    result = run(document, repository)
    assert result.outcome is Outcome.REJECTED and {v.rule for v in result.violations} == {"RF-19"}
    assert dump(repository) == before


def test_a_division_creates_a_currency_with_many_replacements() -> None:
    """CL-18 (CSK → CZK y SKK)."""
    repository = FakeCurrencyRepository()
    run(build_snapshot(1, codes=("CSK", "CZK", "SKK"), country_currencies=[]), repository)
    csk = currency(
        "CSK",
        status="inactive",
        replacement_currency_ids=[currency_id("CZK"), currency_id("SKK")],
    )
    result = run(
        build_snapshot(
            2,
            currencies=[csk, currency("CZK"), currency("SKK")],
            currency_names=[n for c in ("CSK", "CZK", "SKK") for n in names(c)],
            country_currencies=[],
        ),
        repository,
    )
    assert result.outcome is Outcome.INCORPORATED, result.violations
    stored = repository.state.currencies[currency_id("CSK")]
    assert stored.replacement_currency_ids == tuple(
        sorted([currency_id("CZK"), currency_id("SKK")])
    )


def test_a_reactivation_clears_the_replacements() -> None:
    """CL-19."""
    repository = FakeCurrencyRepository()
    retired = currency("HRK", status="inactive", replacement_currency_ids=[currency_id("EUR")])
    first = build_snapshot(
        1,
        currencies=[retired, currency("EUR")],
        currency_names=[n for c in ("HRK", "EUR") for n in names(c)],
        country_currencies=[],
    )
    run(first, repository)
    second = build_snapshot(
        2,
        currencies=[currency("HRK"), currency("EUR")],
        currency_names=[n for c in ("HRK", "EUR") for n in names(c)],
        country_currencies=[],
    )
    assert run(second, repository).outcome is Outcome.INCORPORATED
    assert repository.state.currencies[currency_id("HRK")].replacement_currency_ids == ()


def test_a_later_list_three_currency_is_added_inactive_with_a_new_id() -> None:
    """CA-15, RF-43."""
    repository = seeded()
    before_ids = set(repository.state.currencies)
    old = currency("YUM", status="inactive")
    document = build_snapshot(
        2,
        currencies=[*(currency(c) for c in _codes()), old],
        currency_names=[n for c in (*_codes(), "YUM") for n in names(c)],
    )
    result = run(document, repository)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert set(repository.state.currencies) - before_ids == {currency_id("YUM")}
    assert repository.state.currencies[currency_id("YUM")].status == "inactive"
    assert all(repository.state.versions[i] == [1, 1] for i in before_ids)


def test_a_name_change_touches_the_currency_version_without_changing_the_row() -> None:
    repository = seeded()
    renamed = copy.deepcopy(build_snapshot(1))
    for n in renamed["currency_names"]:
        if n["currency_id"] == currency_id("ARS") and n["locale_id"] == EN:
            n["name"] = "Peso"
    from tests.fixtures.currencies import seal

    result = run(seal({**renamed, "snapshot_version": 2}), repository)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert result.names == 1 and result.updated_currencies == 0
    assert repository.state.versions[currency_id("ARS")] == [1, 2]
    assert repository.state.versions[currency_id("USD")] == [1, 1]


# --- diff e integridad


def test_diff_reads_without_writing_and_matches_what_incorporation_would_do() -> None:
    repository = seeded()
    before, calls = dump(repository), len(repository.calls)
    eur = currency("EUR")
    hrk = currency("HRK", status="inactive", replacement_currency_ids=[eur["currency_id"]])
    document = build_snapshot(
        2,
        currencies=[currency(c) for c in _codes() if c != "HRK"] + [hrk],
        currency_names=[n for c in _codes() for n in names(c)],
        country_currencies=[association(a, c, f, t) for a, c, f, t in _associations() if c != "HRK"]
        + [association("HR", "HRK", D(1994, 5, 30), D(2023, 1, 1))],
    )
    preview = preview_snapshot(document, repository, POLICY)
    assert preview.outcome is Outcome.INCORPORATED and preview.diff is not None
    text = "\n".join(preview.diff.lines())
    assert "estado" in text and "inactive" in text and "reemplazos" in text and "vigencia" in text
    assert dump(repository) == before and len(repository.calls) == calls
    assert repository.transactions == 1 and repository.inspections == 1


def test_diff_reports_noop_and_violations() -> None:
    repository = seeded()
    assert preview_snapshot(build_snapshot(1), repository, POLICY).outcome is Outcome.NOOP
    bad = preview_snapshot(build_snapshot(0 + 1, codes=("ARS",)), repository, POLICY)
    assert bad.outcome is Outcome.REJECTED


def test_check_integrity_detects_the_drift_left_by_a_country_retirement() -> None:
    """S-8: 003 retira un país sin conocer Currency; queda visible y se corrige hacia adelante."""
    repository = seeded()
    assert check_integrity(repository) == ()
    repository.countries = country_catalog(inactive=["AR"])
    found = check_integrity(repository)
    assert [(v.country_id, v.country_not_active, v.currency_not_active) for v in found] == [
        (country_id("AR"), True, False)
    ]
    # la siguiente incorporación exige la corrección (cerrar la vigencia)
    stale = build_snapshot(2)
    result = run(stale, repository)
    assert result.outcome is Outcome.REJECTED and {v.rule for v in result.violations} == {"RF-19"}
    fixed = build_snapshot(
        2,
        country_currencies=[
            association(a, c, f, D(2026, 1, 1) if a == "AR" else t)
            for a, c, f, t in _associations()
        ],
    )
    assert run(fixed, repository).outcome is Outcome.INCORPORATED
