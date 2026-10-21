"""T5: clasificación A/B/C/D contra el historial y precedencia de validaciones
(RF-21, RF-29, RF-30, RF-31, RF-32)."""

from datetime import date
from typing import Any

import pytest

from gi_common_reference.locales.domain.snapshot import (
    Classification,
    HistoricalSnapshot,
    SnapshotDecision,
    evaluate_snapshot,
)
from tests.fixtures.snapshots import (
    build_snapshot,
    history_of,
    registry_text,
    seal,
)

A, B, C, D = Classification.A, Classification.B, Classification.C, Classification.D


def rules(decision: SnapshotDecision) -> set[str]:
    return {v.rule for v in decision.violations}


def sealed(document: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return seal({**document, **changes})


# --- clasificación (RF-32) ---------------------------------------------------------------------


@pytest.mark.parametrize("version", [1, 7, 10, 10**12])
def test_first_snapshot_is_case_d_with_any_valid_version(version: int) -> None:
    decision = evaluate_snapshot(build_snapshot(version), [])
    assert decision.classification is D
    assert decision.violations == ()
    assert decision.proceeds and not decision.is_noop and not decision.rejected


def test_resubmitting_the_last_snapshot_is_case_a() -> None:
    snapshot = build_snapshot(3)
    decision = evaluate_snapshot(snapshot, [history_of(snapshot)])
    assert decision.classification is A
    assert decision.is_noop and not decision.rejected and not decision.proceeds


def test_n_resubmitted_after_n_plus_one_is_case_a_noop() -> None:
    first = build_snapshot(5, file_date="2026-08-01")
    second = build_snapshot(6, file_date="2026-09-01")
    decision = evaluate_snapshot(first, [history_of(first), history_of(second)])
    assert decision.classification is A
    assert decision.is_noop and decision.violations == ()


def test_case_a_does_not_apply_the_file_date_rule_even_if_older_than_the_last() -> None:
    first = build_snapshot(5, file_date="2026-01-01")
    second = build_snapshot(6, file_date="2026-09-01")
    decision = evaluate_snapshot(first, [history_of(second), history_of(first)])
    assert decision.is_noop and decision.violations == ()


def test_same_version_with_other_digest_is_case_b() -> None:
    original = build_snapshot(4)
    other = build_snapshot(4, codes=("es", "en", "pt"))
    decision = evaluate_snapshot(other, [history_of(original)])
    assert decision.classification is B
    assert rules(decision) == {"RF-32"}
    assert decision.rejected and not decision.proceeds


def test_case_b_applies_to_any_incorporated_version_not_only_the_last() -> None:
    old, new = build_snapshot(4), build_snapshot(5)
    other = build_snapshot(4, codes=("es", "en", "pt"))
    decision = evaluate_snapshot(other, [history_of(old), history_of(new)])
    assert decision.classification is B


def test_new_version_older_than_the_last_is_case_c() -> None:
    ten, twelve = build_snapshot(10), build_snapshot(12)
    decision = evaluate_snapshot(build_snapshot(11), [history_of(ten), history_of(twelve)])
    assert decision.classification is C
    assert rules(decision) == {"RF-32"}
    assert decision.rejected


def test_version_older_than_everything_incorporated_is_case_c() -> None:
    decision = evaluate_snapshot(build_snapshot(1), [history_of(build_snapshot(2))])
    assert decision.classification is C


def test_jump_from_3_to_7_is_case_d() -> None:
    decision = evaluate_snapshot(build_snapshot(7), [history_of(build_snapshot(3))])
    assert decision.classification is D and decision.proceeds


def test_consecutive_version_is_case_d() -> None:
    decision = evaluate_snapshot(build_snapshot(4), [history_of(build_snapshot(3))])
    assert decision.classification is D and decision.proceeds


def test_history_order_does_not_matter() -> None:
    snapshots = [build_snapshot(v) for v in (10, 12, 11)]
    history = [history_of(s) for s in snapshots]
    assert evaluate_snapshot(build_snapshot(13), history).classification is D
    assert evaluate_snapshot(build_snapshot(11), list(reversed(history))).classification is A
    assert evaluate_snapshot(build_snapshot(9), list(reversed(history))).classification is C


# --- precedencia: RF-31 → RF-32 → RF-30 → RF-29 ------------------------------------------------


def broken_artifact_variants(base: dict[str, Any]) -> dict[str, dict[str, Any]]:
    wrong_digest = {**base["iana"], "digest": "sha256:" + "0" * 64}
    no_iana = {k: v for k, v in base.items() if k != "iana"}
    no_text = {**base["iana"], "registry_text": ""}
    unparsable = {**base["iana"], "registry_text": "esto no es record-jar"}
    return {
        "bad-iana-digest": sealed(base, iana=wrong_digest),
        "no-artifact": seal(no_iana),
        "empty-artifact": sealed(base, iana=no_text),
        "unparsable-artifact": sealed(base, iana=unparsable),
    }


@pytest.mark.parametrize(
    "variant", ["bad-iana-digest", "no-artifact", "empty-artifact", "unparsable-artifact"]
)
def test_case_b_with_invalid_iana_artifact_is_reported_as_b(variant: str) -> None:
    original = build_snapshot(4)
    broken = broken_artifact_variants(build_snapshot(4, codes=("es", "pt")))[variant]
    decision = evaluate_snapshot(broken, [history_of(original)])
    assert decision.classification is B
    assert rules(decision) == {"RF-32"}


@pytest.mark.parametrize(
    "variant", ["bad-iana-digest", "no-artifact", "empty-artifact", "unparsable-artifact"]
)
def test_case_c_with_invalid_iana_artifact_is_reported_as_c(variant: str) -> None:
    history = [history_of(build_snapshot(10)), history_of(build_snapshot(12))]
    broken = broken_artifact_variants(build_snapshot(11))[variant]
    decision = evaluate_snapshot(broken, history)
    assert decision.classification is C
    assert rules(decision) == {"RF-32"}


@pytest.mark.parametrize(
    "variant", ["bad-iana-digest", "no-artifact", "empty-artifact", "unparsable-artifact"]
)
def test_case_a_with_invalid_iana_artifact_is_still_a_noop(variant: str) -> None:
    """El snapshot ya está incorporado: se identifica por versión y digest de contenido."""
    broken = broken_artifact_variants(build_snapshot(4))[variant]
    incorporated = HistoricalSnapshot(4, broken["content_digest"], date(2026, 9, 1))
    decision = evaluate_snapshot(broken, [incorporated])
    assert decision.is_noop and decision.violations == ()


def test_content_digest_mismatch_is_rf31_and_precedes_classification() -> None:
    original = build_snapshot(4)
    tampered = {**build_snapshot(4, codes=("es", "pt")), "content_digest": "sha256:" + "0" * 64}
    decision = evaluate_snapshot(tampered, [history_of(original)])
    assert decision.classification is None
    assert rules(decision) == {"RF-31"}


def test_content_digest_mismatch_on_an_already_incorporated_version_is_not_a_noop() -> None:
    original = build_snapshot(4)
    tampered = {**original, "content_digest": "sha256:" + "0" * 64}
    decision = evaluate_snapshot(tampered, [history_of(original)])
    assert decision.classification is None and decision.rejected and not decision.is_noop


def test_content_that_cannot_be_canonicalized_is_rf31() -> None:
    document = build_snapshot(4)
    document["provenance"]["ratio"] = 1.5
    decision = evaluate_snapshot(document, [])
    assert decision.classification is None and rules(decision) == {"RF-31"}


def test_rf30_is_reported_before_rf29() -> None:
    last = build_snapshot(3, file_date="2026-09-01")
    older = build_snapshot(4, file_date="2026-01-01")
    broken = sealed(older, iana={**older["iana"], "digest": "sha256:" + "0" * 64})
    decision = evaluate_snapshot(broken, [history_of(last)])
    assert decision.classification is D
    assert rules(decision) == {"RF-30"}


# --- RF-30: artefacto IANA ---------------------------------------------------------------------


def test_missing_artifact_is_rejected() -> None:
    base = build_snapshot(1)
    decision = evaluate_snapshot(seal({k: v for k, v in base.items() if k != "iana"}), [])
    assert decision.classification is D
    assert rules(decision) == {"RF-30"} and not decision.proceeds


def test_artifact_without_registry_text_is_rejected() -> None:
    base = build_snapshot(1)
    without = {k: v for k, v in base["iana"].items() if k != "registry_text"}
    decision = evaluate_snapshot(sealed(base, iana=without), [])
    assert rules(decision) == {"RF-30"}


def test_declared_iana_digest_that_does_not_match_is_rejected() -> None:
    base = build_snapshot(1)
    wrong = {**base["iana"], "digest": "sha256:" + "f" * 64}
    decision = evaluate_snapshot(sealed(base, iana=wrong), [])
    assert rules(decision) == {"RF-30"}


def test_artifact_modified_after_digest_is_rejected() -> None:
    base = build_snapshot(1)
    edited = {
        **base["iana"],
        "registry_text": base["iana"]["registry_text"] + "%%\nType: language\nSubtag: zz\n",
    }
    assert rules(evaluate_snapshot(sealed(base, iana=edited), [])) == {"RF-30"}


def with_artifact(text: str, version: int = 1, declared: str = "2026-09-01") -> dict[str, Any]:
    return build_snapshot(version, registry=text, declared_file_date=declared)


def test_artifact_without_file_date_is_rejected() -> None:
    text = "Type: language\nSubtag: es\n"
    decision = evaluate_snapshot(with_artifact(text), [])
    assert rules(decision) == {"RF-30"}
    assert "File-Date" in decision.violations[0].message


def test_artifact_with_an_entry_without_type_is_rejected() -> None:
    text = "File-Date: 2026-09-01\n%%\nSubtag: es\nDescription: Spanish\n"
    decision = evaluate_snapshot(with_artifact(text), [])
    assert rules(decision) == {"RF-30"}
    assert "Type" in decision.violations[0].message


def test_artifact_with_an_entry_without_subtag_is_rejected() -> None:
    text = "File-Date: 2026-09-01\n%%\nType: language\nDescription: Spanish\n"
    decision = evaluate_snapshot(with_artifact(text), [])
    assert rules(decision) == {"RF-30"}
    assert "Subtag" in decision.violations[0].message


@pytest.mark.parametrize("field", ["Deprecated", "Preferred-Value"])
def test_artifact_with_an_empty_deprecated_or_preferred_value_is_rejected(field: str) -> None:
    """RF-33: un campo presente pero vacío es ambiguo; se rechaza en vez de interpretarlo."""
    text = f"File-Date: 2026-09-01\n%%\nType: language\nSubtag: iw\n{field}:\n"
    decision = evaluate_snapshot(with_artifact(text), [])
    assert rules(decision) == {"RF-30"} and not decision.proceeds
    assert f"{field} vacío" in decision.violations[0].message


EMPTY_FIELD = "File-Date: 2026-09-01\n%%\nType: language\nSubtag: iw\nDeprecated:\n"


def test_case_b_with_an_empty_deprecated_is_reported_as_b_not_as_rf33() -> None:
    """RF-33: RF-32 precede a RF-30 y RF-33; un caso B no llega a mirar el artefacto."""
    incorporated = build_snapshot(3)
    decision = evaluate_snapshot(with_artifact(EMPTY_FIELD, version=3), [history_of(incorporated)])
    assert decision.classification is B and rules(decision) == {"RF-32"}


def test_case_c_with_an_empty_preferred_value_is_reported_as_c_not_as_rf33() -> None:
    incorporated = build_snapshot(5)
    text = EMPTY_FIELD.replace("Deprecated:", "Preferred-Value:")
    decision = evaluate_snapshot(with_artifact(text, version=4), [history_of(incorporated)])
    assert decision.classification is C and rules(decision) == {"RF-32"}


def test_case_d_with_an_empty_field_is_rejected_by_the_artifact_rule() -> None:
    incorporated = build_snapshot(2)
    decision = evaluate_snapshot(with_artifact(EMPTY_FIELD, version=3), [history_of(incorporated)])
    assert decision.classification is D and rules(decision) == {"RF-30"} and not decision.proceeds


def test_a_value_on_a_continuation_line_is_not_an_empty_field() -> None:
    """RF-33: el campo está presente y con valor."""
    text = "File-Date: 2026-09-01\n%%\nType: language\nSubtag: iw\nDeprecated:\n  1989-01-01\n"
    decision = evaluate_snapshot(with_artifact(text), [])
    assert decision.violations == () and decision.proceeds


def test_entries_without_optional_fields_are_not_rejected_for_their_absence() -> None:
    """`Deprecated`, `Preferred-Value` y `Scope` son opcionales en cada entrada."""
    text = "File-Date: 2026-09-01\n%%\nType: language\nSubtag: es\n%%\nType: language\nSubtag: en\n"
    decision = evaluate_snapshot(with_artifact(text), [])
    assert decision.violations == () and decision.proceeds


def test_entries_with_only_the_required_fields_pass_with_real_looking_entries() -> None:
    text = (
        "File-Date: 2026-09-01\n%%\n"
        "Type: language\nSubtag: es\nDescription: Spanish\n%%\n"
        "Type: language\nSubtag: iw\nDeprecated: 1989-01-01\nPreferred-Value: he\n%%\n"
        "Type: language\nSubtag: und\nScope: special\n"
    )
    assert evaluate_snapshot(with_artifact(text), []).proceeds


def test_declared_file_date_different_from_the_artifact_is_rejected() -> None:
    decision = evaluate_snapshot(
        with_artifact(registry_text("2026-09-01"), declared="2026-09-02"), []
    )
    assert rules(decision) == {"RF-30"}
    assert "File-Date" in decision.violations[0].message


def test_decision_exposes_the_parsed_artifact_only_when_it_proceeds() -> None:
    ok = evaluate_snapshot(build_snapshot(1), [])
    assert ok.registry is not None and ok.registry.file_date == date(2026, 9, 1)
    bad = evaluate_snapshot(with_artifact("nada"), [])
    assert bad.registry is None


# --- RF-29: File-Date monótono -----------------------------------------------------------------


@pytest.mark.parametrize("file_date", ["1999-01-01", "2026-09-01", "2099-12-31"])
def test_first_snapshot_accepts_any_valid_file_date(file_date: str) -> None:
    decision = evaluate_snapshot(build_snapshot(1, file_date=file_date), [])
    assert decision.proceeds


def test_older_file_date_than_the_last_is_rejected() -> None:
    last = build_snapshot(3, file_date="2026-09-01")
    decision = evaluate_snapshot(build_snapshot(4, file_date="2026-08-31"), [history_of(last)])
    assert decision.classification is D
    assert rules(decision) == {"RF-29"} and not decision.proceeds


def test_equal_file_date_is_valid() -> None:
    last = build_snapshot(3, file_date="2026-09-01")
    decision = evaluate_snapshot(build_snapshot(4, file_date="2026-09-01"), [history_of(last)])
    assert decision.proceeds


def test_later_file_date_is_valid() -> None:
    last = build_snapshot(3, file_date="2026-09-01")
    decision = evaluate_snapshot(build_snapshot(4, file_date="2026-09-02"), [history_of(last)])
    assert decision.proceeds


def test_file_date_is_compared_with_the_last_snapshot_by_version() -> None:
    history = [
        HistoricalSnapshot(2, "sha256:" + "2" * 64, date(2026, 10, 1)),
        HistoricalSnapshot(1, "sha256:" + "1" * 64, date(2026, 9, 1)),
    ]
    rejected = evaluate_snapshot(build_snapshot(3, file_date="2026-09-15"), history)
    assert rules(rejected) == {"RF-29"}
    accepted = evaluate_snapshot(build_snapshot(3, file_date="2026-10-01"), history)
    assert accepted.proceeds


def test_file_date_after_a_version_jump_is_still_compared() -> None:
    last = build_snapshot(3, file_date="2026-09-01")
    decision = evaluate_snapshot(build_snapshot(7, file_date="2026-01-01"), [history_of(last)])
    assert rules(decision) == {"RF-29"}


# --- el resultado ------------------------------------------------------------------------------


def test_violations_carry_a_human_readable_message() -> None:
    last = build_snapshot(3, file_date="2026-09-01")
    decision = evaluate_snapshot(build_snapshot(4, file_date="2026-08-31"), [history_of(last)])
    violation = decision.violations[0]
    assert violation.rule == "RF-29"
    assert "2026-08-31" in violation.message and "2026-09-01" in violation.message


def test_evaluation_does_not_modify_the_document_or_the_history() -> None:
    document = build_snapshot(4)
    snapshot_before = repr(document)
    history = [history_of(build_snapshot(3))]
    history_before = repr(history)
    evaluate_snapshot(document, history)
    assert repr(document) == snapshot_before and repr(history) == history_before


def test_a_preferred_value_on_a_continuation_line_is_not_an_empty_field() -> None:
    """RF-33: igual que `Deprecated`, el campo está presente y con valor."""
    text = (
        "File-Date: 2026-09-01\n%%\nType: language\nSubtag: he\n%%\n"
        "Type: language\nSubtag: iw\nDeprecated: 1989-01-01\nPreferred-Value:\n  he\n"
    )
    decision = evaluate_snapshot(with_artifact(text), [])
    assert decision.violations == () and decision.proceeds
    assert decision.registry is not None
    assert decision.registry.language_aliases() == {"iw": "he"}
