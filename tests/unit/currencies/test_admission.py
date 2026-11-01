"""T3: admisión del snapshot contra el historial (RF-39, RF-41): digest y reglas A/B/C/D."""

import copy
from typing import Any

import pytest

from gi_common_reference.currencies.domain.snapshot import (
    Classification,
    HistoricalSnapshot,
    evaluate_snapshot,
)
from tests.fixtures.currencies import build_snapshot, seal


def history(*snapshots: dict[str, Any]) -> list[HistoricalSnapshot]:
    return [HistoricalSnapshot(s["snapshot_version"], s["content_digest"]) for s in snapshots]


def test_the_first_snapshot_proceeds_without_history() -> None:
    decision = evaluate_snapshot(build_snapshot(1), [])
    assert decision.classification is Classification.D
    assert decision.proceeds and not decision.rejected and not decision.is_noop


@pytest.mark.parametrize("version", [1, 2, 5, 1000])
def test_any_positive_first_version_is_accepted_gaps_included(version: int) -> None:
    assert evaluate_snapshot(build_snapshot(version), []).proceeds


def test_a_higher_version_is_applied_even_with_gaps() -> None:
    applied = build_snapshot(1)
    decision = evaluate_snapshot(build_snapshot(7), history(applied))
    assert decision.classification is Classification.D and decision.proceeds


def test_the_same_version_and_digest_is_a_noop() -> None:
    applied = build_snapshot(3)
    decision = evaluate_snapshot(copy.deepcopy(applied), history(applied))
    assert decision.classification is Classification.A
    assert decision.is_noop and not decision.rejected and not decision.proceeds


def test_the_same_version_with_another_digest_is_rejected() -> None:
    applied = build_snapshot(3)
    other = build_snapshot(3, codes=("ARS", "USD"))
    assert applied["content_digest"] != other["content_digest"]
    decision = evaluate_snapshot(other, history(applied))
    assert decision.classification is Classification.B
    assert decision.rejected
    assert {v.rule for v in decision.violations} == {"RF-39"}


def test_a_lower_version_not_applied_is_a_regression() -> None:
    decision = evaluate_snapshot(build_snapshot(2), history(build_snapshot(1), build_snapshot(5)))
    assert decision.classification is Classification.C
    assert decision.rejected
    assert {v.rule for v in decision.violations} == {"RF-39"}
    assert "anterior" in decision.violations[0].message


def test_a_lower_version_that_was_applied_with_the_same_digest_is_still_a_noop() -> None:
    """Regla A antes que C: reenviar un snapshot histórico idéntico no es una regresión."""
    old = build_snapshot(1)
    decision = evaluate_snapshot(old, history(old, build_snapshot(5)))
    assert decision.is_noop


def test_a_tampered_digest_is_rejected_before_any_classification() -> None:
    applied = build_snapshot(1)
    tampered = copy.deepcopy(build_snapshot(2))
    tampered["currencies"][0]["minor_units"] = 9
    decision = evaluate_snapshot(tampered, history(applied))
    assert decision.classification is None and decision.rejected
    assert {v.rule for v in decision.violations} == {"RF-41"}
    # incluso con la versión ya incorporada: el digest se verifica primero
    decision = evaluate_snapshot({**tampered, "snapshot_version": 1}, history(applied))
    assert {v.rule for v in decision.violations} == {"RF-41"}


def test_the_digest_is_recomputed_never_trusted() -> None:
    document = build_snapshot(2)
    document["content_digest"] = "sha256:" + "a" * 64
    assert evaluate_snapshot(document, []).rejected
    assert evaluate_snapshot(seal(document), []).proceeds


def test_a_noop_does_not_depend_on_the_rest_of_the_history() -> None:
    first, second = build_snapshot(1), build_snapshot(2, codes=("ARS",))
    assert evaluate_snapshot(second, history(first, second)).is_noop
