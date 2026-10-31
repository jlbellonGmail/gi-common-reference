"""T8: incorporación y diff con repositorio en memoria (RF-20, RF-23–RF-25, RF-30, RF-51)."""

from pathlib import Path
from typing import Any

import pytest

from gi_common_reference.countries.application.diff import preview_snapshot
from gi_common_reference.countries.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.countries.domain.errors import ConstraintRejected
from gi_common_reference.countries.domain.model import LocaleCatalog, RegionCatalog
from gi_common_reference.countries.infrastructure.flag_store import DirectoryFlagStore
from tests.fixtures.countries import (
    FLAGS_DIR,
    POLICY,
    build_snapshot,
    country,
    country_id,
    flag,
    flag_exception,
    names,
    recoding,
    seal,
)
from tests.fixtures.country_fakes import FakeCountryRepository

STORE = DirectoryFlagStore(FLAGS_DIR)
BASE = ("AR", "NA", "AQ", "TW", "US", "CA", "PR", "BV")
WRITE_STEPS = [
    "insert_snapshot",
    "insert_countries",
    "update_countries",
    "record_recodings",
    "insert_names",
    "update_names",
    "write_flags",
    "touch_countries",
    "check_constraints",
]


def timor_recoded() -> dict[str, Any]:
    """Snapshot 2: Timor se recodifica TP → TL (mismo id, estado y nombres)."""
    return build_snapshot(
        2,
        countries=[*(country(k) for k in BASE), country("TL", identity="TP")],
        country_names=[*(n for k in BASE for n in names(k)), *names("TP")],
        flags=[*(flag(k) for k in BASE if k not in ("AQ", "BV")), flag("TP")],
        flag_exceptions=[flag_exception("AQ"), flag_exception("BV")],
        recodings=[recoding("TP", ("TP", "TMP", "626"), ("TL", "TLS", "626"))],
    )


def test_a_valid_snapshot_is_written_in_the_planned_order() -> None:
    repository = FakeCountryRepository()
    result = incorporate_snapshot(build_snapshot(1), repository, POLICY, STORE)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.new_countries, result.updated, result.recodings) == (8, 0, 0)
    assert (result.locale_snapshot_version, result.region_snapshot_version) == (1, 1)
    assert repository.calls == WRITE_STEPS
    (stored,) = repository.state.snapshots
    assert stored["_locale_snapshot_version"] == 1 and stored["_policy_version"] == POLICY.version
    assert (
        stored["region_snapshot_version"] == 1 and stored["_region_current_snapshot_version"] == 1
    )
    assert len(repository.state.countries) == 8 and len(repository.state.names) == 16


def test_the_same_snapshot_again_is_a_noop_without_writes() -> None:
    repository = FakeCountryRepository()
    incorporate_snapshot(build_snapshot(1), repository, POLICY, STORE)
    repository.calls.clear()
    before = repository.state
    result = incorporate_snapshot(build_snapshot(1), repository, POLICY, STORE)
    assert result.outcome is Outcome.NOOP and repository.calls == []
    assert repository.state == before


def test_a_rejected_snapshot_writes_nothing() -> None:
    repository = FakeCountryRepository()
    incorporate_snapshot(build_snapshot(1), repository, POLICY, STORE)
    repository.calls.clear()
    before = repository.state
    result = incorporate_snapshot(build_snapshot(2, keys=BASE[:-1]), repository, POLICY, STORE)
    assert result.outcome is Outcome.REJECTED
    assert {v.rule for v in result.violations} == {"RF-21"}
    assert repository.calls == [] and repository.state == before


def test_an_empty_locale_or_regions_catalog_rejects_without_writes() -> None:
    locales = FakeCountryRepository(locales=LocaleCatalog(None, ()))
    result = incorporate_snapshot(build_snapshot(1), locales, POLICY, STORE)
    assert result.outcome is Outcome.REJECTED and {v.rule for v in result.violations} == {"RF-36"}
    assert locales.calls == []
    regions = FakeCountryRepository(regions=RegionCatalog(None))
    result = incorporate_snapshot(build_snapshot(1), regions, POLICY, STORE)
    assert result.outcome is Outcome.REJECTED and {v.rule for v in result.violations} == {"RF-47"}
    assert regions.calls == []


def test_a_missing_or_altered_flag_asset_rejects_the_whole_snapshot(tmp_path: Path) -> None:
    repository = FakeCountryRepository()
    empty = DirectoryFlagStore(tmp_path)
    result = incorporate_snapshot(build_snapshot(1), repository, POLICY, empty)
    assert result.outcome is Outcome.REJECTED
    assert {v.rule for v in result.violations} == {"RF-49"} and len(result.violations) == 6
    assert repository.calls == [] and repository.state.snapshots == []


def test_a_failure_after_the_first_write_leaves_nothing() -> None:
    repository = FakeCountryRepository()
    repository.fail_at = "insert_names"
    with pytest.raises(RuntimeError):
        incorporate_snapshot(build_snapshot(1), repository, POLICY, STORE)
    assert repository.state.snapshots == [] and repository.state.countries == {}


@pytest.mark.parametrize(("foreign", "rule"), [(True, "RF-6"), (False, "RNF-5")])
def test_a_constraint_rejected_by_the_database_is_a_rejection(foreign: bool, rule: str) -> None:
    repository = FakeCountryRepository()
    repository.constraint_failure = ConstraintRejected(
        "country_classification_fk", "23503", foreign
    )
    result = incorporate_snapshot(build_snapshot(1), repository, POLICY, STORE)
    assert result.outcome is Outcome.REJECTED
    (violation,) = result.violations
    assert violation.rule == rule and "country_classification_fk" in violation.message
    assert repository.state.snapshots == []


def test_a_recoding_keeps_the_id_status_and_names_and_is_traced() -> None:
    repository = FakeCountryRepository()
    incorporate_snapshot(build_snapshot(1, keys=(*BASE, "TP")), repository, POLICY, STORE)
    names_before = dict(repository.state.names)
    result = incorporate_snapshot(timor_recoded(), repository, POLICY, STORE)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.new_countries, result.updated, result.recodings) == (0, 1, 1)
    assert repository.state.names == names_before
    timor = repository.state.countries[country_id("TP")]
    assert (timor.alpha2, timor.status) == ("TL", "active")
    assert [version for _, version in repository.state.recodings] == [2]


def test_version_columns_track_introduction_codes_and_last_change() -> None:
    """RF-51: primer snapshot, snapshot de los códigos vigentes y último que cambió el contenido."""
    repository = FakeCountryRepository()
    incorporate_snapshot(build_snapshot(1, keys=(*BASE, "TP")), repository, POLICY, STORE)
    assert set(map(tuple, repository.state.versions.values())) == {(1, 1, 1)}

    incorporate_snapshot(timor_recoded(), repository, POLICY, STORE)
    versions = repository.state.versions
    assert versions[country_id("TP")] == [1, 2, 2]  # recodificado en el 2
    assert versions[country_id("AR")] == [1, 1, 1]

    document = timor_recoded()
    document.update(snapshot_version=3, recodings=[])
    renamed = next(
        n
        for n in document["country_names"]
        if n["country_id"] == country_id("AR") and n["name"] == "Argentina" and n["official_name"]
    )
    renamed["official_name"] = "La República Argentina"
    document = seal(document)
    result = incorporate_snapshot(document, repository, POLICY, STORE)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    versions = repository.state.versions  # el estado confirmado es otra copia
    assert versions[country_id("AR")] == [1, 1, 3]  # cambió un nombre: último = 3, códigos = 1
    assert versions[country_id("TP")] == [1, 2, 2]

    before = {k: list(v) for k, v in repository.state.versions.items()}
    assert incorporate_snapshot(document, repository, POLICY, STORE).outcome is Outcome.NOOP
    assert repository.state.versions == before


def test_applying_the_same_content_under_a_new_version_changes_no_country() -> None:
    repository = FakeCountryRepository()
    incorporate_snapshot(build_snapshot(1), repository, POLICY, STORE)
    result = incorporate_snapshot(build_snapshot(2), repository, POLICY, STORE)
    assert result.outcome is Outcome.INCORPORATED
    assert (result.new_countries, result.updated, result.recodings) == (0, 0, 0)
    assert set(map(tuple, repository.state.versions.values())) == {(1, 1, 1)}


# --- diff (RF-30, D18) ---------------------------------------------------------------------------


def test_the_diff_reads_only_and_matches_what_incorporating_would_do() -> None:
    repository = FakeCountryRepository()
    incorporate_snapshot(build_snapshot(1, keys=(*BASE, "TP")), repository, POLICY, STORE)
    repository.calls.clear()
    transactions, state = repository.transactions, repository.state
    preview = preview_snapshot(timor_recoded(), repository, POLICY)
    assert preview.outcome is Outcome.INCORPORATED and preview.diff is not None
    assert {e.category for e in preview.diff.entries} == {"códigos"}
    assert repository.calls == [] and repository.transactions == transactions
    assert repository.inspections == 1 and repository.state == state


def test_the_diff_of_a_noop_snapshot_is_empty_and_an_invalid_one_lists_violations() -> None:
    repository = FakeCountryRepository()
    incorporate_snapshot(build_snapshot(1), repository, POLICY, STORE)
    assert preview_snapshot(build_snapshot(1), repository, POLICY).outcome is Outcome.NOOP
    rejected = preview_snapshot(build_snapshot(2, keys=BASE[:-1]), repository, POLICY)
    assert rejected.outcome is Outcome.REJECTED and rejected.diff is None
    assert {v.rule for v in rejected.violations} == {"RF-21"}


def test_the_diff_does_not_verify_the_flag_assets() -> None:
    """D18: eso ocurre al incorporar. Una bandera con suma incorrecta igual se muestra."""
    repository = FakeCountryRepository()
    document = build_snapshot(1)
    document["flags"][0]["sha256"] = "sha256:" + "0" * 64
    document = seal(document)
    assert preview_snapshot(document, repository, POLICY).outcome is Outcome.INCORPORATED
    assert incorporate_snapshot(document, repository, POLICY, STORE).outcome is Outcome.REJECTED
