"""T7: incorporación con repositorio en memoria (RF-21, RF-25, RF-26, RF-35, RF-38)."""

import pytest

from gi_common_reference.regions.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.regions.domain.errors import ConstraintRejected
from gi_common_reference.regions.domain.model import LocaleCatalog
from tests.fixtures.region_fakes import FakeRegionRepository
from tests.fixtures.regions import POLICY, build_snapshot, recoding, region, region_id, subregion

WRITE_STEPS = [
    "insert_snapshot",
    "insert_regions",
    "update_regions",
    "insert_subregions",
    "update_subregions",
    "record_reclassifications",
    "record_recodings",
    "insert_names",
    "update_names",
    "check_constraints",
]


def test_a_valid_snapshot_is_written_in_the_planned_order() -> None:
    repository = FakeRegionRepository()
    result = incorporate_snapshot(build_snapshot(1), repository, POLICY)
    assert result.outcome is Outcome.INCORPORATED
    assert (result.new_regions, result.new_subregions, result.locale_snapshot_version) == (2, 4, 1)
    assert repository.calls == WRITE_STEPS
    (stored,) = repository.state.snapshots
    assert stored["_locale_snapshot_version"] == 1 and stored["_policy_version"] == POLICY.version


def test_the_same_snapshot_again_is_a_noop_without_writes() -> None:
    repository = FakeRegionRepository()
    incorporate_snapshot(build_snapshot(1), repository, POLICY)
    repository.calls.clear()
    before = repository.state
    result = incorporate_snapshot(build_snapshot(1), repository, POLICY)
    assert result.outcome is Outcome.NOOP and repository.calls == []
    assert repository.state == before


def test_a_rejected_snapshot_writes_nothing() -> None:
    repository = FakeRegionRepository()
    incorporate_snapshot(build_snapshot(1), repository, POLICY)
    repository.calls.clear()
    before = repository.state
    result = incorporate_snapshot(build_snapshot(2, regions=[region("019")]), repository, POLICY)
    assert result.outcome is Outcome.REJECTED and result.violations
    assert repository.calls == [] and repository.state == before


def test_a_snapshot_is_rejected_when_locale_has_no_snapshot() -> None:
    repository = FakeRegionRepository(locales=LocaleCatalog(None, ()))
    result = incorporate_snapshot(build_snapshot(1), repository, POLICY)
    assert result.outcome is Outcome.REJECTED
    assert {v.rule for v in result.violations} == {"RF-38"}
    assert repository.calls == []


def test_a_failure_after_the_first_write_leaves_nothing() -> None:
    repository = FakeRegionRepository()
    repository.fail_at = "insert_subregions"
    with pytest.raises(RuntimeError):
        incorporate_snapshot(build_snapshot(1), repository, POLICY)
    assert repository.state.snapshots == [] and repository.state.regions == {}


@pytest.mark.parametrize(("foreign", "rule"), [(True, "RF-35"), (False, "RNF-3")])
def test_a_constraint_rejected_by_the_database_is_a_rejection(foreign: bool, rule: str) -> None:
    repository = FakeRegionRepository()
    incorporate_snapshot(build_snapshot(1), repository, POLICY)
    before = repository.state
    repository.constraint_failure = ConstraintRejected("country_region_pair_fk", "23503", foreign)
    reclassified = build_snapshot(
        2,
        subregions=[
            subregion("015"),
            subregion("202"),
            subregion("419", region_id=region_id("002")),
            subregion("021"),
        ],
    )
    result = incorporate_snapshot(reclassified, repository, POLICY)
    assert result.outcome is Outcome.REJECTED
    (violation,) = result.violations
    assert violation.rule == rule and "country_region_pair_fk" in violation.message
    assert repository.state == before


def test_reclassifications_and_recodings_are_recorded_with_the_snapshot_version() -> None:
    repository = FakeRegionRepository()
    incorporate_snapshot(build_snapshot(1), repository, POLICY)
    document = build_snapshot(
        2,
        subregions=[
            subregion("015"),
            subregion("202"),
            subregion("419", region_id=region_id("002")),
            subregion("021", code="456"),
        ],
        recodings=[recoding("subregion", "021", "021", "456")],
    )
    result = incorporate_snapshot(document, repository, POLICY)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.reclassifications, result.recodings, result.updated) == (1, 1, 2)
    assert [version for _, version in repository.state.reclassifications] == [2]
    assert [version for _, version in repository.state.recodings] == [2]
