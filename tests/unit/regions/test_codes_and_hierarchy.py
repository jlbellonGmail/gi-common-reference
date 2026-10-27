"""T5: códigos M49, recodificación, reasignación, jerarquía y ciclo de vida (pasos 5 y 6)."""

import pytest

from gi_common_reference.regions.domain.codes import is_valid_code
from gi_common_reference.regions.domain.model import CatalogState, Reclassification, Recoding
from tests.fixtures.regions import (
    build_snapshot,
    provenance,
    reassignment,
    recoding,
    region,
    region_id,
    subregion,
    subregion_id,
)
from tests.unit.regions.helpers import messages, plan, published, rules

ALL_SUBREGIONS = ("015", "202", "419", "021")


def subregions(**changes: dict[str, object]) -> list[dict[str, object]]:
    """Las cuatro subregiones del fixture, con cambios por clave."""
    return [subregion(key, **changes.get(f"s{key}", {})) for key in ALL_SUBREGIONS]


# --- formato (RF-3, RF-17) -------------------------------------------------------------------


@pytest.mark.parametrize("code", ["002", "019", "419", "000", "999"])
def test_three_digit_codes_are_valid(code: str) -> None:
    assert is_valid_code(code)


@pytest.mark.parametrize("code", ["19", "0019", "1", "", "abc", "01a", " 019", "019 ", "٠١٩"])
def test_other_codes_are_invalid(code: str) -> None:
    assert not is_valid_code(code)


def test_a_snapshot_with_a_malformed_code_is_rejected() -> None:
    document = build_snapshot(regions=[region("002", code="19"), region("019")])
    assert rules(plan(document)) == {"RF-3"}


def test_the_code_is_optional() -> None:
    document = build_snapshot(regions=[region("002", code=None), region("019")])
    result = plan(document)
    assert result.ok, messages(result)


# --- cambio de código y recodificación (RF-22, RF-39, RF-40) -----------------------------------


@pytest.fixture
def current() -> CatalogState:
    return published(build_snapshot(1))


def test_an_undeclared_code_change_is_rejected(current: CatalogState) -> None:
    document = build_snapshot(2, subregions=subregions(s419={"code": "420"}))
    result = plan(document, current)
    assert rules(result) == {"RF-22"} and "419" in messages(result)


def test_a_declared_recoding_keeps_id_status_names_and_parent(current: CatalogState) -> None:
    document = build_snapshot(
        2,
        subregions=subregions(s419={"code": "456"}),
        recodings=[recoding("subregion", "419", "419", "456")],
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    (updated,) = result.updated_subregions
    assert updated.subregion_id == subregion_id("419") and updated.code == "456"
    assert updated.status == "active" and updated.region_id == region_id("019")
    assert result.recodings == (
        Recoding(
            "subregion",
            subregion_id("419"),
            "419",
            "456",
            provenance("M49 recodificación 419 → 456"),
        ),
    )
    assert not result.updated_subregion_names and not result.new_subregion_names
    assert not result.reclassifications


def test_a_region_can_be_recoded_too(current: CatalogState) -> None:
    document = build_snapshot(
        2,
        regions=[region("002"), region("019", code="018")],
        recodings=[recoding("region", "019", "019", "018")],
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    assert [r.code for r in result.updated_regions] == ["018"]


@pytest.mark.parametrize(
    "declaration",
    [
        recoding("subregion", "419", "419", "456", provenance={"source": ""}),
        recoding("subregion", "419", "419", "456", provenance={"reference": "x"}),
        recoding("subregion", "419", "419", "456", provenance="UN"),
        recoding("subregion", "419", "418", "456"),
    ],
)
def test_a_recoding_without_provenance_or_with_a_wrong_previous_code_is_rejected(
    current: CatalogState, declaration: dict[str, object]
) -> None:
    document = build_snapshot(
        2, subregions=subregions(s419={"code": "456"}), recodings=[declaration]
    )
    assert "RF-40" in rules(plan(document, current))


@pytest.mark.parametrize(
    "declaration",
    [
        recoding("subregion", "419", "419", "457"),  # no coincide con el código del snapshot
        recoding("subregion", "030", None, "456"),  # id no publicado
        recoding("region", "419", "419", "456"),  # id de otro tipo
    ],
)
def test_a_recoding_that_does_not_match_the_snapshot_is_rejected(
    current: CatalogState, declaration: dict[str, object]
) -> None:
    document = build_snapshot(
        2, subregions=subregions(s419={"code": "456"}), recodings=[declaration]
    )
    assert "RF-39" in rules(plan(document, current))


def test_a_recoding_without_a_real_change_is_rejected(current: CatalogState) -> None:
    document = build_snapshot(2, recodings=[recoding("subregion", "419", "419", "419")])
    assert "RF-39" in rules(plan(document, current))


def test_a_duplicated_recoding_is_rejected(current: CatalogState) -> None:
    declaration = recoding("subregion", "419", "419", "456")
    document = build_snapshot(
        2, subregions=subregions(s419={"code": "456"}), recodings=[declaration, declaration]
    )
    assert "RF-39" in rules(plan(document, current))


# --- reasignación e intercambio (RF-41, RF-42) -----------------------------------------------


def test_a_declared_swap_of_codes_is_accepted_on_the_final_state(current: CatalogState) -> None:
    document = build_snapshot(
        2,
        subregions=subregions(s419={"code": "021"}, s021={"code": "419"}),
        recodings=[
            recoding("subregion", "419", "419", "021"),
            recoding("subregion", "021", "021", "419"),
        ],
        code_reassignments=[
            reassignment("subregion", "419", "021"),
            reassignment("subregion", "021", "419"),
        ],
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    assert {s.code for s in result.updated_subregions} == {"021", "419"}
    assert len(result.recodings) == 2


def test_a_swap_without_the_reassignments_is_rejected(current: CatalogState) -> None:
    document = build_snapshot(
        2,
        subregions=subregions(s419={"code": "021"}, s021={"code": "419"}),
        recodings=[
            recoding("subregion", "419", "419", "021"),
            recoding("subregion", "021", "021", "419"),
        ],
    )
    assert rules(plan(document, current)) == {"RF-41"}


def test_reusing_a_historical_code_of_another_id_needs_a_declared_reassignment() -> None:
    current = published(
        build_snapshot(
            1, subregions=[*subregions()[:2], subregion("419", code="456"), subregion("021")]
        ),
        history=(("subregion", subregion_id("419"), "123"),),
    )
    new = subregion("030", "019", code="123")
    base = [*subregions()[:2], subregion("419", code="456"), subregion("021")]
    undeclared = build_snapshot(2, subregions=[*base, new])
    result = plan(undeclared, current)
    assert rules(result) == {"RF-41"} and "123" in messages(result)

    declared = build_snapshot(
        2, subregions=[*base, new], code_reassignments=[reassignment("subregion", "030", "123")]
    )
    result = plan(declared, current)
    assert result.ok, messages(result)


def test_taking_the_code_of_an_inactive_entity_needs_a_declared_reassignment() -> None:
    first = subregions(s419={"status": "inactive"})
    current = published(build_snapshot(1, subregions=first))
    new = subregion("030", "019", code="419")
    assert rules(plan(build_snapshot(2, subregions=[*first, new]), current)) == {"RF-41"}
    declared = build_snapshot(
        2, subregions=[*first, new], code_reassignments=[reassignment("subregion", "030", "419")]
    )
    result = plan(declared, current)
    assert result.ok, messages(result)


def test_a_reassignment_that_does_not_apply_is_rejected(current: CatalogState) -> None:
    document = build_snapshot(2, code_reassignments=[reassignment("subregion", "419", "419")])
    assert rules(plan(document, current)) == {"RF-41"}
    document = build_snapshot(
        2,
        subregions=[*subregions(), subregion("030", "019", code="555")],
        code_reassignments=[reassignment("subregion", "030", "555")],
    )
    assert rules(plan(document, current)) == {"RF-41"}


def test_a_reassignment_without_provenance_is_rejected() -> None:
    first = subregions(s419={"status": "inactive"})
    current = published(build_snapshot(1, subregions=first))
    document = build_snapshot(
        2,
        subregions=[*first, subregion("030", "019", code="419")],
        code_reassignments=[reassignment("subregion", "030", "419", provenance={"source": ""})],
    )
    assert rules(plan(document, current)) == {"RF-41"}


def test_two_active_entities_of_the_same_type_cannot_share_a_code() -> None:
    document = build_snapshot(regions=[region("002"), region("019", code="002")])
    assert "RF-3" in rules(plan(document))
    document = build_snapshot(subregions=[*subregions(), subregion("030", "019", code="419")])
    assert "RF-3" in rules(plan(document))


def test_an_active_region_and_subregion_cannot_share_a_code() -> None:
    document = build_snapshot(regions=[region("002"), region("019"), region("142", code="419")])
    result = plan(document)
    assert rules(result) == {"RF-4"} and "419" in messages(result)


def test_inactive_entities_may_share_a_code_with_an_active_one_of_the_other_type() -> None:
    document = build_snapshot(
        regions=[region("002"), region("019"), region("142", code="419", status="inactive")]
    )
    result = plan(document)
    assert result.ok, messages(result)


# --- jerarquía (RF-5, RF-6, RF-34) ------------------------------------------------------------


def test_a_subregion_must_belong_to_a_region_of_the_snapshot() -> None:
    document = build_snapshot(subregions=[subregion("030", "142")])
    assert rules(plan(document)) == {"RF-5"}


def test_a_reclassification_keeps_id_and_code_and_is_traced(current: CatalogState) -> None:
    document = build_snapshot(2, subregions=subregions(s419={"region_id": region_id("002")}))
    result = plan(document, current)
    assert result.ok, messages(result)
    (updated,) = result.updated_subregions
    assert (updated.subregion_id, updated.code) == (subregion_id("419"), "419")
    assert result.reclassifications == (
        Reclassification(subregion_id("419"), region_id("019"), region_id("002")),
    )
    assert not result.recodings


def test_a_split_creates_new_ids_and_retires_the_original_without_replacement(
    current: CatalogState,
) -> None:
    """M49 divide 419 en dos subregiones nuevas: la original queda inactive sin sucesor único."""
    new_a = subregion("005", "019", code="005")
    new_b = subregion("013", "019", code="013")
    document = build_snapshot(
        2, subregions=[*subregions(s419={"status": "inactive"}), new_a, new_b]
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    assert {s.subregion_id for s in result.new_subregions} == {
        subregion_id("005"),
        subregion_id("013"),
    }
    assert [s.status for s in result.updated_subregions] == ["inactive"]


def test_a_merge_creates_one_new_id_and_points_both_originals_to_it(current: CatalogState) -> None:
    merged = subregion("003", "019", code="003")
    document = build_snapshot(
        2,
        subregions=[
            *subregions(
                s419={"status": "inactive", "replacement_subregion_id": subregion_id("003")},
                s021={"status": "inactive", "replacement_subregion_id": subregion_id("003")},
            ),
            merged,
        ],
    )
    result = plan(document, current)
    assert result.ok, messages(result)
    assert len(result.updated_subregions) == 2 and len(result.new_subregions) == 1


def test_an_area_retired_without_successor_stays_resolvable(current: CatalogState) -> None:
    document = build_snapshot(2, subregions=subregions(s021={"status": "inactive"}))
    result = plan(document, current)
    assert result.ok, messages(result)


# --- ciclo de vida (RF-7, RF-27, RF-36) -------------------------------------------------------


def test_status_outside_the_common_convention_is_rejected() -> None:
    document = build_snapshot(regions=[region("002", status="deprecated"), region("019")])
    assert "RF-7" in rules(plan(document))


@pytest.mark.parametrize(
    "changes",
    [
        {"s419": {"replacement_subregion_id": subregion_id("021")}},  # en una active
        {"s419": {"status": "inactive", "replacement_subregion_id": subregion_id("419")}},
        {"s419": {"status": "inactive", "replacement_subregion_id": subregion_id("999")}},
        {"s419": {"status": "inactive", "replacement_subregion_id": region_id("019")}},
        {
            "s419": {"status": "inactive", "replacement_subregion_id": subregion_id("021")},
            "s021": {"status": "inactive", "replacement_subregion_id": subregion_id("419")},
        },
    ],
    ids=["active", "self", "missing", "other-type", "cycle"],
)
def test_invalid_replacements_are_rejected(changes: dict[str, dict[str, object]]) -> None:
    result = plan(build_snapshot(subregions=subregions(**changes)))
    assert rules(result) == {"RF-27"}, messages(result)


def test_an_invalid_region_replacement_is_rejected() -> None:
    document = build_snapshot(
        regions=[
            region("002", status="inactive", replacement_region_id=subregion_id("015")),
            region("019"),
        ],
        subregions=[subregion("419"), subregion("021")],
    )
    assert rules(plan(document)) == {"RF-27"}


def test_an_inactive_region_with_an_active_subregion_is_rejected(current: CatalogState) -> None:
    document = build_snapshot(2, regions=[region("002", status="inactive"), region("019")])
    result = plan(document, current)
    assert rules(result) == {"RF-36"}
    retired = build_snapshot(
        2,
        regions=[region("002", status="inactive"), region("019")],
        subregions=subregions(s015={"status": "inactive"}, s202={"status": "inactive"}),
    )
    result = plan(retired, current)
    assert result.ok, messages(result)
