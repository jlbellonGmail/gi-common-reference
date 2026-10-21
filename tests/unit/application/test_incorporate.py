"""T7: caso de uso de incorporación sobre el puerto, con un repositorio en memoria
(RF-14, RF-17, RF-18, RF-20, RF-21, RF-28, RNF-5)."""

import copy
from typing import Any

import pytest

from gi_common_reference.locales.application.incorporate import (
    IncorporationResult,
    Outcome,
    incorporate_snapshot,
)
from tests.fixtures.fakes import FakeRepository
from tests.fixtures.snapshots import build_snapshot, iw_scenario, locale, locale_id, seal

WRITE_ORDER = ["insert_snapshot", "insert_locales", "update_metadata", "replace_aliases"]


def rules(result: IncorporationResult) -> set[str]:
    return {v.rule for v in result.violations}


def test_first_snapshot_is_incorporated_with_the_ids_it_brings() -> None:
    repo = FakeRepository()
    v1, _ = iw_scenario()
    result = incorporate_snapshot(v1, repo)
    assert result.outcome is Outcome.INCORPORATED
    assert (result.snapshot_version, result.new_locales, result.updated_locales) == (1, 3, 0)
    assert set(repo.state.locales) == {locale_id("es"), locale_id("en"), locale_id("iw")}
    assert {r.code for r in repo.state.locales.values()} == {"es", "en", "iw"}
    assert set(repo.state.first_snapshot.values()) == {1}
    assert repo.state.aliases == {}
    assert len(repo.state.snapshots) == 1 and repo.state.snapshots[0] == v1


def test_write_order_is_snapshot_then_new_locales_then_metadata_then_aliases() -> None:
    repo = FakeRepository()
    v1, v2 = iw_scenario()
    incorporate_snapshot(v1, repo)
    repo.calls.clear()
    incorporate_snapshot(v2, repo)
    assert repo.calls == WRITE_ORDER


def test_later_snapshot_updates_metadata_and_keeps_identity() -> None:
    repo = FakeRepository()
    v1, v2 = iw_scenario()
    incorporate_snapshot(v1, repo)
    result = incorporate_snapshot(v2, repo)
    assert result.outcome is Outcome.INCORPORATED
    assert (result.new_locales, result.updated_locales) == (1, 1)
    iw = repo.state.locales[locale_id("iw")]
    assert (iw.code, iw.status, iw.iana_deprecated) == ("iw", "inactive", True)
    assert iw.replacement_locale_id == locale_id("he")
    assert repo.state.first_snapshot[locale_id("he")] == 2
    assert repo.state.first_snapshot[locale_id("iw")] == 1
    assert repo.state.aliases == {"iw": "he"}
    assert [s["snapshot_version"] for s in repo.state.snapshots] == [1, 2]


def test_aliases_are_replaced_with_those_of_the_current_artifact() -> None:
    repo = FakeRepository()
    v1, v2 = iw_scenario()
    incorporate_snapshot(v1, repo)
    assert repo.state.aliases == {}
    incorporate_snapshot(v2, repo)
    assert repo.state.aliases == {"iw": "he"}


def test_resubmitting_an_incorporated_snapshot_is_a_noop_without_writes() -> None:
    repo = FakeRepository()
    v1, v2 = iw_scenario()
    incorporate_snapshot(v1, repo)
    incorporate_snapshot(v2, repo)
    before, calls = copy.deepcopy(repo.state), len(repo.calls)
    for document in (v2, v1):  # el último y uno anterior (caso A de RF-32)
        result = incorporate_snapshot(document, repo)
        assert result.outcome is Outcome.NOOP and result.violations == ()
    assert repo.state == before
    assert len(repo.calls) == calls


def test_rejected_snapshot_writes_nothing() -> None:
    repo = FakeRepository()
    v1, _ = iw_scenario()
    incorporate_snapshot(v1, repo)
    before, calls = copy.deepcopy(repo.state), list(repo.calls)
    bad = build_snapshot(2, locales=[locale("es"), locale("ES")])
    result = incorporate_snapshot(bad, repo)
    assert result.outcome is Outcome.REJECTED
    assert repo.state == before and repo.calls == calls


def test_published_locale_arriving_in_uppercase_is_rejected_with_rf28() -> None:
    repo = FakeRepository()
    v1, _ = iw_scenario()
    incorporate_snapshot(v1, repo)
    uppercase = locale("es", code="ES")
    bad = build_snapshot(2, locales=[uppercase, locale("en"), locale("iw")], registry=None)
    result = incorporate_snapshot(bad, repo)
    assert result.outcome is Outcome.REJECTED and rules(result) == {"RF-28"}
    assert {r.code for r in repo.state.locales.values()} == {"es", "en", "iw"}


def incorporated(*documents: dict[str, Any]) -> FakeRepository:
    repo = FakeRepository()
    for document in documents:
        assert incorporate_snapshot(document, repo).outcome is Outcome.INCORPORATED
    return repo


def assert_rejected_untouched(repo: FakeRepository, document: dict[str, Any], rule: str) -> None:
    before, calls = copy.deepcopy(repo.state), list(repo.calls)
    result = incorporate_snapshot(document, repo)
    assert result.outcome is Outcome.REJECTED and rules(result) == {rule}
    assert repo.state == before and repo.calls == calls


def test_content_digest_mismatch_is_rejected_with_rf31() -> None:
    v1, v2 = iw_scenario()
    tampered = {
        **build_snapshot(3, codes=("es", "en", "he", "iw")),
        "content_digest": "sha256:" + "0" * 64,
    }
    assert_rejected_untouched(incorporated(v1, v2), tampered, "RF-31")


def test_same_version_with_other_content_is_rejected_with_rf32() -> None:
    v1, v2 = iw_scenario()
    assert_rejected_untouched(incorporated(v1, v2), build_snapshot(2, codes=("es", "en")), "RF-32")


def test_version_older_than_the_last_is_rejected_with_rf32() -> None:
    repo = incorporated(build_snapshot(10), build_snapshot(12))
    assert_rejected_untouched(repo, build_snapshot(11), "RF-32")


def test_iana_digest_mismatch_is_rejected_with_rf30() -> None:
    v1, v2 = iw_scenario()
    v3 = build_snapshot(3, file_date="2026-11-01", codes=("es", "en", "he", "iw"))
    broken = seal({**v3, "iana": {**v3["iana"], "digest": "sha256:" + "0" * 64}})
    assert_rejected_untouched(incorporated(v1, v2), broken, "RF-30")


def test_older_file_date_is_rejected_with_rf29() -> None:
    repo = FakeRepository()
    v1, v2 = iw_scenario()
    for document in (v1, v2):
        incorporate_snapshot(document, repo)
    stale = build_snapshot(3, file_date="2026-01-01", codes=("es", "en", "he", "iw"))
    result = incorporate_snapshot(stale, repo)
    assert result.outcome is Outcome.REJECTED and rules(result) == {"RF-29"}


@pytest.mark.parametrize("failing_step", WRITE_ORDER)
def test_a_failure_in_any_write_step_rolls_everything_back(failing_step: str) -> None:
    repo = FakeRepository()
    v1, v2 = iw_scenario()
    incorporate_snapshot(v1, repo)
    before = copy.deepcopy(repo.state)
    repo.fail_at = failing_step
    with pytest.raises(RuntimeError, match=failing_step):
        incorporate_snapshot(v2, repo)
    assert repo.state == before


def test_the_whole_evaluation_runs_inside_one_transaction() -> None:
    repo = FakeRepository()
    v1, v2 = iw_scenario()
    incorporate_snapshot(v1, repo)
    incorporate_snapshot(v2, repo)
    incorporate_snapshot(v2, repo)
    assert repo.transactions == 3


def test_the_incorporation_never_generates_ids() -> None:
    repo = FakeRepository()
    document = build_snapshot(1, codes=("es", "en"))
    incorporate_snapshot(document, repo)
    assert {r.locale_id for r in repo.state.locales.values()} == {
        item["locale_id"] for item in document["locales"]
    }
