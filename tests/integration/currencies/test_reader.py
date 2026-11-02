"""T7: el lector de Postgres devuelve lo mismo que el lector en memoria sobre los mismos datos.

El lector en memoria es la referencia de la semántica (consultas, orden, filtros por fecha); aquí se
comprueba, contra Postgres real y con el rol `reference_reader`, que el SQL la respeta
(RF-22 a RF-32, RF-48 a RF-50, RNF-7).
"""

from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from gi_common_reference.bootstrap import (
    currency_required_locales,
    postgres_currency_repository,
    postgres_region_repository,
    postgres_repository,
    required_locales,
)
from gi_common_reference.currencies.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.currencies.application.queries import (
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
from gi_common_reference.currencies.infrastructure.clock import SystemClock
from gi_common_reference.currencies.infrastructure.postgres_reader import PostgresCurrencyReader
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.regions.application.incorporate import (
    incorporate_snapshot as incorporate_regions,
)
from tests.fixtures.countries import regions_snapshot
from tests.fixtures.currencies import (
    COUNTRY_CODES,
    EN,
    ES,
    build_snapshot,
    country_id,
    currency_id,
    transition_snapshot,
)
from tests.fixtures.currency_reader import FakeClock, InMemoryCurrencyReader
from tests.fixtures.regions import FR, locale_snapshot
from tests.integration.currencies.test_incorporation import seed_countries

D = date
DAYS = ("1990-01-01", "1994-05-29", "1994-05-30", "2022-12-31", "2023-01-01", "2030-06-01")
CLOCK = FakeClock(D(2026, 11, 1))


@pytest.fixture
def loaded(database_factory: Callable[[], str]) -> Iterator[tuple[str, InMemoryCurrencyReader]]:
    """Base con el snapshot 1 y la transición HRK→EUR (snapshot 2), y su lector de referencia."""
    url = database_factory()
    incorporate_locales(locale_snapshot(1), postgres_repository(url))
    incorporate_regions(regions_snapshot(1), postgres_region_repository(url), required_locales())
    seed_countries(url)
    for document in (build_snapshot(1), transition_snapshot(2)):
        result = incorporate_snapshot(
            document, postgres_currency_repository(url), currency_required_locales()
        )
        assert result.outcome is Outcome.INCORPORATED, result.violations
    reference = InMemoryCurrencyReader(transition_snapshot(2))
    reference.locale_ids = {EN, ES, FR}
    yield make_conninfo(url, options="-c role=reference_reader"), reference


def both(loaded: tuple[str, InMemoryCurrencyReader]) -> tuple[Any, Any]:
    return PostgresCurrencyReader(loaded[0]), loaded[1]


def test_lookups_match_the_reference_for_every_currency_and_locale(
    loaded: tuple[str, InMemoryCurrencyReader],
) -> None:
    real, reference = both(loaded)
    for currency in reference.currencies.values():
        for locale in (None, EN, ES, FR):
            assert get_currency_by_id(real, currency.currency_id, locale) == get_currency_by_id(
                reference, currency.currency_id, locale
            )
            assert get_currency_by_code(
                real, currency.alphabetic_code.lower(), locale
            ) == get_currency_by_code(reference, currency.alphabetic_code, locale)
        assert validate_currency(real, currency.currency_id) == validate_currency(
            reference, currency.currency_id
        )
    assert get_currency_by_id(real, "00000000-0000-4000-8000-000000000000").error == (
        "currency_not_found"
    )


@pytest.mark.parametrize("include_inactive", [False, True])
@pytest.mark.parametrize("exclude_funds", [False, True])
@pytest.mark.parametrize("locale", [None, EN, ES, FR])
def test_the_list_matches_the_reference(
    loaded: tuple[str, InMemoryCurrencyReader],
    include_inactive: bool,
    exclude_funds: bool,
    locale: str | None,
) -> None:
    real, reference = both(loaded)
    assert list_currencies(real, include_inactive, exclude_funds, locale) == list_currencies(
        reference, include_inactive, exclude_funds, locale
    )


def test_the_default_list_is_ordered_in_binary_code_order_without_the_retired(
    loaded: tuple[str, InMemoryCurrencyReader],
) -> None:
    listing = list_currencies(PostgresCurrencyReader(loaded[0]))
    codes = [v.record.alphabetic_code for v in listing.items]
    assert codes == sorted(codes) and "HRK" not in codes and listing.snapshot_version == 2


@pytest.mark.parametrize("include_inactive", [False, True])
def test_the_country_and_currency_queries_match_the_reference_on_every_boundary_date(
    loaded: tuple[str, InMemoryCurrencyReader], include_inactive: bool
) -> None:
    real, reference = both(loaded)
    for code in COUNTRY_CODES:
        for day in (*DAYS, None):
            assert currencies_of_country(
                real, CLOCK, country_id(code), day, include_inactive, locale_id=ES
            ) == currencies_of_country(
                reference, CLOCK, country_id(code), day, include_inactive, locale_id=ES
            ), (code, day)
        assert history_of_country(
            real, country_id(code), include_inactive, EN
        ) == history_of_country(reference, country_id(code), include_inactive, EN)
    for currency in reference.currencies.values():
        for day in (*DAYS, None):
            assert countries_of_currency(
                real, CLOCK, currency.currency_id, day, include_inactive
            ) == countries_of_currency(
                reference, CLOCK, currency.currency_id, day, include_inactive
            )
        assert history_of_currency(
            real, currency.currency_id, include_inactive
        ) == history_of_currency(reference, currency.currency_id, include_inactive)


def test_the_transition_day_returns_exactly_one_currency_for_croatia(
    loaded: tuple[str, InMemoryCurrencyReader],
) -> None:
    """CA-18, CL-20 contra Postgres real."""
    real = PostgresCurrencyReader(loaded[0])
    hr = country_id("HR")

    def on(day: str) -> list[str]:
        result = currencies_of_country(real, CLOCK, hr, day)
        return [v.currency.record.alphabetic_code for v in result.items]

    assert on("2022-12-31") == ["HRK"] and on("2023-01-01") == ["EUR"] and on("1980-01-01") == []
    history = history_of_country(real, hr)
    assert [(v.currency.record.alphabetic_code, v.association.valid_to) for v in history.items] == [
        ("HRK", D(2023, 1, 1)),
        ("EUR", None),
    ]


def test_an_unknown_country_is_not_found_and_an_existing_one_without_currency_is_empty(
    loaded: tuple[str, InMemoryCurrencyReader],
) -> None:
    real = PostgresCurrencyReader(loaded[0])
    assert currencies_of_country(real, CLOCK, country_id("AQ")).items == ()
    assert currencies_of_country(real, CLOCK, "00000000-0000-4000-8000-000000000000").error == (
        "country_not_found"
    )


def test_the_reader_role_can_read_everything_the_queries_need_and_write_nothing(
    loaded: tuple[str, InMemoryCurrencyReader],
) -> None:
    with psycopg.connect(loaded[0], autocommit=True) as conn:
        for table in ("currency", "currency_locale", "country_currency", "currency_snapshot"):
            conn.execute(f"SELECT 1 FROM reference.{table} LIMIT 1")
        conn.execute("SELECT 1 FROM reference.country LIMIT 1")
        conn.execute("SELECT 1 FROM reference.locale LIMIT 1")
        for statement in (
            "UPDATE reference.currency SET status = 'inactive'",
            "DELETE FROM reference.country_currency",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)


def test_the_catalog_version_and_an_empty_catalog(
    loaded: tuple[str, InMemoryCurrencyReader], database_factory: Callable[[], str]
) -> None:
    assert get_catalog_version(PostgresCurrencyReader(loaded[0])) == 2
    empty = PostgresCurrencyReader(database_factory())
    assert get_catalog_version(empty) is None
    assert list_currencies(empty).items == ()
    assert get_currency_by_code(empty, "ARS").error == "currency_not_found"


def test_a_database_that_cannot_be_reached_is_a_technical_error() -> None:
    """RF-26: ni «no encontrado» ni error de validación; sin credenciales en el mensaje."""
    unreachable = PostgresCurrencyReader("postgresql://u:s3cr3t@127.0.0.1:1/none?connect_timeout=2")
    with pytest.raises(ReaderUnavailable) as error:
        list_currencies(unreachable)
    assert "s3cr3t" not in str(error.value)
    with pytest.raises(ReaderUnavailable):
        get_currency_by_id(unreachable, currency_id("ARS"))


def test_the_system_clock_is_a_utc_calendar_day() -> None:
    today = SystemClock().today()
    assert isinstance(today, date) and today.year >= 2026
