"""T8: API pública read-only de Currency contra datos incorporados en Postgres real.

RF-8, RF-22 a RF-35, RF-49, RF-50, RNF-3, RNF-6, RNF-8, CA-4 a CA-6, CA-13, CA-24.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from gi_common_reference.app import (
    countries_openapi_document,
    create_catalog_app,
    currencies_openapi_document,
    openapi_document,
    regions_openapi_document,
)
from gi_common_reference.bootstrap import (
    country_flag_store,
    currency_required_locales,
    postgres_country_reader,
    postgres_currency_reader,
    postgres_currency_repository,
    postgres_reader,
    postgres_region_reader,
    postgres_region_repository,
    postgres_repository,
    required_locales,
)
from gi_common_reference.currencies.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.regions.application.incorporate import (
    incorporate_snapshot as incorporate_regions,
)
from tests.conftest import alembic_config, with_database
from tests.fixtures.countries import regions_snapshot
from tests.fixtures.currencies import (
    EN,
    ES,
    build_snapshot,
    country_id,
    currency_id,
    transition_snapshot,
)
from tests.fixtures.currency_reader import FakeClock
from tests.fixtures.regions import FR, locale_snapshot
from tests.integration.currencies.test_incorporation import seed_countries

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "contracts"
CLOCK = FakeClock(date(2026, 11, 1))
GHOST = "00000000-0000-4000-8000-000000000000"
CURRENCY_KEYS = {
    "currency_id",
    "alphabetic_code",
    "numeric_code",
    "minor_units",
    "fund_code",
    "status",
    "replacement_currency_ids",
    "name",
}
ASSOCIATION_KEYS = {
    "country_currency_id",
    "country_id",
    "currency",
    "status",
    "valid_from",
    "valid_to",
}
ACTIVE_CODES = sorted(
    [
        "ARS",
        "USD",
        "EUR",
        "PAB",
        "JPY",
        "KWD",
        "CLF",
        "XAU",
        "XDR",
        "BOB",
        "BOV",
        "CHF",
        "CHE",
        "CHW",
    ]
)


def prepared_database(
    admin_url: str, *, currencies: bool = True, snapshots: tuple[int, ...] = (1, 2)
) -> tuple[str, str]:
    name = f"api_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = with_database(admin_url, name)
    command.upgrade(alembic_config(url), "head")
    incorporate_locales(locale_snapshot(1), postgres_repository(url))
    incorporate_regions(regions_snapshot(1), postgres_region_repository(url), required_locales())
    seed_countries(url)
    if currencies:
        for version in snapshots:
            document = build_snapshot(1) if version == 1 else transition_snapshot(version)
            result = incorporate_snapshot(
                document, postgres_currency_repository(url), currency_required_locales()
            )
            assert result.outcome is Outcome.INCORPORATED, result.violations
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("ALTER ROLE reference_reader LOGIN PASSWORD 'reader-pw'")
    return name, make_conninfo(url, user="reference_reader", password="reader-pw")


@pytest.fixture(scope="module")
def reader_url(postgres_with_roles: str) -> Iterator[str]:
    """Una base con Locale, Regions, Countries sembrado y los dos snapshots de Currency."""
    name, url = prepared_database(postgres_with_roles)
    yield url
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def client_for(url: str, clock: FakeClock = CLOCK) -> TestClient:
    return TestClient(
        create_catalog_app(
            postgres_reader(url),
            postgres_region_reader(url),
            postgres_country_reader(url),
            country_flag_store(),
            postgres_currency_reader(url),
            clock,
        )
    )


@pytest.fixture
def api(reader_url: str) -> TestClient:
    return client_for(reader_url)


def codes(response: Any) -> list[str]:
    return [
        item["alphabetic_code"]
        if "alphabetic_code" in item
        else item["currency"]["alphabetic_code"]
        for item in response.json()["data"]
    ]


# --- listado (RF-27, RF-29) --------------------------------------------------------------------


def test_the_default_list_is_active_currencies_in_binary_code_order(api: TestClient) -> None:
    response = api.get("/v1/currencies")
    assert response.status_code == 200
    assert response.json()["snapshot_version"] == 2
    assert codes(response) == ACTIVE_CODES
    first = response.json()["data"][0]
    assert set(first) == CURRENCY_KEYS
    assert first["name"] is None  # sin locale no hay nombre
    assert first["status"] == "active" and first["replacement_currency_ids"] == []


def test_inactive_and_funds_are_options(api: TestClient) -> None:
    assert "HRK" in codes(api.get("/v1/currencies", params={"include_inactive": "true"}))
    no_funds = codes(api.get("/v1/currencies", params={"exclude_funds": "true"}))
    assert not {"BOV", "CHE", "CHW", "CLF"} & set(no_funds) and "CHF" in no_funds


def test_the_list_names_in_en_and_es_and_null_without_translation(api: TestClient) -> None:
    for locale, expected in ((EN, "Argentine Peso"), (ES, "peso argentino")):
        data = api.get("/v1/currencies", params={"locale_id": locale}).json()["data"]
        assert next(c for c in data if c["alphabetic_code"] == "ARS")["name"] == expected
    french = api.get("/v1/currencies", params={"locale_id": FR}).json()["data"]
    assert all(c["name"] is None for c in french)  # sin fallback


@pytest.mark.parametrize(
    ("locale", "code"), [("nope", "invalid_locale_id"), (GHOST, "unknown_locale")]
)
def test_an_invalid_locale_is_422_not_404(api: TestClient, locale: str, code: str) -> None:
    response = api.get("/v1/currencies", params={"locale_id": locale})
    assert response.status_code == 422 and response.json()["error"]["code"] == code


@pytest.mark.parametrize("param", ["include_inactive", "exclude_funds"])
def test_a_malformed_boolean_is_422_with_the_common_error_envelope(
    api: TestClient, param: str
) -> None:
    response = api.get("/v1/currencies", params={param: "maybe"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_parameter" and param in response.text


# --- por código y por identidad (RF-22 a RF-25, CL-12)


@pytest.mark.parametrize("code", ["USD", "usd", "Usd"])
def test_code_and_id_resolve_to_the_same_record(api: TestClient, code: str) -> None:
    """CA-4."""
    by_code = api.get(f"/v1/currencies/by-code/{code}", params={"locale_id": EN})
    by_id = api.get(f"/v1/currencies/{currency_id('USD')}", params={"locale_id": EN})
    assert by_code.status_code == by_id.status_code == 200
    assert by_code.json() == by_id.json()
    data = by_code.json()["data"]
    assert (data["numeric_code"], data["minor_units"], data["name"]) == ("840", 2, "US Dollar")


@pytest.mark.parametrize(
    "code", ["%20USD", "USD%20", "US", "US%24", "USDD", "12A", "032", "%C3%9CSD"]
)
def test_malformed_codes_are_422(api: TestClient, code: str) -> None:
    response = api.get(f"/v1/currencies/by-code/{code}")
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_code"


def test_unknown_code_and_id_are_404_and_a_malformed_id_is_422(api: TestClient) -> None:
    """CA-5: los tres resultados son distinguibles."""
    unknown_code = api.get("/v1/currencies/by-code/ZZZ")
    assert unknown_code.status_code == 404
    assert unknown_code.json()["error"]["code"] == "currency_not_found"
    assert api.get(f"/v1/currencies/{GHOST}").status_code == 404
    malformed = api.get("/v1/currencies/nope")
    assert (
        malformed.status_code == 422 and malformed.json()["error"]["code"] == "invalid_currency_id"
    )


def test_numeric_code_is_published_with_leading_zeros_but_is_not_a_resolution_key(
    api: TestClient,
) -> None:
    """D-12, CA-23."""
    data = api.get("/v1/currencies/by-code/ARS").json()["data"]
    assert data["numeric_code"] == "032"
    assert api.get("/v1/currencies/by-numeric/032").status_code == 404  # no existe esa ruta
    assert api.get("/v1/currencies/by-code/032").status_code == 422


def test_ars_usd_eur_and_special_units(api: TestClient) -> None:
    """CA-16, CL-1, CL-2."""
    expected = {
        "ARS": ("032", 2, False),
        "USD": ("840", 2, False),
        "EUR": ("978", 2, False),
        "JPY": ("392", 0, False),
        "KWD": ("414", 3, False),
        "CLF": ("990", 4, True),
        "XAU": ("959", None, False),
        "BOB": ("068", 2, False),
    }
    for code, (numeric, units, fund) in expected.items():
        data = api.get(f"/v1/currencies/by-code/{code}").json()["data"]
        assert (data["numeric_code"], data["minor_units"], data["fund_code"]) == (
            numeric,
            units,
            fund,
        )


def test_a_retired_currency_resolves_with_status_inactive_and_its_replacement(
    api: TestClient,
) -> None:
    """CA-22, CL-8."""
    by_code = api.get("/v1/currencies/by-code/hrk", params={"locale_id": ES})
    assert by_code.status_code == 200
    data = by_code.json()["data"]
    assert data["status"] == "inactive" and data["replacement_currency_ids"] == [currency_id("EUR")]
    assert data["name"] == "kuna croata"
    assert api.get(f"/v1/currencies/{currency_id('HRK').upper()}").json()["data"] == {
        **data,
        "name": None,
    }


def test_validation_returns_the_three_results(api: TestClient) -> None:
    """CA-6."""

    def result(identity: str) -> Any:
        return api.get(f"/v1/currencies/{identity}/validation")

    assert result(currency_id("ARS")).json()["data"] == {"result": "active"}
    assert result(currency_id("HRK")).json()["data"] == {"result": "inactive"}
    ghost = result(GHOST)
    assert ghost.status_code == 200 and ghost.json()["data"] == {"result": "not_found"}
    assert result("nope").status_code == 422


def test_the_catalog_version_endpoint(api: TestClient) -> None:
    assert api.get("/v1/currencies/version").json() == {
        "snapshot_version": 2,
        "data": {"snapshot_version": 2},
    }


# --- monedas de un país y países de una moneda (RF-30, RF-31, RF-48 a RF-50)


def test_panama_has_pab_and_usd_simultaneously(api: TestClient) -> None:
    """CA-7, CA-17."""
    response = api.get(f"/v1/currencies/by-country/{country_id('PA')}")
    assert response.status_code == 200 and codes(response) == ["PAB", "USD"]
    item = response.json()["data"][0]
    assert set(item) == ASSOCIATION_KEYS and set(item["currency"]) == CURRENCY_KEYS
    assert item["status"] == "active" and item["valid_from"] == "1904-01-01"
    assert item["valid_to"] is None


def test_a_country_without_currency_is_empty_and_an_unknown_one_is_404(api: TestClient) -> None:
    aq = api.get(f"/v1/currencies/by-country/{country_id('AQ')}")
    assert aq.status_code == 200 and aq.json()["data"] == []
    ghost = api.get(f"/v1/currencies/by-country/{GHOST}")
    assert ghost.status_code == 404 and ghost.json()["error"]["code"] == "country_not_found"
    assert api.get("/v1/currencies/by-country/nope").status_code == 422


def test_croatia_by_date_the_same_day_transition_has_no_gap_and_no_overlap(api: TestClient) -> None:
    """CA-18, CL-20."""
    url = f"/v1/currencies/by-country/{country_id('HR')}"
    for day, expected in (
        ("1994-05-29", []),
        ("1994-05-30", ["HRK"]),
        ("2022-12-31", ["HRK"]),
        ("2023-01-01", ["EUR"]),
        ("2099-12-31", ["EUR"]),
    ):
        response = api.get(url, params={"as_of": day})
        assert response.status_code == 200 and codes(response) == expected, day


def test_the_default_date_is_the_injected_clock_day(reader_url: str) -> None:
    url = f"/v1/currencies/by-country/{country_id('HR')}"
    before = client_for(reader_url, FakeClock(date(2022, 12, 31))).get(url)
    after = client_for(reader_url, FakeClock(date(2023, 1, 1))).get(url)
    assert codes(before) == ["HRK"] and codes(after) == ["EUR"]


@pytest.mark.parametrize("day", ["2023-1-1", "2023-02-30", "today", "2023-01-01T00:00", ""])
def test_a_malformed_date_is_422(api: TestClient, day: str) -> None:
    for path in (
        f"/v1/currencies/by-country/{country_id('HR')}",
        f"/v1/currencies/{currency_id('EUR')}/countries",
    ):
        response = api.get(path, params={"as_of": day})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_as_of_date"


def test_funds_can_be_excluded_from_a_countrys_currencies(api: TestClient) -> None:
    ch = f"/v1/currencies/by-country/{country_id('CH')}"
    assert codes(api.get(ch)) == ["CHE", "CHF", "CHW"]
    assert codes(api.get(ch, params={"exclude_funds": "true"})) == ["CHF"]


def test_the_history_keeps_the_closed_period_active_and_the_open_one(api: TestClient) -> None:
    """CA-19, RF-49, RF-50."""
    response = api.get(f"/v1/currencies/by-country/{country_id('HR')}/history")
    assert response.status_code == 200
    rows = response.json()["data"]
    assert [(r["currency"]["alphabetic_code"], r["status"]) for r in rows] == [
        ("HRK", "active"),
        ("EUR", "active"),
    ]
    assert (rows[0]["valid_from"], rows[0]["valid_to"]) == ("1994-05-30", "2023-01-01")
    assert (rows[1]["valid_from"], rows[1]["valid_to"]) == ("2023-01-01", None)
    assert rows[0]["currency"]["status"] == "inactive"  # `status` y vigencia son independientes


def test_the_countries_of_a_currency_follow_the_date_and_expose_only_country_id(
    api: TestClient,
) -> None:
    eur = f"/v1/currencies/{currency_id('EUR')}/countries"
    now = api.get(eur)
    assert [r["country_id"] for r in now.json()["data"]] == sorted(
        [country_id("DE"), country_id("FR"), country_id("HR")]
    )
    earlier = api.get(eur, params={"as_of": "2022-12-31"})
    assert country_id("HR") not in [r["country_id"] for r in earlier.json()["data"]]
    assert set(now.json()["data"][0]) == ASSOCIATION_KEYS  # nada más de Country (RF-20)
    history = api.get(f"{eur}/history")
    assert history.status_code == 200 and len(history.json()["data"]) == 3
    assert api.get(f"/v1/currencies/{currency_id('XDR')}/countries").json()["data"] == []
    assert api.get(f"/v1/currencies/{GHOST}/countries").status_code == 404
    assert api.get(f"/v1/currencies/{GHOST}/countries/history").status_code == 404
    assert api.get("/v1/currencies/nope/countries").status_code == 422


# --- rutas, métodos y sin escritura (RF-34, CA-13)


def test_fixed_routes_are_not_swallowed_by_the_id_route(api: TestClient) -> None:
    assert api.get("/v1/currencies/version").json()["data"] == {"snapshot_version": 2}
    assert api.get("/v1/currencies/by-country/validation").status_code == 422
    assert api.get("/v1/currencies/by-code/countries").json()["error"]["code"] == "invalid_code"
    assert api.get(f"/v1/currencies/by-country/{country_id('PA')}/history").status_code == 200
    assert api.get("/v1/currencies/by-country").status_code == 422


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_no_write_method_exists_on_any_route(api: TestClient, method: str) -> None:
    for path in (
        "/v1/currencies",
        "/v1/currencies/version",
        f"/v1/currencies/{currency_id('ARS')}",
        "/v1/currencies/by-code/ARS",
        f"/v1/currencies/by-country/{country_id('PA')}",
        f"/v1/currencies/{currency_id('ARS')}/countries",
        f"/v1/currencies/{currency_id('ARS')}/validation",
    ):
        response = api.request(method, path, json={"status": "inactive"})
        assert response.status_code == 405, (method, path)


def test_responses_carry_no_tenant_no_market_data_and_no_country_attributes(
    api: TestClient,
) -> None:
    """RF-8, RF-20, CA-2, CA-8, CA-13."""
    forbidden = {
        "tenant_id",
        "organization_id",
        "rate",
        "exchange_rate",
        "price",
        "balance",
        "symbol",
    }
    bodies = [
        api.get("/v1/currencies", params={"include_inactive": "true", "locale_id": ES}).text,
        api.get(f"/v1/currencies/by-country/{country_id('HR')}/history").text,
        api.get(f"/v1/currencies/{currency_id('EUR')}/countries/history").text,
    ]
    for body in bodies:
        keys = set(_keys(json.loads(body)))
        assert not forbidden & keys
        assert not {"alpha2", "alpha3", "calling_code", "region_id"} & keys


def _keys(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [*node, *(k for value in node.values() for k in _keys(value))]
    if isinstance(node, list):
        return [k for item in node for k in _keys(item)]
    return []


# --- catálogo vacío y falla técnica (RF-26, CL-15)


def test_an_empty_catalog_is_never_a_server_error(postgres_with_roles: str) -> None:
    name, url = prepared_database(postgres_with_roles, currencies=False)
    try:
        api = client_for(url)
        listing = api.get("/v1/currencies")
        assert listing.status_code == 200
        assert listing.json() == {"snapshot_version": None, "data": []}
        assert api.get("/v1/currencies/version").json()["snapshot_version"] is None
        assert api.get(f"/v1/currencies/{currency_id('ARS')}").status_code == 404
        assert api.get("/v1/currencies/by-code/ARS").status_code == 404
        assert api.get(f"/v1/currencies/by-country/{country_id('AR')}").json()["data"] == []
        assert api.get(f"/v1/currencies/{currency_id('ARS')}/validation").json()["data"] == {
            "result": "not_found"
        }
    finally:
        with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def test_a_technical_failure_is_503_never_404_or_422_and_leaks_no_credentials() -> None:
    api = TestClient(
        create_catalog_app(
            postgres_reader("postgresql://u:s3cr3t@127.0.0.1:1/none?connect_timeout=2"),
            postgres_region_reader("postgresql://u:s3cr3t@127.0.0.1:1/none?connect_timeout=2"),
            postgres_country_reader("postgresql://u:s3cr3t@127.0.0.1:1/none?connect_timeout=2"),
            country_flag_store(),
            postgres_currency_reader("postgresql://u:s3cr3t@127.0.0.1:1/none?connect_timeout=2"),
            CLOCK,
        ),
        raise_server_exceptions=False,
    )
    for path in (
        "/v1/currencies",
        f"/v1/currencies/{currency_id('ARS')}",
        "/v1/currencies/by-code/ARS",
        f"/v1/currencies/by-country/{country_id('PA')}",
        "/v1/currencies/version",
    ):
        response = api.get(path)
        assert response.status_code == 503, path
        assert response.json()["error"]["code"] == "technical_error"
        assert "s3cr3t" not in response.text


# --- contratos publicados


def test_the_published_openapi_matches_the_generated_one_and_is_served(api: TestClient) -> None:
    published = json.loads((CONTRACTS / "currencies-api.v1.openapi.json").read_text("utf-8"))
    assert currencies_openapi_document() == published
    assert api.get("/v1/openapi/currencies.json").json() == published


def test_the_other_published_contracts_do_not_change(api: TestClient) -> None:
    """CA-24: 001–003 intactos."""

    def published(name: str) -> Any:
        return json.loads((CONTRACTS / name).read_text("utf-8"))

    assert openapi_document() == published("locales-api.v1.openapi.json")
    assert regions_openapi_document() == published("regions-api.v1.openapi.json")
    assert countries_openapi_document() == published("countries-api.v1.openapi.json")
    assert api.get("/v1/openapi.json").json() == published("locales-api.v1.openapi.json")
    assert api.get("/v1/openapi/countries.json").json() == published(
        "countries-api.v1.openapi.json"
    )


def test_the_openapi_declares_only_read_operations_and_the_five_outcomes() -> None:
    document = currencies_openapi_document()
    for path, operations in document["paths"].items():
        assert set(operations) == {"get"}, path
        responses = operations["get"]["responses"]
        assert "200" in responses and "503" in responses, path
    assert "422" in document["paths"]["/v1/currencies/{currency_id}"]["get"]["responses"]
    assert "404" in document["paths"]["/v1/currencies/{currency_id}"]["get"]["responses"]
    properties = {
        name
        for schema in document["components"]["schemas"].values()
        for name in schema.get("properties", {})
    }
    assert not {"tenant_id", "rate", "exchange_rate", "price", "balance", "symbol"} & properties
    assert document["info"]["version"] == "1.0.0"


def test_the_country_api_mounted_next_to_currency_keeps_its_routes(api: TestClient) -> None:
    """RNF-6: montar Currency no altera el despacho de Countries ni de Locale."""
    assert api.get("/v1/countries").status_code == 200
    assert api.get("/v1/locales").status_code in (200, 404)
    assert api.get("/v1/regions").status_code == 200


def test_the_reader_url_uses_the_least_privileged_role(reader_url: str) -> None:
    with psycopg.connect(reader_url, autocommit=True) as conn:
        assert conn.execute("SELECT current_user").fetchone() == ("reference_reader",)


def test_an_app_built_without_currency_does_not_serve_its_routes() -> None:
    from tests.fixtures.country_fakes import FakeCountryReader
    from tests.fixtures.fakes import FakeReader
    from tests.fixtures.region_fakes import FakeRegionReader

    api = TestClient(
        create_catalog_app(
            FakeReader(),
            FakeRegionReader(),
            FakeCountryReader(),
            country_flag_store(),
        )
    )
    assert api.get("/v1/currencies").status_code == 404
