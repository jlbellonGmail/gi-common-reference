"""T4: reglas puras de Currency: códigos, ciclo de vida, reemplazo 0..N y localizaciones."""

import copy
import uuid
from typing import Any

import pytest

from gi_common_reference.currencies.domain.model import LocaleCatalog, LocaleInfo
from tests.fixtures.currencies import (
    EN,
    ES,
    build_snapshot,
    country_catalog,
    currency,
    currency_id,
    locale_catalog,
    names,
    provenance,
)
from tests.unit.currencies.helpers import messages, plan, published, rules

FR = str(uuid.uuid4())


def only(*codes: str, version: int = 1, **kwargs: Any) -> dict[str, Any]:
    return build_snapshot(version, codes=codes, **kwargs)


def with_currencies(codes: tuple[str, ...], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Snapshot con `rows` como monedas y los nombres de `codes`."""
    return build_snapshot(codes=codes, currencies=rows, country_currencies=[])


# --- snapshot válido ------------------------------------------------------------------------------


def test_the_default_snapshot_creates_everything_and_changes_nothing_else() -> None:
    result = plan(build_snapshot())
    assert result.ok, messages(result)
    assert len(result.new_currencies) == 15 and len(result.new_names) == 30
    assert not result.updated_currencies and not result.updated_names


def test_resubmitting_the_same_content_produces_an_empty_plan() -> None:
    document = build_snapshot()
    result = plan(document, published(document))
    assert result.ok and result.is_empty


def test_the_plan_carries_codes_exactly_as_text() -> None:
    """CL-3: `032` y `068` conservan sus ceros."""
    by_code = {c.alphabetic_code: c for c in plan(build_snapshot()).new_currencies}
    assert by_code["ARS"].numeric_code == "032"
    assert by_code["BOB"].numeric_code == "068"


# --- unidades menores (RF-4, CL-1, CL-2)


@pytest.mark.parametrize("units", [0, 2, 3, 4, None, 6])
def test_minor_units_zero_to_n_and_not_applicable_are_accepted(units: int | None) -> None:
    result = plan(with_currencies(("JPY",), [currency("JPY", minor_units=units)]))
    assert result.ok, messages(result)
    assert result.new_currencies[0].minor_units == units


@pytest.mark.parametrize("units", [-1, "2", True, False, [], {}])
def test_invalid_minor_units_are_rejected(units: Any) -> None:
    result = plan(with_currencies(("JPY",), [currency("JPY", minor_units=units)]))
    assert rules(result) == {"RF-4"}


def test_not_applicable_is_distinct_from_zero_in_the_plan() -> None:
    result = plan(
        with_currencies(
            ("XAU", "JPY"),
            [currency("XAU", minor_units=None), currency("JPY", minor_units=0)],
        )
    )
    by_code = {c.alphabetic_code: c.minor_units for c in result.new_currencies}
    assert by_code == {"XAU": None, "JPY": 0}


def test_changing_minor_units_keeps_the_id_and_shows_in_the_plan() -> None:
    """CL-10 (precedente ISK 2 → 0): se conserva el currency_id y el cambio es visible."""
    before = with_currencies(("JPY",), [currency("JPY", minor_units=2)])
    after = build_snapshot(
        2, codes=("JPY",), currencies=[currency("JPY", minor_units=0)], country_currencies=[]
    )
    result = plan(after, published(before))
    assert result.ok and not result.new_currencies
    assert [(c.currency_id, c.minor_units) for c in result.updated_currencies] == [
        (currency_id("JPY"), 0)
    ]


# --- formato de códigos (RF-4)


@pytest.mark.parametrize("code", ["ars", "AR", "ARSS", "AR1", " ARS", "ARS ", "ÁRS", "", "A-S"])
def test_malformed_alphabetic_codes_are_rejected(code: str) -> None:
    result = plan(with_currencies(("ARS",), [currency("ARS", alphabetic_code=code)]))
    assert "RF-4" in rules(result)


@pytest.mark.parametrize("code", ["32", "0032", "03a", "+32", " 32", "", "٣٢٣"])
def test_malformed_numeric_codes_are_rejected(code: str) -> None:
    result = plan(with_currencies(("ARS",), [currency("ARS", numeric_code=code)]))
    assert "RF-4" in rules(result)


def test_a_numeric_code_given_as_a_number_is_rejected() -> None:
    result = plan(with_currencies(("ARS",), [currency("ARS", numeric_code=32)]))
    assert "RF-4" in rules(result)


def test_fund_code_must_be_boolean() -> None:
    for value in ("false", None, 0):
        result = plan(with_currencies(("BOV",), [currency("BOV", fund_code=value)]))
        assert "RF-4" in rules(result)


def test_funds_and_special_units_are_accepted() -> None:
    """D-7: fondos (BOV, CHE, CLF), unidades especiales (XDR) y metales (XAU)."""
    result = plan(only("BOV", "CHE", "CHW", "CLF", "XDR", "XAU"))
    assert result.ok, messages(result)
    flags = {c.alphabetic_code: c.fund_code for c in result.new_currencies}
    assert flags == {
        "BOV": True,
        "CHE": True,
        "CHW": True,
        "CLF": True,
        "XDR": False,
        "XAU": False,
    }


# --- unicidad de códigos (RF-3, D-15)


def test_a_repeated_alphabetic_code_is_rejected_even_when_one_is_inactive() -> None:
    other = currency("USD", alphabetic_code="ARS", status="inactive")
    result = plan(with_currencies(("ARS", "USD"), [currency("ARS"), other]))
    assert "RF-3" in rules(result)


def test_a_repeated_numeric_code_among_active_is_rejected() -> None:
    other = currency("USD", numeric_code="032")
    result = plan(with_currencies(("ARS", "USD"), [currency("ARS"), other]))
    assert rules(result) == {"RF-3"}


def test_a_numeric_code_may_be_reused_by_an_active_currency_when_the_holder_is_inactive() -> None:
    """CL-11 (precedente 891: YUM → CSD)."""
    yum = currency("YUM", status="inactive")
    csd = currency("CSD")
    result = plan(with_currencies(("YUM", "CSD"), [yum, csd]))
    assert result.ok, messages(result)


def test_two_inactive_currencies_may_share_a_numeric_code() -> None:
    yum, csd = currency("YUM", status="inactive"), currency("CSD", status="inactive")
    assert plan(with_currencies(("YUM", "CSD"), [yum, csd])).ok


def test_reactivating_a_currency_whose_numeric_code_is_now_held_by_another_is_rejected() -> None:
    """RF-10: reactivar queda sujeto a RF-3."""
    before = with_currencies(("YUM", "CSD"), [currency("YUM", status="inactive"), currency("CSD")])
    after = build_snapshot(
        2,
        codes=("YUM", "CSD"),
        currencies=[currency("YUM"), currency("CSD")],
        country_currencies=[],
    )
    assert rules(plan(after, published(before))) == {"RF-3"}


def test_reactivating_a_currency_with_a_free_numeric_code_is_accepted_and_clears_replacements() -> (
    None
):
    """CL-19."""
    eur = currency("EUR")
    hrk_retired = currency("HRK", status="inactive", replacement_currency_ids=[eur["currency_id"]])
    before = with_currencies(("HRK", "EUR"), [hrk_retired, eur])
    after = build_snapshot(
        2, codes=("HRK", "EUR"), currencies=[currency("HRK"), eur], country_currencies=[]
    )
    result = plan(after, published(before))
    assert result.ok, messages(result)
    assert [
        (c.alphabetic_code, c.status, c.replacement_currency_ids) for c in result.updated_currencies
    ] == [("HRK", "active", ())]


def test_reactivating_without_clearing_the_replacements_is_rejected() -> None:
    eur = currency("EUR")
    hrk_retired = currency("HRK", status="inactive", replacement_currency_ids=[eur["currency_id"]])
    before = with_currencies(("HRK", "EUR"), [hrk_retired, eur])
    after = build_snapshot(
        2,
        codes=("HRK", "EUR"),
        currencies=[currency("HRK", replacement_currency_ids=[eur["currency_id"]]), eur],
        country_currencies=[],
    )
    assert rules(plan(after, published(before))) == {"RF-6"}


# --- códigos publicados inmutables (RF-5, D-6)


def test_changing_the_alphabetic_code_of_a_published_currency_is_rejected() -> None:
    before = only("ARS")
    after = build_snapshot(2, codes=("ARS",), currencies=[currency("ARS", alphabetic_code="ARX")])
    result = plan(after, published(before))
    assert "RF-5" in rules(result)
    assert "moneda nueva" in messages(result)


def test_changing_the_numeric_code_of_a_published_currency_is_rejected() -> None:
    before = only("ARS")
    after = build_snapshot(2, codes=("ARS",), currencies=[currency("ARS", numeric_code="999")])
    assert "RF-5" in rules(plan(after, published(before)))


def test_assigning_a_published_alphabetic_code_to_another_id_is_rejected() -> None:
    before = only("ARS")
    intruder = currency("USD", alphabetic_code="ARS", numeric_code="840")
    after = build_snapshot(
        2, codes=("ARS", "USD"), currencies=[currency("ARS"), intruder], country_currencies=[]
    )
    assert {"RF-3", "RF-5"} <= rules(plan(after, published(before)))


def test_a_redenomination_is_a_new_currency_and_the_old_one_is_retired_with_replacement() -> None:
    """D-6, CL-9, RF-11: VEF → VES."""
    before = only("VEF")
    ves = currency("VES")
    vef = currency("VEF", status="inactive", replacement_currency_ids=[ves["currency_id"]])
    after = build_snapshot(2, codes=("VEF", "VES"), currencies=[vef, ves], country_currencies=[])
    result = plan(after, published(before))
    assert result.ok, messages(result)
    assert [c.alphabetic_code for c in result.new_currencies] == ["VES"]
    assert [c.alphabetic_code for c in result.updated_currencies] == ["VEF"]
    assert result.updated_currencies[0].currency_id == currency_id("VEF")
    assert result.new_currencies[0].currency_id != currency_id("VEF")


# --- identidad y completitud (RF-2, RF-37)


@pytest.mark.parametrize("bad", ["", "not-a-uuid", "1D806402-A823-4580-9F4D-958C6E5A5354", "123"])
def test_an_invalid_currency_id_is_rejected(bad: str) -> None:
    result = plan(with_currencies(("ARS",), [currency("ARS", currency_id=bad)]))
    assert "RF-2" in rules(result)


def test_a_repeated_currency_id_is_rejected() -> None:
    rows = [currency("ARS"), currency("USD", currency_id=currency_id("ARS"))]
    assert "RF-2" in rules(plan(with_currencies(("ARS", "USD"), rows)))


def test_omitting_a_published_currency_is_rejected_and_retirement_is_status() -> None:
    before = only("ARS", "USD")
    after = build_snapshot(2, codes=("ARS",))
    result = plan(after, published(before))
    assert rules(result) == {"RF-37"}
    assert "inactive" in messages(result)
    retired = build_snapshot(
        2,
        codes=("ARS", "USD"),
        currencies=[currency("ARS"), currency("USD", status="inactive")],
        country_currencies=[],
    )
    assert plan(retired, published(before)).ok


def test_omitting_a_published_localization_is_rejected() -> None:
    before = only("ARS")
    after = build_snapshot(2, codes=("ARS",), currency_names=names("ARS")[:1])
    assert "RF-37" in rules(plan(after, published(before)))


# --- reemplazo 0..N (RF-6, D-17)


def retired(code: str, *successors: str, **kwargs: Any) -> dict[str, Any]:
    return currency(
        code,
        status="inactive",
        replacement_currency_ids=[currency_id(s) for s in successors],
        **kwargs,
    )


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_zero_one_and_many_replacements_are_accepted_and_ordered(count: int) -> None:
    """CL-18 (CSK → CZK y SKK)."""
    targets = ("CZK", "SKK", "EUR")[:count]
    codes = ("CSK", "CZK", "SKK", "EUR")
    rows = [retired("CSK", *targets), currency("CZK"), currency("SKK"), currency("EUR")]
    result = plan(with_currencies(codes, rows))
    assert result.ok, messages(result)
    csk = next(c for c in result.new_currencies if c.alphabetic_code == "CSK")
    assert csk.replacement_currency_ids == tuple(sorted(currency_id(t) for t in targets))


def test_the_order_in_the_snapshot_has_no_meaning() -> None:
    rows_a = [retired("CSK", "CZK", "SKK"), currency("CZK"), currency("SKK")]
    rows_b = [retired("CSK", "SKK", "CZK"), currency("CZK"), currency("SKK")]
    ids = [currency_id("SKK"), currency_id("CZK")]
    rows_b[0]["replacement_currency_ids"] = ids
    result_a = plan(with_currencies(("CSK", "CZK", "SKK"), rows_a))
    result_b = plan(with_currencies(("CSK", "CZK", "SKK"), rows_b))
    assert result_a.new_currencies == result_b.new_currencies
    # el estado ya publicado con otro orden no es un cambio
    assert plan(
        with_currencies(("CSK", "CZK", "SKK"), rows_b),
        published(with_currencies(("CSK", "CZK", "SKK"), rows_a)),
    ).is_empty


def test_a_replacement_on_an_active_currency_is_rejected() -> None:
    row = currency("CSK", replacement_currency_ids=[currency_id("CZK")])
    result = plan(with_currencies(("CSK", "CZK"), [row, currency("CZK")]))
    assert rules(result) == {"RF-6"}


def test_a_repeated_replacement_is_rejected() -> None:
    row = retired("CSK", "CZK")
    row["replacement_currency_ids"] = [currency_id("CZK"), currency_id("CZK")]
    assert "RF-6" in rules(plan(with_currencies(("CSK", "CZK"), [row, currency("CZK")])))


def test_a_null_replacement_element_is_rejected() -> None:
    row = retired("CSK")
    row["replacement_currency_ids"] = [None]
    assert "RF-6" in rules(plan(with_currencies(("CSK",), [row])))


def test_a_replacement_to_itself_is_rejected() -> None:
    row = retired("CSK", "CSK")
    assert "RF-6" in rules(plan(with_currencies(("CSK",), [row])))


def test_a_replacement_to_a_missing_or_malformed_currency_is_rejected() -> None:
    row = retired("CSK")
    row["replacement_currency_ids"] = [str(uuid.uuid4())]
    assert "RF-6" in rules(plan(with_currencies(("CSK",), [row])))
    row["replacement_currency_ids"] = ["nope"]
    assert "RF-6" in rules(plan(with_currencies(("CSK",), [row])))


def test_two_and_three_currency_cycles_are_rejected() -> None:
    two = [retired("CSK", "CZK"), retired("CZK", "CSK")]
    assert "RF-6" in rules(plan(with_currencies(("CSK", "CZK"), two)))
    three = [retired("CSK", "CZK"), retired("CZK", "SKK"), retired("SKK", "CSK")]
    result = plan(with_currencies(("CSK", "CZK", "SKK"), three))
    assert "ciclo" in messages(result)


def test_a_successor_may_itself_be_inactive_without_a_cycle() -> None:
    rows = [retired("CSK", "CZK"), retired("CZK", "EUR"), currency("EUR")]
    assert plan(with_currencies(("CSK", "CZK", "EUR"), rows)).ok


def test_a_diamond_is_not_a_cycle() -> None:
    rows = [
        retired("CSK", "CZK", "SKK"),
        retired("CZK", "EUR"),
        retired("SKK", "EUR"),
        currency("EUR"),
    ]
    assert plan(with_currencies(("CSK", "CZK", "SKK", "EUR"), rows)).ok


@pytest.mark.parametrize("status", ["retired", "ACTIVE", "", "not_found", "vigente"])
def test_an_invalid_status_is_rejected(status: str) -> None:
    result = plan(with_currencies(("ARS",), [currency("ARS", status=status)]))
    assert "RF-9" in rules(result)


# --- localizaciones (RF-12 a RF-16)


def test_names_in_en_and_es_are_accepted() -> None:
    result = plan(only("ARS"))
    assert {(n.locale_id, n.name) for n in result.new_names} == {
        (EN, "Argentine Peso"),
        (ES, "peso argentino"),
    }


@pytest.mark.parametrize("missing", [EN, ES])
def test_a_currency_without_a_required_locale_name_is_rejected(missing: str) -> None:
    kept = [n for n in names("ARS") if n["locale_id"] != missing]
    result = plan(build_snapshot(codes=("ARS",), currency_names=kept))
    assert rules(result) == {"RF-13"}


def test_a_name_in_an_additional_active_locale_is_accepted() -> None:
    locales = LocaleCatalog(
        1,
        (
            LocaleInfo(EN, "en", "active"),
            LocaleInfo(ES, "es", "active"),
            LocaleInfo(FR, "fr", "active"),
        ),
    )
    extra = {"currency_id": currency_id("ARS"), "locale_id": FR, "name": "peso argentin"}
    result = plan(
        build_snapshot(codes=("ARS",), currency_names=[*names("ARS"), extra]), locales=locales
    )
    assert result.ok, messages(result)


def test_a_new_name_in_an_unknown_or_inactive_locale_is_rejected() -> None:
    inactive = LocaleCatalog(
        1,
        (
            LocaleInfo(EN, "en", "active"),
            LocaleInfo(ES, "es", "active"),
            LocaleInfo(FR, "fr", "inactive"),
        ),
    )
    extra = {"currency_id": currency_id("ARS"), "locale_id": FR, "name": "peso"}
    document = build_snapshot(codes=("ARS",), currency_names=[*names("ARS"), extra])
    assert rules(plan(document, locales=inactive)) == {"RF-14"}
    unknown = {**extra, "locale_id": str(uuid.uuid4())}
    document = build_snapshot(codes=("ARS",), currency_names=[*names("ARS"), unknown])
    assert rules(plan(document)) == {"RF-14"}


def test_a_published_name_survives_its_locale_becoming_inactive() -> None:
    """RF-14: lo ya publicado se conserva y sigue resolviéndose."""
    extra = {"currency_id": currency_id("ARS"), "locale_id": FR, "name": "peso"}
    active = LocaleCatalog(
        1,
        (
            LocaleInfo(EN, "en", "active"),
            LocaleInfo(ES, "es", "active"),
            LocaleInfo(FR, "fr", "active"),
        ),
    )
    document = build_snapshot(codes=("ARS",), currency_names=[*names("ARS"), extra])
    current = published(document)
    later = LocaleCatalog(
        2,
        (
            LocaleInfo(EN, "en", "active"),
            LocaleInfo(ES, "es", "active"),
            LocaleInfo(FR, "fr", "inactive"),
        ),
    )
    assert plan(document, current, locales=later).ok
    assert plan(document, current, locales=active).ok


def test_a_required_locale_that_is_inactive_missing_or_with_another_code_rejects_the_snapshot() -> (
    None
):
    document = only("ARS")
    assert rules(plan(document, locales=locale_catalog(inactive=[ES]))) == {"RF-13"}
    assert rules(plan(document, locales=locale_catalog(missing=[EN]))) == {"RF-13"}
    swapped = LocaleCatalog(1, (LocaleInfo(EN, "fr", "active"), LocaleInfo(ES, "es", "active")))
    assert "«fr»" in messages(plan(document, locales=swapped))
    assert rules(plan(document, locales=locale_catalog(snapshot_version=None))) == {"RF-13"}


@pytest.mark.parametrize("name", ["", " ", " peso", "peso ", "\tpeso", "peso\n"])
def test_empty_or_untrimmed_names_are_rejected(name: str) -> None:
    rows = names("ARS")
    rows[0] = {**rows[0], "name": name}
    result = plan(build_snapshot(codes=("ARS",), currency_names=rows))
    assert "RF-16" in rules(result)


def test_a_repeated_pair_or_an_unknown_currency_is_rejected() -> None:
    rows = [*names("ARS"), names("ARS")[0]]
    assert "RF-12" in rules(plan(build_snapshot(codes=("ARS",), currency_names=rows)))
    ghost = {"currency_id": str(uuid.uuid4()), "locale_id": EN, "name": "Ghost"}
    rows = [*names("ARS"), ghost]
    assert "RF-12" in rules(plan(build_snapshot(codes=("ARS",), currency_names=rows)))


def test_a_name_change_is_an_update_and_there_is_no_fallback_between_locales() -> None:
    before = only("ARS")
    renamed = [
        {**n, "name": "Peso argentino" if n["locale_id"] == ES else n["name"]} for n in names("ARS")
    ]
    after = build_snapshot(2, codes=("ARS",), currency_names=renamed)
    result = plan(after, published(before))
    assert [(n.locale_id, n.name) for n in result.updated_names] == [(ES, "Peso argentino")]
    assert not result.new_names


def test_the_names_carry_only_the_name() -> None:
    """D-11: sin símbolos ni formato."""
    result = plan(only("ARS"))
    assert {f for f in result.new_names[0].__dataclass_fields__} == {
        "currency_id",
        "locale_id",
        "name",
    }


# --- contexto (RF-40, RF-41)


def test_the_declared_country_version_must_be_incorporated_and_not_later_than_current() -> None:
    document = build_snapshot(country_snapshot_version=3)
    assert "RF-41" in rules(plan(document, countries=country_catalog(versions=(1, 2))))
    ok = plan(document, countries=country_catalog(snapshot_version=3, versions=(1, 2, 3)))
    assert ok.ok, messages(ok)
    later = plan(document, countries=country_catalog(snapshot_version=2, versions=(1, 2, 3)))
    assert "RF-41" in rules(later)


def test_an_empty_countries_catalog_rejects_the_snapshot() -> None:
    result = plan(build_snapshot(), countries=country_catalog(snapshot_version=None, versions=()))
    assert rules(result) == {"RF-40"}


# --- procedencia (RF-41, D-20)


def drop_role(role: str) -> dict[str, Any]:
    base = provenance()
    base["sources"] = [s for s in base["sources"] if s["role"] != role]
    return base


@pytest.mark.parametrize("role", ["identity", "names"])
def test_the_identity_and_names_sources_are_always_required(role: str) -> None:
    result = plan(build_snapshot(catalog_provenance=drop_role(role)))
    assert rules(result) == {"RF-41"} and role in messages(result)


@pytest.mark.parametrize(
    "field", ["name", "edition", "retrieved_at", "location", "checksum", "license"]
)
def test_each_source_field_is_required(field: str) -> None:
    broken = provenance()
    broken["sources"][0][field] = ""
    assert rules(plan(build_snapshot(catalog_provenance=broken))) == {"RF-41"}
    del broken["sources"][0][field]
    assert rules(plan(build_snapshot(catalog_provenance=broken))) == {"RF-41"}


def test_unresolved_conflicts_between_sources_reject_the_snapshot() -> None:
    """RF-41: p. ej. nombre ISO ≠ CLDR, o entidad ISO sin Country inequívoco."""
    conflicted = provenance(unresolved_conflicts=[{"what": "nombre ISO distinto de CLDR (ARS)"}])
    result = plan(build_snapshot(catalog_provenance=conflicted))
    assert rules(result) == {"RF-41"} and "conflictos" in messages(result)


def test_a_missing_or_malformed_provenance_is_rejected() -> None:
    document = build_snapshot()
    document["provenance"] = None
    assert rules(plan(document)) == {"RF-41"}
    for broken in (
        {"sources": [], "unresolved_conflicts": []},
        {"sources": "x", "unresolved_conflicts": []},
    ):
        assert rules(plan(build_snapshot(catalog_provenance=broken))) == {"RF-41"}
    unknown = provenance()
    unknown["sources"].append({**unknown["sources"][0], "role": "fx"})
    assert rules(plan(build_snapshot(catalog_provenance=unknown))) == {"RF-41"}


# --- orden de los pasos (RF-39)


def test_the_first_failing_step_is_the_only_one_reported() -> None:
    """Contexto antes que identidad antes que códigos: se informa solo el primer paso que falla."""
    document = build_snapshot(codes=("ARS",))
    document["currencies"][0]["alphabetic_code"] = "ars"
    document["currencies"][0]["currency_id"] = "nope"
    result = plan(document, locales=locale_catalog(inactive=[EN]))
    assert rules(result) == {"RF-13"}
    result = plan(document)
    assert rules(result) == {"RF-2"}


def test_all_violations_of_the_failing_step_are_reported_together() -> None:
    rows = [currency("ARS", alphabetic_code="ars"), currency("USD", numeric_code="84")]
    result = plan(with_currencies(("ARS", "USD"), rows))
    assert len(result.violations) == 2 and rules(result) == {"RF-4"}


def test_planning_does_not_mutate_its_inputs() -> None:
    document = build_snapshot()
    before = copy.deepcopy(document)
    plan(document)
    assert document == before


def test_the_country_catalog_helper_lists_the_countries_the_fixtures_use() -> None:
    assert len(country_catalog().countries) == 14
