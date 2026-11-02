"""T7: consultas de Currency (RF-15, RF-22 a RF-32, RF-48 a RF-50, CL-12, CL-15, CL-24, CL-25)."""

from datetime import date
from typing import Any

import pytest

from gi_common_reference.currencies.application.queries import (
    LookupStatus,
    Validation,
    countries_of_currency,
    currencies_of_country,
    get_catalog_version,
    get_currency_by_code,
    get_currency_by_id,
    history_of_country,
    history_of_currency,
    list_currencies,
    validate_currency,
)
from gi_common_reference.currencies.domain.ports import ReaderUnavailable
from tests.fixtures.currencies import (
    EN,
    ES,
    build_snapshot,
    country_id,
    currency_id,
    transition_snapshot,
)
from tests.fixtures.currency_reader import FR, FakeClock, InMemoryCurrencyReader

D = date
TODAY = FakeClock(D(2026, 11, 1))


def reader(version: int = 1, transitioned: bool = False) -> InMemoryCurrencyReader:
    return InMemoryCurrencyReader(
        transition_snapshot(version) if transitioned else build_snapshot(version)
    )


def codes(listing: Any) -> list[str]:
    """Códigos alfabéticos de un listado de monedas o de asociaciones."""
    views = [item.currency if hasattr(item, "association") else item for item in listing.items]
    return [view.record.alphabetic_code for view in views]


# --- por identidad


def test_resolving_an_existing_id_returns_the_currency_with_its_status() -> None:
    result = get_currency_by_id(reader(), currency_id("ARS"), EN)
    assert result.status is LookupStatus.FOUND and result.snapshot_version == 1
    assert result.item is not None
    record = result.item.record
    assert (record.alphabetic_code, record.numeric_code, record.minor_units) == ("ARS", "032", 2)
    assert (record.status, record.fund_code, record.replacement_currency_ids) == (
        "active",
        False,
        (),
    )
    assert result.item.name == "Argentine Peso"


def test_names_in_en_and_es_and_none_without_locale_or_translation() -> None:
    """CA-16, RF-15: sin fallback entre locales."""
    r = reader()
    assert get_currency_by_id(r, currency_id("ARS"), ES).item.name == "peso argentino"  # type: ignore[union-attr]
    assert get_currency_by_id(r, currency_id("ARS")).item.name is None  # type: ignore[union-attr]
    untranslated = get_currency_by_id(r, currency_id("ARS"), FR)
    assert untranslated.status is LookupStatus.FOUND and untranslated.item.name is None  # type: ignore[union-attr]


def test_a_retired_currency_still_resolves_with_status_inactive() -> None:
    """CL-8, CA-22."""
    result = get_currency_by_id(reader(2, transitioned=True), currency_id("HRK"), EN)
    assert result.status is LookupStatus.FOUND
    assert result.item.record.status == "inactive"  # type: ignore[union-attr]
    assert result.item.record.replacement_currency_ids == (currency_id("EUR"),)  # type: ignore[union-attr]


def test_an_unknown_id_is_not_found_and_a_malformed_one_is_a_validation_error() -> None:
    r = reader()
    missing = get_currency_by_id(r, "00000000-0000-4000-8000-000000000000")
    assert (missing.status, missing.error) == (LookupStatus.NOT_FOUND, "currency_not_found")
    for bad in ("", "nope", "123", currency_id("ARS") + "0", " " + currency_id("ARS")):
        result = get_currency_by_id(r, bad)
        assert (result.status, result.error) == (LookupStatus.INVALID, "invalid_currency_id")


def test_an_uppercase_uuid_resolves_to_the_same_record() -> None:
    r = reader()
    lower = get_currency_by_id(r, currency_id("USD"))
    upper = get_currency_by_id(r, currency_id("USD").upper())
    assert lower.item == upper.item and lower.item is not None


def test_an_unknown_or_malformed_locale_is_a_validation_error_not_not_found() -> None:
    r = reader()
    unknown = get_currency_by_id(r, currency_id("ARS"), "00000000-0000-4000-8000-000000000000")
    assert (unknown.status, unknown.error) == (LookupStatus.INVALID, "unknown_locale")
    malformed = get_currency_by_id(r, currency_id("ARS"), "es")
    assert (malformed.status, malformed.error) == (LookupStatus.INVALID, "invalid_locale_id")
    missing_and_bad_locale = get_currency_by_id(r, "00000000-0000-4000-8000-000000000000", "es")
    assert missing_and_bad_locale.status is LookupStatus.INVALID


# --- por código alfabético


@pytest.mark.parametrize("code", ["USD", "usd", "Usd", "uSD"])
def test_code_resolution_ignores_case_and_returns_the_same_record_as_the_id(code: str) -> None:
    """CA-4."""
    r = reader()
    by_code = get_currency_by_code(r, code, EN)
    by_id = get_currency_by_id(r, currency_id("USD"), EN)
    assert by_code.status is LookupStatus.FOUND and by_code.item == by_id.item


@pytest.mark.parametrize(
    "code", [" USD", "USD ", "US", "US$", "", "USDD", "12A", "ÜSD", "U-D", "\nUSD"]
)
def test_malformed_codes_are_validation_errors(code: str) -> None:
    """CL-12."""
    result = get_currency_by_code(reader(), code)
    assert (result.status, result.error) == (LookupStatus.INVALID, "invalid_code")


def test_a_well_formed_unknown_code_is_not_found_and_a_retired_code_still_resolves() -> None:
    r = reader(2, transitioned=True)
    assert get_currency_by_code(r, "ZZZ").status is LookupStatus.NOT_FOUND
    hrk = get_currency_by_code(r, "hrk")
    assert hrk.status is LookupStatus.FOUND and hrk.item.record.status == "inactive"  # type: ignore[union-attr]


def test_numeric_resolution_does_not_exist_in_v1_but_the_number_is_published() -> None:
    """D-12, CA-23: `032` no es una clave de resolución, solo un atributo."""
    result = get_currency_by_code(reader(), "032")
    assert result.status is LookupStatus.INVALID
    assert get_currency_by_code(reader(), "ARS").item.record.numeric_code == "032"  # type: ignore[union-attr]


def test_ars_usd_and_eur_resolve() -> None:
    """Aceptación mínima: resolver ARS, USD y EUR."""
    r = reader()
    found = {c: get_currency_by_code(r, c, ES).item for c in ("ARS", "USD", "EUR")}
    assert all(item is not None for item in found.values())
    assert {c: i.name for c, i in found.items() if i is not None} == {
        "ARS": "peso argentino",
        "USD": "dólar estadounidense",
        "EUR": "euro",
    }


# --- listado


def test_the_default_list_has_only_active_currencies_in_binary_code_order() -> None:
    """RF-27."""
    result = list_currencies(reader(2, transitioned=True))
    assert "HRK" not in codes(result)
    assert codes(result) == sorted(codes(result))
    assert len(result.items) == 14


def test_inactive_currencies_and_funds_are_options() -> None:
    r = reader(2, transitioned=True)
    assert "HRK" in codes(list_currencies(r, include_inactive=True))
    no_funds = codes(list_currencies(r, exclude_funds=True))
    assert not {"BOV", "CHE", "CHW", "CLF"} & set(no_funds)
    assert {"BOB", "CHF"} <= set(no_funds)


def test_the_list_accepts_a_locale_and_validates_it() -> None:
    r = reader()
    listing = list_currencies(r, locale_id=ES)
    assert all(v.name for v in listing.items)
    assert all(v.name is None for v in list_currencies(r, locale_id=FR).items)
    assert list_currencies(r, locale_id="nope").status is LookupStatus.INVALID


# --- validación y versión


def test_validation_returns_active_inactive_and_not_found_never_a_status() -> None:
    """CA-6, RF-28."""
    r = reader(2, transitioned=True)
    results = {
        "ars": validate_currency(r, currency_id("ARS")),
        "hrk": validate_currency(r, currency_id("HRK")),
        "ghost": validate_currency(r, "00000000-0000-4000-8000-000000000000"),
    }
    assert results["ars"].item is Validation.ACTIVE
    assert results["hrk"].item is Validation.INACTIVE
    assert results["ghost"].item is Validation.NOT_FOUND
    assert results["ghost"].status is LookupStatus.FOUND  # una respuesta, no un error
    assert validate_currency(r, "nope").status is LookupStatus.INVALID
    stored = {c.status for c in r.currencies.values()}
    assert "not_found" not in stored


def test_the_catalog_version_is_the_applied_one_and_none_when_empty() -> None:
    assert get_catalog_version(reader(7)) == 7
    assert get_catalog_version(InMemoryCurrencyReader()) is None


# --- países de una moneda y monedas de un país


def test_panama_has_two_simultaneous_currencies() -> None:
    """CA-17, CL-21."""
    result = currencies_of_country(reader(), TODAY, country_id("PA"))
    assert result.status is LookupStatus.FOUND and codes(result) == ["PAB", "USD"]


def test_a_country_without_currency_returns_an_empty_list_and_an_unknown_one_not_found() -> None:
    """CL-6, CA-7."""
    r = reader()
    aq = currencies_of_country(r, TODAY, country_id("AQ"))
    assert aq.status is LookupStatus.FOUND and aq.items == ()
    ghost = currencies_of_country(r, TODAY, "00000000-0000-4000-8000-000000000000")
    assert (ghost.status, ghost.error) == (LookupStatus.NOT_FOUND, "country_not_found")
    bad = currencies_of_country(r, TODAY, "nope")
    assert (bad.status, bad.error) == (LookupStatus.INVALID, "invalid_country_id")


def test_the_default_date_is_the_clock_day() -> None:
    r = reader(2, transitioned=True)
    before = currencies_of_country(r, FakeClock(D(2022, 12, 31)), country_id("HR"))
    after = currencies_of_country(r, FakeClock(D(2023, 1, 1)), country_id("HR"))
    assert codes(before) == ["HRK"] and codes(after) == ["EUR"]


def test_an_explicit_date_overrides_the_clock_and_boundaries_are_half_open() -> None:
    """CA-18, CL-20."""
    r = reader(2, transitioned=True)
    hr = country_id("HR")
    for day, expected in (
        ("1994-05-29", []),
        ("1994-05-30", ["HRK"]),
        ("2022-12-31", ["HRK"]),
        ("2023-01-01", ["EUR"]),
        ("2099-01-01", ["EUR"]),
    ):
        result = currencies_of_country(r, TODAY, hr, as_of=day)
        assert codes(result) == expected, day
        assert result.status is LookupStatus.FOUND  # una fecha sin asociaciones no es 404 (CL-25)


@pytest.mark.parametrize(
    "day", ["2023-1-1", "2023-02-30", "", "today", "2023-01-01T00:00", "2023-W01-1"]
)
def test_a_malformed_date_is_a_validation_error(day: str) -> None:
    result = currencies_of_country(reader(), TODAY, country_id("HR"), as_of=day)
    assert (result.status, result.error) == (LookupStatus.INVALID, "invalid_as_of_date")
    other = countries_of_currency(reader(), TODAY, currency_id("EUR"), as_of=day)
    assert other.error == "invalid_as_of_date"


def test_inactive_associations_are_hidden_by_default_and_optional() -> None:
    document = build_snapshot()
    # el registro retirado conserva su vigencia: sigue sin aparecer en las consultas por defecto
    for item in document["country_currencies"]:
        if item["currency_id"] == currency_id("JPY"):
            item["status"] = "inactive"
    from tests.fixtures.currencies import seal

    r = InMemoryCurrencyReader(seal(document))
    jp = country_id("JP")
    assert currencies_of_country(r, TODAY, jp).items == ()
    assert codes(currencies_of_country(r, TODAY, jp, include_inactive=True)) == ["JPY"]


def test_funds_can_be_excluded_from_the_countrys_currencies() -> None:
    """CL-5: BO tiene BOB y BOV; CH tiene CHE, CHF y CHW."""
    r = reader()
    assert codes(currencies_of_country(r, TODAY, country_id("BO"))) == ["BOB", "BOV"]
    assert codes(currencies_of_country(r, TODAY, country_id("BO"), exclude_funds=True)) == ["BOB"]
    assert codes(currencies_of_country(r, TODAY, country_id("CH"))) == ["CHE", "CHF", "CHW"]
    assert codes(currencies_of_country(r, TODAY, country_id("CH"), exclude_funds=True)) == ["CHF"]


def test_a_future_association_is_not_current_but_is_found_by_date_and_in_the_history() -> None:
    """CL-24."""
    from tests.fixtures.currencies import association, seal

    document = build_snapshot(
        codes=("ARS", "USD"),
        country_currencies=[association("AR", "ARS"), association("AR", "USD", D(2099, 1, 1))],
    )
    r = InMemoryCurrencyReader(seal(document))
    ar = country_id("AR")
    assert codes(currencies_of_country(r, TODAY, ar)) == ["ARS"]
    assert codes(currencies_of_country(r, TODAY, ar, as_of="2099-01-01")) == ["ARS", "USD"]
    assert codes(history_of_country(r, ar)) == ["ARS", "USD"]


def test_the_current_countries_of_a_currency_follow_the_date() -> None:
    r = reader(2, transitioned=True)
    eur = currency_id("EUR")
    now = countries_of_currency(r, TODAY, eur)
    assert [v.association.country_id for v in now.items] == sorted(
        [country_id("DE"), country_id("FR"), country_id("HR")]
    )
    earlier = countries_of_currency(r, TODAY, eur, as_of="2022-12-31")
    assert country_id("HR") not in [v.association.country_id for v in earlier.items]
    assert countries_of_currency(r, TODAY, currency_id("HRK")).items == ()  # ya no vigente
    hrk_then = countries_of_currency(r, TODAY, currency_id("HRK"), as_of="2000-01-01")
    assert [v.association.country_id for v in hrk_then.items] == [country_id("HR")]


def test_a_currency_without_countries_and_an_unknown_currency() -> None:
    """CL-7, CA-7."""
    r = reader()
    xdr = countries_of_currency(r, TODAY, currency_id("XDR"))
    assert xdr.status is LookupStatus.FOUND and xdr.items == ()
    ghost = countries_of_currency(r, TODAY, "00000000-0000-4000-8000-000000000000")
    assert (ghost.status, ghost.error) == (LookupStatus.NOT_FOUND, "currency_not_found")
    assert countries_of_currency(r, TODAY, "nope").error == "invalid_currency_id"


def test_one_currency_in_many_countries() -> None:
    result = countries_of_currency(reader(), TODAY, currency_id("EUR"))
    assert len(result.items) == 2  # DE y FR en el snapshot por defecto


# --- historial


def test_the_history_keeps_closed_and_open_periods_ordered_by_start() -> None:
    """CA-19, RF-49."""
    r = reader(2, transitioned=True)
    history = history_of_country(r, country_id("HR"))
    assert [(v.currency.record.alphabetic_code, v.association.valid_to) for v in history.items] == [
        ("HRK", D(2023, 1, 1)),
        ("EUR", None),
    ]
    assert all(v.association.status == "active" for v in history.items)


def test_the_history_puts_missing_starts_first_then_code_order() -> None:
    r = reader()
    pa = history_of_country(r, country_id("PA"))
    assert codes(pa) == ["PAB", "USD"]  # mismo inicio: por código
    ar = history_of_country(r, country_id("AR"))
    assert [v.association.valid_from for v in ar.items] == [None]


def test_the_history_of_a_currency_and_the_unknowns() -> None:
    r = reader(2, transitioned=True)
    eur = history_of_currency(r, currency_id("EUR"))
    assert [v.association.country_id for v in eur.items][-1] == country_id("HR")
    assert (
        history_of_currency(r, "00000000-0000-4000-8000-000000000000").status
        is LookupStatus.NOT_FOUND
    )
    assert history_of_currency(r, "nope").status is LookupStatus.INVALID
    assert (
        history_of_country(r, "00000000-0000-4000-8000-000000000000").status
        is LookupStatus.NOT_FOUND
    )
    assert history_of_country(r, "nope").status is LookupStatus.INVALID
    assert history_of_country(r, country_id("AQ")).items == ()


def test_associations_expose_status_validity_and_both_identities() -> None:
    """RF-50: el consumidor distingue vigente, cerrada, futura y retirada."""
    r = reader(2, transitioned=True)
    first = history_of_country(r, country_id("HR")).items[0]
    a = first.association
    assert (a.status, a.valid_from, a.valid_to) == ("active", D(1994, 5, 30), D(2023, 1, 1))
    assert (a.country_id, a.currency_id) == (country_id("HR"), currency_id("HRK"))
    assert first.currency.record.status == "inactive"  # `status` y vigencia son independientes


# --- sesiones, catálogo vacío y fallas técnicas


def test_each_query_uses_exactly_one_session() -> None:
    r = reader()
    get_currency_by_id(r, currency_id("ARS"), EN)
    assert r.sessions == 1
    currencies_of_country(r, TODAY, country_id("PA"), locale_id=EN)
    assert r.sessions == 2
    list_currencies(r)
    countries_of_currency(r, TODAY, currency_id("EUR"))
    history_of_country(r, country_id("HR"))
    assert r.sessions == 5


def test_an_empty_catalog_answers_with_empty_lists_and_not_found_never_a_technical_error() -> None:
    """CL-15."""
    r = InMemoryCurrencyReader()
    listing = list_currencies(r)
    assert listing.status is LookupStatus.FOUND and listing.items == ()
    assert listing.snapshot_version is None
    assert get_currency_by_id(r, currency_id("ARS")).status is LookupStatus.NOT_FOUND
    assert get_currency_by_code(r, "ARS").status is LookupStatus.NOT_FOUND
    assert validate_currency(r, currency_id("ARS")).item is Validation.NOT_FOUND
    assert get_catalog_version(r) is None


def test_a_technical_failure_is_never_reported_as_not_found_or_invalid() -> None:
    """RF-26, CA-5."""
    r = reader()
    r.unavailable = True
    calls = (
        lambda: get_currency_by_id(r, currency_id("ARS")),
        lambda: get_currency_by_code(r, "ARS"),
        lambda: list_currencies(r),
        lambda: validate_currency(r, currency_id("ARS")),
        lambda: currencies_of_country(r, TODAY, country_id("PA")),
        lambda: countries_of_currency(r, TODAY, currency_id("EUR")),
        lambda: history_of_country(r, country_id("PA")),
        lambda: history_of_currency(r, currency_id("EUR")),
        lambda: get_catalog_version(r),
    )
    for call in calls:
        with pytest.raises(ReaderUnavailable):
            call()


def test_the_queries_are_deterministic_for_the_same_catalog_and_date() -> None:
    """RNF-7."""
    r = reader(2, transitioned=True)
    first = currencies_of_country(r, TODAY, country_id("HR"), as_of="2023-06-01")
    second = currencies_of_country(
        r, FakeClock(D(1900, 1, 1)), country_id("HR"), as_of="2023-06-01"
    )
    assert first == second
