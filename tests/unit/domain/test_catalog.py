"""T6: validación del catálogo contra el estado vigente y el artefacto IANA
(RF-3, RF-4, RF-5, RF-15–RF-19, RF-22, RF-26, RF-27, RF-28)."""

import uuid

import pytest

from gi_common_reference.locales.domain.catalog import (
    CatalogPlan,
    locale_records,
    plan_catalog_changes,
)
from gi_common_reference.locales.domain.iana import IanaRegistry, parse_registry
from gi_common_reference.locales.domain.model import LocaleRecord
from tests.fixtures.snapshots import build_snapshot, locale_id


def lang(
    code: str, deprecated: str | None = None, preferred: str | None = None, scope: str | None = None
) -> str:
    lines = ["Type: language", f"Subtag: {code}", f"Description: {code}"]
    if deprecated:
        lines.append(f"Deprecated: {deprecated}")
    if preferred:
        lines.append(f"Preferred-Value: {preferred}")
    if scope:
        lines.append(f"Scope: {scope}")
    return "\n".join(lines) + "\n"


def registry(*entries: str) -> IanaRegistry:
    return parse_registry("File-Date: 2026-09-01\n%%\n" + "%%\n".join(entries))


def rec(
    code: str,
    *,
    status: str = "active",
    deprecated: bool = False,
    replacement: str | None = None,
    id: str | None = None,
) -> LocaleRecord:
    return LocaleRecord(
        locale_id=locale_id(code) if id is None else id,
        code=code,
        status=status,
        iana_deprecated=deprecated,
        replacement_locale_id=replacement,
    )


def dep(code: str, replacement_code: str | None = None, *, id: str | None = None) -> LocaleRecord:
    """Locale deprecado: `inactive`, deprecado y con `replacement` hacia otro código."""
    return rec(
        code,
        status="inactive",
        deprecated=True,
        replacement=locale_id(replacement_code) if replacement_code else None,
        id=id,
    )


BASE = registry(lang("es"), lang("en"), lang("pt"), lang("he"))
IW_DEPRECATED = registry(lang("es"), lang("he"), lang("iw", "1989-01-01", "he"))


def rules(plan: CatalogPlan) -> set[str]:
    return {v.rule for v in plan.violations}


def messages(plan: CatalogPlan) -> str:
    return " | ".join(v.message for v in plan.violations)


# --- válido y plan de cambios ------------------------------------------------------------------


def test_first_catalog_creates_every_locale() -> None:
    plan = plan_catalog_changes([rec("es"), rec("en")], [], BASE)
    assert plan.ok and plan.violations == ()
    assert plan.new_locales == (rec("es"), rec("en"))
    assert plan.metadata_updates == ()


def test_same_catalog_again_changes_nothing() -> None:
    catalog = [rec("es"), rec("en")]
    plan = plan_catalog_changes(catalog, catalog, BASE)
    assert plan.ok and plan.new_locales == () and plan.metadata_updates == ()


def test_new_locale_is_added_and_published_ones_are_kept() -> None:
    plan = plan_catalog_changes([rec("es"), rec("en"), rec("pt")], [rec("es"), rec("en")], BASE)
    assert plan.ok
    assert plan.new_locales == (rec("pt"),)
    assert plan.metadata_updates == ()


def test_catalog_order_does_not_matter_for_validation() -> None:
    plan = plan_catalog_changes([rec("en"), rec("es")], [rec("es"), rec("en")], BASE)
    assert plan.ok and plan.new_locales == () and plan.metadata_updates == ()


def test_inactive_by_catalog_decision_without_deprecation_is_valid_and_is_an_update() -> None:
    """RF-5: `inactive` no implica deprecación; el locale sigue resoluble y sin `replacement`."""
    plan = plan_catalog_changes([rec("es", status="inactive")], [rec("es")], BASE)
    assert plan.ok
    assert plan.metadata_updates == (rec("es", status="inactive"),)


def test_reactivating_an_inactive_locale_is_a_metadata_update() -> None:
    plan = plan_catalog_changes([rec("es")], [rec("es", status="inactive")], BASE)
    assert plan.ok and plan.metadata_updates == (rec("es"),)


def test_planning_does_not_modify_its_inputs() -> None:
    incoming, current = [rec("es"), rec("pt")], [rec("es")]
    before = (list(incoming), list(current))
    plan_catalog_changes(incoming, current, BASE)
    assert (incoming, current) == before


def test_records_are_read_from_the_snapshot_document() -> None:
    document = build_snapshot(1, codes=("es", "he"))
    assert locale_records(document) == [rec("es"), rec("he")]


def test_records_tolerate_missing_ids_so_the_domain_can_reject_them() -> None:
    document = {"locales": [{"code": "es", "status": "active", "iana_deprecated": False}]}
    (record,) = locale_records(document)
    assert record.locale_id == "" and record.replacement_locale_id is None


# --- RF-28: minúsculas en todos los códigos, nuevos y publicados --------------------------------


def test_published_locale_arriving_as_He_rejects_the_whole_snapshot() -> None:
    current = [rec("es"), rec("he")]
    incoming = [rec("es"), rec("He", id=locale_id("he"))]
    plan = plan_catalog_changes(incoming, current, BASE)
    assert rules(plan) == {"RF-28"}
    assert "He" in messages(plan)
    assert plan.new_locales == () and plan.metadata_updates == ()


def test_published_locale_arriving_as_ES_rejects_the_whole_snapshot() -> None:
    current = [rec("es"), rec("en")]
    incoming = [rec("ES", id=locale_id("es")), rec("en")]
    plan = plan_catalog_changes(incoming, current, BASE)
    assert rules(plan) == {"RF-28"}
    assert not plan.ok and plan.new_locales == ()


def test_published_locale_arriving_as_Pt_is_rejected_and_not_normalized() -> None:
    plan = plan_catalog_changes([rec("Pt", id=locale_id("pt"))], [rec("pt")], BASE)
    assert rules(plan) == {"RF-28"}


def test_new_locale_with_uppercase_code_is_rejected() -> None:
    plan = plan_catalog_changes([rec("es"), rec("PT")], [rec("es")], BASE)
    assert rules(plan) == {"RF-28"}


def test_rf28_is_checked_before_the_comparison_with_the_current_state() -> None:
    """Con `ES` y un locale omitido solo se reporta RF-28: los demás pasos no corren."""
    plan = plan_catalog_changes([rec("ES", id=locale_id("es"))], [rec("es"), rec("en")], BASE)
    assert rules(plan) == {"RF-28"}


def test_every_uppercase_code_is_reported() -> None:
    plan = plan_catalog_changes([rec("ES"), rec("En"), rec("pt")], [], BASE)
    assert len(plan.violations) == 2


def test_lowercase_published_codes_pass_rf28() -> None:
    assert plan_catalog_changes([rec("es"), rec("he")], [rec("es"), rec("he")], BASE).ok


# --- RF-15: ningún locale publicado puede faltar -------------------------------------------------


def test_omitting_a_published_locale_is_rejected() -> None:
    plan = plan_catalog_changes([rec("es")], [rec("es"), rec("en")], BASE)
    assert rules(plan) == {"RF-15"}
    assert "en" in messages(plan)


def test_empty_snapshot_over_a_published_catalog_is_rejected() -> None:
    plan = plan_catalog_changes([], [rec("es")], BASE)
    assert rules(plan) == {"RF-15"}


def test_omission_is_rejected_even_when_the_locale_is_inactive() -> None:
    plan = plan_catalog_changes([rec("es")], [rec("es"), rec("en", status="inactive")], BASE)
    assert rules(plan) == {"RF-15"}


# --- RF-16: id ↔ código publicado se conserva ---------------------------------------------------


def test_changing_the_code_of_a_published_id_is_rejected() -> None:
    plan = plan_catalog_changes([rec("en", id=locale_id("es"))], [rec("es")], BASE)
    assert "RF-16" in rules(plan)


def test_assigning_a_new_id_to_a_published_code_is_rejected() -> None:
    other = str(uuid.uuid4())
    plan = plan_catalog_changes([rec("es", id=other)], [rec("es")], BASE)
    assert "RF-16" in rules(plan)
    assert "RF-15" in rules(plan)  # el id publicado además desapareció


def test_swapping_the_codes_of_two_published_ids_is_rejected() -> None:
    current = [rec("es"), rec("en")]
    incoming = [rec("en", id=locale_id("es")), rec("es", id=locale_id("en"))]
    plan = plan_catalog_changes(incoming, current, BASE)
    assert rules(plan) == {"RF-16"}
    assert len(plan.violations) == 2


def test_assigning_a_published_code_to_another_published_id_is_rejected() -> None:
    current = [rec("es"), rec("en")]
    incoming = [rec("es"), rec("es", id=locale_id("en"))]
    plan = plan_catalog_changes(incoming, current, BASE)
    assert "RF-16" in rules(plan)


# --- RF-17: ids de locales nuevos ---------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["", " ", "abc", "not-a-uuid", str(uuid.uuid4()).upper()])
def test_new_locale_without_a_valid_lowercase_uuid_is_rejected(bad_id: str) -> None:
    plan = plan_catalog_changes([rec("es"), rec("pt", id=bad_id)], [rec("es")], BASE)
    assert rules(plan) == {"RF-17"}


def test_new_locale_with_the_nil_looking_but_valid_uuid_shape_is_accepted() -> None:
    plan = plan_catalog_changes([rec("pt", id=str(uuid.uuid4()))], [], BASE)
    assert plan.ok


def test_repeated_new_id_is_rejected() -> None:
    same = str(uuid.uuid4())
    plan = plan_catalog_changes([rec("es", id=same), rec("en", id=same)], [], BASE)
    assert "RF-17" in rules(plan)
    assert same in messages(plan)


def test_id_already_used_in_the_catalog_by_a_new_locale_is_rejected() -> None:
    plan = plan_catalog_changes([rec("es"), rec("pt", id=locale_id("es"))], [rec("es")], BASE)
    assert {"RF-16", "RF-17"} <= rules(plan)


def test_new_ids_unknown_to_the_catalog_are_accepted() -> None:
    plan = plan_catalog_changes([rec("es"), rec("pt")], [rec("es")], BASE)
    assert plan.ok


# --- RF-3 / RF-4: códigos nuevos y duplicados ----------------------------------------------------


def test_new_code_that_is_not_the_preferred_form_is_rejected() -> None:
    plan = plan_catalog_changes([rec("es"), rec("iw")], [], IW_DEPRECATED)
    assert rules(plan) == {"RF-4"}
    assert "iw" in messages(plan)


def test_two_equal_new_codes_are_rejected() -> None:
    plan = plan_catalog_changes([rec("es"), rec("es", id=str(uuid.uuid4()))], [], BASE)
    assert "RF-4" in rules(plan)


def test_iw_and_he_as_new_locales_in_the_same_snapshot_reject_iw() -> None:
    incoming = [rec("he"), dep("iw", "he")]
    plan = plan_catalog_changes(incoming, [], IW_DEPRECATED)
    assert rules(plan) == {"RF-4"}
    assert "iw" in messages(plan) and "he" not in messages(plan).replace("iw", "")


@pytest.mark.parametrize("code", ["spa", "eng", "ger", "zz", "und", "mul", "qaa", "es-ar", "e"])
def test_new_codes_that_break_the_publication_rules_are_rejected(code: str) -> None:
    reg = parse_registry(
        "File-Date: 2026-09-01\n%%\n"
        + lang("es")
        + "%%\n"
        + lang("und", scope="special")
        + "%%\n"
        + lang("mul", scope="special")
        + "%%\nType: language\nSubtag: qaa..qtz\nScope: private-use\n"
    )
    plan = plan_catalog_changes([rec("es"), rec(code)], [rec("es")], reg)
    assert "RF-4" in rules(plan)


def test_new_code_with_region_and_uppercase_is_rejected_by_rf28_first() -> None:
    plan = plan_catalog_changes([rec("es"), rec("es-AR")], [rec("es")], BASE)
    assert rules(plan) == {"RF-28"}


def test_rules_of_publication_are_not_reapplied_to_published_locales() -> None:
    """RF-26: un código publicado que luego se depreca no se vuelve a exigir como preferido."""
    current = [rec("es"), rec("iw")]
    incoming = [rec("es"), dep("iw", "he"), rec("he")]
    plan = plan_catalog_changes(incoming, current, IW_DEPRECATED)
    assert plan.ok


def test_duplicated_published_code_in_the_snapshot_is_rejected() -> None:
    plan = plan_catalog_changes([rec("es"), rec("es")], [rec("es")], BASE)
    assert "RF-3" in rules(plan)


def test_duplicated_published_id_in_the_snapshot_is_rejected() -> None:
    plan = plan_catalog_changes([rec("es"), rec("es")], [rec("es")], BASE)
    assert "RF-3" in rules(plan)


# --- RF-18 / RF-19: iw publicado y deprecado después; `he` nuevo --------------------------------


def test_published_iw_later_deprecated_becomes_inactive_with_replacement_to_new_he() -> None:
    current = [rec("es"), rec("iw")]
    incoming = [rec("es"), dep("iw", "he"), rec("he")]
    plan = plan_catalog_changes(incoming, current, IW_DEPRECATED)
    assert plan.ok
    assert plan.new_locales == (rec("he"),)
    assert plan.metadata_updates == (dep("iw", "he"),)
    (update,) = plan.metadata_updates
    assert update.locale_id == locale_id("iw") and update.code == "iw"


def test_he_published_in_an_earlier_snapshot_is_enough_for_the_replacement() -> None:
    current = [rec("es"), rec("iw"), rec("he")]
    incoming = [rec("es"), dep("iw", "he"), rec("he")]
    plan = plan_catalog_changes(incoming, current, IW_DEPRECATED)
    assert plan.ok and plan.new_locales == ()
    assert plan.metadata_updates == (dep("iw", "he"),)


def test_snapshot_without_he_is_rejected_because_the_replacement_has_no_target() -> None:
    current = [rec("es"), rec("iw")]
    incoming = [rec("es"), dep("iw")]
    plan = plan_catalog_changes(incoming, current, IW_DEPRECATED)
    assert rules(plan) == {"RF-22"}
    assert "he" in messages(plan)


def test_replacement_is_not_created_implicitly() -> None:
    current = [rec("iw")]
    plan = plan_catalog_changes([dep("iw", "he")], current, IW_DEPRECATED)
    assert not plan.ok and plan.new_locales == ()


# --- cadena A → B → C (RFC 5646 §3.1.7) ---------------------------------------------------------

CHAIN_V1 = registry(lang("xa", "2020-01-01", "xb"), lang("xb"))
CHAIN_V2 = registry(
    lang("xa", "2020-01-01", "xc"), lang("xb", "2026-01-01", "xc"), lang("xc"), lang("es")
)


def test_chain_updates_a_to_c_and_b_to_c() -> None:
    current = [dep("xa", "xb"), rec("xb")]
    incoming = [dep("xa", "xc"), dep("xb", "xc"), rec("xc")]
    plan = plan_catalog_changes(incoming, current, CHAIN_V2)
    assert plan.ok
    assert plan.new_locales == (rec("xc"),)
    assert set(plan.metadata_updates) == {dep("xa", "xc"), dep("xb", "xc")}


def test_chain_keeping_a_to_b_is_rejected() -> None:
    current = [dep("xa", "xb"), rec("xb")]
    incoming = [dep("xa", "xb"), dep("xb", "xc"), rec("xc")]
    plan = plan_catalog_changes(incoming, current, CHAIN_V2)
    assert rules(plan) == {"RF-26"}
    assert "xa" in messages(plan)


def test_chain_before_the_second_deprecation_is_valid_with_a_to_b() -> None:
    current = [rec("xa"), rec("xb")]
    incoming = [dep("xa", "xb"), rec("xb")]
    assert plan_catalog_changes(incoming, current, CHAIN_V1).ok


# --- RF-26 / RF-27: coherencia con el artefacto --------------------------------------------------


def test_deprecated_without_preferred_value_is_inactive_without_replacement() -> None:
    reg = registry(lang("sh", "2000-02-18"), lang("es"))
    plan = plan_catalog_changes([rec("es"), dep("sh")], [rec("es"), rec("sh")], reg)
    assert plan.ok
    assert plan.metadata_updates == (dep("sh"),)


def test_new_locale_may_be_born_deprecated_without_preferred_value() -> None:
    reg = registry(lang("sh", "2000-02-18"), lang("es"))
    assert plan_catalog_changes([rec("es"), dep("sh")], [rec("es")], reg).ok


def test_replacement_where_the_artifact_declares_none_is_rejected() -> None:
    reg = registry(lang("sh", "2000-02-18"), lang("es"))
    incoming = [
        rec("es"),
        rec("sh", status="inactive", deprecated=True, replacement=locale_id("es")),
    ]
    plan = plan_catalog_changes(incoming, [rec("es"), rec("sh")], reg)
    assert rules(plan) == {"RF-26"}


def test_deprecated_but_active_is_rejected() -> None:
    incoming = [
        rec("es"),
        rec("iw", status="active", deprecated=True, replacement=locale_id("he")),
        rec("he"),
    ]
    plan = plan_catalog_changes(incoming, [rec("es"), rec("iw")], IW_DEPRECATED)
    assert rules(plan) == {"RF-27"}


def test_artifact_deprecation_with_flag_false_and_active_reports_rf26_and_rf27() -> None:
    incoming = [rec("es"), rec("iw"), rec("he")]
    plan = plan_catalog_changes(incoming, [rec("es"), rec("iw")], IW_DEPRECATED)
    assert rules(plan) == {"RF-26", "RF-27"}


def test_flag_deprecated_but_artifact_declares_none_is_rejected() -> None:
    incoming = [rec("es", status="inactive", deprecated=True)]
    plan = plan_catalog_changes(incoming, [rec("es")], BASE)
    assert rules(plan) == {"RF-26"}


def test_replacement_different_from_the_artifact_is_rejected() -> None:
    incoming = [
        rec("es"),
        rec("he"),
        rec("iw", status="inactive", deprecated=True, replacement=locale_id("es")),
    ]
    plan = plan_catalog_changes(incoming, [rec("es"), rec("iw"), rec("he")], IW_DEPRECATED)
    assert rules(plan) == {"RF-26"}


def test_missing_replacement_when_the_artifact_declares_one_is_rejected() -> None:
    incoming = [rec("es"), rec("he"), dep("iw")]
    plan = plan_catalog_changes(incoming, [rec("es"), rec("iw"), rec("he")], IW_DEPRECATED)
    assert rules(plan) == {"RF-26"}


def test_published_code_absent_from_the_artifact_is_rejected() -> None:
    plan = plan_catalog_changes(
        [rec("es"), rec("en")], [rec("es"), rec("en")], registry(lang("es"))
    )
    assert rules(plan) == {"RF-26"}
    assert "en" in messages(plan)


def test_published_code_registered_with_another_type_is_rejected() -> None:
    reg = parse_registry("File-Date: 2026-09-01\n%%\nType: extlang\nSubtag: aao\nPrefix: ar\n")
    plan = plan_catalog_changes([rec("aao")], [rec("aao")], reg)
    assert rules(plan) == {"RF-26"}


def test_invalid_status_is_rejected() -> None:
    plan = plan_catalog_changes([rec("es", status="retired")], [rec("es")], BASE)
    assert rules(plan) == {"RF-5"}


# --- RF-22: replacement ------------------------------------------------------------------------


def test_replacement_to_an_unknown_id_is_rejected() -> None:
    incoming = [rec("es"), dep("iw")]
    incoming[1] = rec("iw", status="inactive", deprecated=True, replacement=str(uuid.uuid4()))
    plan = plan_catalog_changes(incoming, [rec("es"), rec("iw")], IW_DEPRECATED)
    assert rules(plan) == {"RF-22"}


def test_replacement_to_an_unknown_id_while_the_target_exists_mismatches_the_artifact() -> None:
    bad = rec("iw", status="inactive", deprecated=True, replacement=str(uuid.uuid4()))
    plan = plan_catalog_changes(
        [rec("es"), rec("he"), bad], [rec("es"), rec("iw"), rec("he")], IW_DEPRECATED
    )
    assert rules(plan) == {"RF-26"}


def test_replacement_to_itself_is_rejected_even_if_the_artifact_says_so() -> None:
    reg = registry(lang("xa", "2020-01-01", "xa"))
    plan = plan_catalog_changes([dep("xa", "xa")], [rec("xa")], reg)
    assert rules(plan) == {"RF-22"}
    assert "sí mismo" in messages(plan)


def test_replacement_to_itself_against_an_artifact_that_says_otherwise_is_rejected() -> None:
    bad = rec("iw", status="inactive", deprecated=True, replacement=locale_id("iw"))
    plan = plan_catalog_changes(
        [rec("es"), rec("he"), bad], [rec("es"), rec("iw"), rec("he")], IW_DEPRECATED
    )
    assert not plan.ok and "RF-26" in rules(plan)


def test_replacement_cycle_is_rejected() -> None:
    reg = registry(lang("xa", "2020-01-01", "xb"), lang("xb", "2021-01-01", "xa"))
    incoming = [dep("xa", "xb"), dep("xb", "xa")]
    plan = plan_catalog_changes(incoming, [rec("xa"), rec("xb")], reg)
    assert rules(plan) == {"RF-22"}
    assert "ciclo" in messages(plan)
    assert len(plan.violations) == 1


def test_longer_cycle_is_rejected() -> None:
    reg = registry(
        lang("xa", "2020-01-01", "xb"),
        lang("xb", "2020-01-01", "xc"),
        lang("xc", "2020-01-01", "xa"),
    )
    incoming = [dep("xa", "xb"), dep("xb", "xc"), dep("xc", "xa")]
    plan = plan_catalog_changes(incoming, [rec("xa"), rec("xb"), rec("xc")], reg)
    assert rules(plan) == {"RF-22"} and len(plan.violations) == 1


def test_replacement_chain_without_a_cycle_is_valid() -> None:
    reg = registry(lang("xa", "2020-01-01", "xb"), lang("xb", "2021-01-01", "xc"), lang("xc"))
    incoming = [dep("xa", "xb"), dep("xb", "xc"), rec("xc")]
    assert plan_catalog_changes(incoming, [rec("xa"), rec("xb"), rec("xc")], reg).ok


# --- orden de los pasos ------------------------------------------------------------------------


def test_the_first_failing_step_is_the_only_one_reported() -> None:
    """RF-15 (identidad) se reporta; RF-26 (artefacto) no, porque el paso anterior ya falló."""
    incoming = [rec("es"), rec("zz", id=str(uuid.uuid4()))]
    plan = plan_catalog_changes(incoming, [rec("es"), rec("en")], BASE)
    assert "RF-15" in rules(plan) and "RF-4" in rules(plan)
    assert "RF-26" not in rules(plan)


def test_a_rejected_plan_carries_no_changes() -> None:
    plan = plan_catalog_changes([rec("es"), rec("pt")], [rec("es"), rec("en")], BASE)
    assert not plan.ok
    assert plan.new_locales == () and plan.metadata_updates == ()


# --- RF-33: un Preferred-Value en línea de continuación se comporta como uno en la misma línea ---


def test_a_preferred_value_on_a_continuation_line_is_accepted_like_one_on_the_same_line() -> None:
    continued = parse_registry(
        "File-Date: 2026-09-01\n%%\n"
        "Type: language\nSubtag: es\n%%\n"
        "Type: language\nSubtag: he\n%%\n"
        "Type: language\nSubtag: iw\nDeprecated:\n  1989-01-01\nPreferred-Value:\n  he\n"
    )
    assert continued.language_aliases() == {"iw": "he"}
    current = [rec("es"), rec("iw")]
    incoming = [rec("es"), dep("iw", "he"), rec("he")]
    plan = plan_catalog_changes(incoming, current, continued)
    assert plan.ok, plan.violations
    assert plan == plan_catalog_changes(incoming, current, IW_DEPRECATED)
