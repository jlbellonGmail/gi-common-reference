"""T6: incorporación transaccional de Units con un repositorio en memoria (RF-6, RF-42 a RF-46)."""

import copy
from typing import Any

import pytest

from gi_common_reference.units.application.diff import preview_snapshot
from gi_common_reference.units.application.incorporate import (
    Outcome,
    incorporate_snapshot,
)
from gi_common_reference.units.domain.errors import ConstraintRejected
from tests.fixtures.units import EN, ES, build_snapshot, kind_id, seal, unit_id
from tests.fixtures.units_fakes import FakeUnitsRepository
from tests.fixtures.units_variants import BULK_ID, SACK_ID, sack_snapshot
from tests.unit.units.helpers import POLICY, association_row, edit, kind_row, ucum_table, unit_row

WRITE_ORDER = [
    "insert_snapshot",
    "insert_units",
    "update_units",
    "insert_quantity_kinds",
    "update_quantity_kinds",
    "insert_associations",
    "update_associations",
    "insert_kind_names",
    "update_kind_names",
    "insert_unit_names",
    "update_unit_names",
    "touch_units",
    "touch_quantity_kinds",
    "check_constraints",
]


def run(document: dict[str, Any], repository: FakeUnitsRepository) -> Any:
    return incorporate_snapshot(document, repository, POLICY, ucum_table())


def dump(repository: FakeUnitsRepository) -> Any:
    return copy.deepcopy(repository.state)


def seeded() -> FakeUnitsRepository:
    repository = FakeUnitsRepository()
    result = run(build_snapshot(1), repository)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    return repository


def second_version() -> dict[str, Any]:
    """v2: una unidad nueva, el retiro de `oz` (y su asociación) y un nombre cambiado."""

    def change(document: dict[str, Any]) -> None:
        document["snapshot_version"] = 2
        unit_row(document, "oz")["status"] = "inactive"
        association_row(document, "mass", "oz")["status"] = "inactive"
        for row in document["unit_names"]:
            if row["unit_id"] == unit_id("kg") and row["locale_id"] == EN:
                row["name"] = "kilo"

    return seal(edit(build_snapshot(1), change))


# --- primer snapshot, no-op e idempotencia


def test_the_first_snapshot_is_incorporated_with_the_full_artifact() -> None:
    repository = FakeUnitsRepository()
    document = build_snapshot(1)
    result = run(document, repository)
    assert result.outcome is Outcome.INCORPORATED and not result.violations
    assert (result.new_units, result.new_quantity_kinds, result.new_associations) == (50, 14, 54)
    assert result.locale_snapshot_version == 1 and result.ucum_table_version == "2.2"
    stored = repository.state.snapshots[0]
    assert stored["_locale_snapshot_version"] == 1 and stored["_ucum_table_version"] == "2.2"
    assert stored["_policy_version"] == POLICY.version
    assert {k: v for k, v in stored.items() if not k.startswith("_")} == document
    assert all(first == last == 1 for first, last in repository.state.versions.values())


def test_the_writes_follow_the_planned_order_and_end_with_the_constraint_check() -> None:
    repository = FakeUnitsRepository()
    run(build_snapshot(1), repository)
    calls = repository.calls
    assert calls[0] == "insert_snapshot" and calls[-1] == "check_constraints"
    assert calls == [step for step in WRITE_ORDER if step in calls]
    assert calls.index("insert_units") < calls.index("insert_quantity_kinds")
    assert calls.index("insert_quantity_kinds") < calls.index("insert_associations")
    assert calls.index("insert_associations") < calls.index("insert_kind_names")


def test_resubmitting_the_same_snapshot_is_a_noop_that_changes_nothing() -> None:
    repository = seeded()
    before, calls = dump(repository), len(repository.calls)
    again = run(copy.deepcopy(build_snapshot(1)), repository)
    assert again.outcome is Outcome.NOOP and not again.violations
    assert dump(repository) == before and len(repository.calls) == calls


def test_a_higher_version_without_changes_registers_only_the_snapshot() -> None:
    repository = seeded()
    result = run(build_snapshot(5), repository)
    assert result.outcome is Outcome.INCORPORATED
    assert (result.new_units, result.updated_units, result.names) == (0, 0, 0)
    assert [s["snapshot_version"] for s in repository.state.snapshots] == [1, 5]
    assert all(last == 1 for _, last in repository.state.versions.values())


# --- rechazos sin escrituras


def rejected_without_writes(
    document: dict[str, Any], repository: FakeUnitsRepository, rule: str
) -> None:
    before, calls = dump(repository), len(repository.calls)
    result = run(document, repository)
    assert result.outcome is Outcome.REJECTED
    assert rule in {v.rule for v in result.violations}, result.violations
    assert dump(repository) == before
    assert not {"insert_snapshot", "insert_units"} & set(repository.calls[calls:])


def test_the_same_version_with_another_digest_is_rejected() -> None:
    rejected_without_writes(build_snapshot(1, codes=("mass",)), seeded(), "RF-42")


def test_a_lower_version_is_rejected_as_a_regression() -> None:
    repository = FakeUnitsRepository()
    run(build_snapshot(5), repository)
    rejected_without_writes(build_snapshot(3), repository, "RF-42")


def test_a_tampered_digest_is_rejected() -> None:
    tampered = build_snapshot(2)
    unit_row(tampered, "kg")["symbol"] = "KG"
    rejected_without_writes(tampered, seeded(), "RF-41")


def test_an_invalid_ucum_code_is_rejected_without_partial_changes() -> None:
    document = edit(build_snapshot(1), lambda d: unit_row(d, "kg").update(ucum_code="kgg"))
    rejected_without_writes(seal(document), FakeUnitsRepository(), "RF-15")


def test_an_omitted_unit_is_rejected() -> None:
    def omit(document: dict[str, Any]) -> None:
        document["snapshot_version"] = 2
        document["units"] = [u for u in document["units"] if u["unit_id"] != unit_id("oz")]
        document["quantity_kind_units"] = [
            a for a in document["quantity_kind_units"] if a["unit_id"] != unit_id("oz")
        ]
        document["unit_names"] = [
            n for n in document["unit_names"] if n["unit_id"] != unit_id("oz")
        ]

    rejected_without_writes(seal(edit(build_snapshot(1), omit)), seeded(), "RF-43")


def test_a_retired_unit_that_is_the_reference_of_an_active_kind_is_rejected() -> None:
    def retire(document: dict[str, Any]) -> None:
        document["snapshot_version"] = 2
        unit_row(document, "kg")["status"] = "inactive"

    rejected_without_writes(seal(edit(build_snapshot(1), retire)), seeded(), "RF-8")


def test_missing_required_locale_names_are_rejected() -> None:
    document = build_snapshot(1)
    document["quantity_kind_names"] = document["quantity_kind_names"][1:]
    rejected_without_writes(seal(document), FakeUnitsRepository(), "RF-19")


# --- versión posterior: alta, retiro, cambio de factor


def test_a_later_version_with_a_retirement_updates_versions_precisely() -> None:
    repository = seeded()
    result = run(second_version(), repository)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.updated_units, result.updated_associations) == (1, 1)
    state = repository.state
    assert state.units[unit_id("oz")].status == "inactive"
    assert state.versions[unit_id("oz")] == [1, 2]
    assert state.versions[(kind_id("mass"), unit_id("oz"))] == [1, 2]
    assert state.versions[unit_id("kg")] == [1, 2]  # su nombre cambió: se marca como tocada
    assert state.versions[unit_id("g")] == [1, 1]
    assert state.versions[kind_id("mass")] == [1, 1]


def test_a_changed_factor_of_a_unit_without_ucum_is_applied_and_shown_in_the_diff() -> None:
    repository = FakeUnitsRepository()
    assert run(sack_snapshot(1, factor="60"), repository).outcome is Outcome.INCORPORATED
    later = sack_snapshot(2, factor="50")
    preview = preview_snapshot(later, repository, POLICY, ucum_table())
    assert preview.diff is not None
    assert any("60" in line and "50" in line for line in preview.diff.lines())
    result = run(later, repository)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.updated_associations, result.updated_units) == (1, 0)
    key = (kind_id("mass"), SACK_ID)
    assert repository.state.associations[key].factor == "50"
    assert repository.state.versions[key] == [1, 2]
    assert repository.state.versions[unit_id("kg")] == [1, 1]


def test_a_changed_factor_of_a_unit_with_ucum_is_rejected_by_the_cross_check() -> None:
    repository = seeded()
    document = edit(
        build_snapshot(2),
        lambda d: association_row(d, "mass", "lb").update(factor="0.5"),
    )
    rejected_without_writes(seal(document), repository, "RF-16")


# --- atomicidad


@pytest.mark.parametrize("step", [s for s in WRITE_ORDER[:-1] if "touch" not in s])
def test_a_failure_at_any_write_step_leaves_the_catalog_untouched(step: str) -> None:
    repository = seeded()
    before = dump(repository)
    repository.fail_at = step

    def richer(document: dict[str, Any]) -> None:
        # asegura que cada paso de escritura tenga trabajo
        document["snapshot_version"] = 2
        unit_row(document, "oz")["status"] = "inactive"
        association_row(document, "mass", "oz")["status"] = "inactive"
        document["units"].append(
            {
                "unit_id": SACK_ID,
                "ucum_code": None,
                "unece_code": None,
                "symbol": "qq",
                "status": "active",
            }
        )
        document["quantity_kinds"].append(
            {
                "quantity_kind_id": BULK_ID,
                "code": "bulk",
                "conversion_type": "linear",
                "reference_unit_id": SACK_ID,
                "status": "active",
            }
        )
        document["quantity_kind_units"].append(
            {
                "quantity_kind_id": BULK_ID,
                "unit_id": SACK_ID,
                "factor": "1",
                "offset": "0",
                "status": "active",
            }
        )
        for locale in (EN, ES):
            document["quantity_kind_names"].append(
                {
                    "quantity_kind_id": BULK_ID,
                    "locale_id": locale,
                    "name": "Bulk",
                }
            )
            document["unit_names"].append(
                {
                    "unit_id": SACK_ID,
                    "locale_id": locale,
                    "name": "quintal",
                    "plural": None,
                }
            )
        for row in document["unit_names"]:
            if row["unit_id"] == unit_id("kg"):
                row["name"] = "kilo"
        for row in document["quantity_kind_names"]:
            if row["quantity_kind_id"] == kind_id("mass"):
                row["name"] = "Mass!"

    with pytest.raises(RuntimeError):
        run(seal(edit(build_snapshot(1), richer)), repository)
    assert dump(repository) == before


@pytest.mark.parametrize(
    ("constraint", "rule"),
    [
        ("quantity_kind_reference_fk", "RF-8"),
        ("quantity_kind_active_requires_active_reference", "RF-8"),
        ("quantity_kind_unit_linear_offset", "RF-12"),
        ("unit_ucum_code_unique", "RF-3"),
        ("unit_ucum_code_immutable", "RF-5"),
        ("some_unknown_constraint", "RNF-4"),
        (None, "RNF-4"),
    ],
)
def test_a_constraint_rejected_at_the_end_is_a_rejection_naming_the_requirement(
    constraint: str | None, rule: str
) -> None:
    repository = FakeUnitsRepository()
    repository.constraint_failure = ConstraintRejected(constraint, "23514")
    result = run(build_snapshot(1), repository)
    assert result.outcome is Outcome.REJECTED
    assert [v.rule for v in result.violations] == [rule]
    assert repository.state.snapshots == []


# --- diff


def test_the_preview_never_writes_and_lists_the_changes() -> None:
    repository = seeded()
    before, transactions = dump(repository), repository.transactions
    result = preview_snapshot(second_version(), repository, POLICY, ucum_table())
    assert result.outcome is Outcome.INCORPORATED and result.diff is not None
    text = "\n".join(result.diff.lines())
    assert "oz" in text and "inactive" in text
    assert dump(repository) == before and repository.transactions == transactions
    assert repository.inspections == 1


def test_the_preview_of_an_applied_snapshot_is_a_noop_and_of_a_bad_one_is_rejected() -> None:
    repository = seeded()
    assert preview_snapshot(build_snapshot(1), repository, POLICY, ucum_table()).outcome is (
        Outcome.NOOP
    )
    bad = preview_snapshot(build_snapshot(1, codes=("mass",)), repository, POLICY, ucum_table())
    assert bad.outcome is Outcome.REJECTED and {v.rule for v in bad.violations} == {"RF-42"}
    invalid = edit(build_snapshot(2), lambda d: kind_row(d, "mass").update(code="Mass"))
    assert preview_snapshot(seal(invalid), repository, POLICY, ucum_table()).outcome is (
        Outcome.REJECTED
    )
