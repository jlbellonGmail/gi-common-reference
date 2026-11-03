"""T8: API pública de Units contra datos incorporados en Postgres real con `reference_reader`.

RF-26, RF-32 a RF-40, RNF-3, CA-15 (y las conversiones de CA-1 a CA-5, CA-7, CA-16 por HTTP).
"""

import json
import uuid
from collections.abc import Iterator
from contextlib import AbstractContextManager
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
    units_openapi_document,
)
from gi_common_reference.bootstrap import (
    country_flag_store,
    postgres_country_reader,
    postgres_currency_reader,
    postgres_reader,
    postgres_region_reader,
    postgres_repository,
    postgres_units_reader,
    postgres_units_repository,
    system_clock,
    units_required_locales,
    units_ucum_table,
)
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.units.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.units.domain.ports import UnitsReader, UnitsSession
from tests.conftest import alembic_config, with_database
from tests.fixtures.regions import FR, locale_snapshot
from tests.fixtures.units import EN, ES, kind_id, seal, unit_id
from tests.fixtures.units_variants import SACK_ID, sack_snapshot
from tests.unit.units.helpers import association_row, edit, kind_row, unit_row

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "contracts"
GHOST = "00000000-0000-4000-8000-000000000000"
HUGE_FACTOR = "100000000000000000000"  # 10^20: hace desbordar el rango del resultado
KIND_KEYS = {"quantity_kind_id", "code", "conversion_type", "reference_unit_id", "status", "name"}
UNIT_KEYS = {
    "unit_id",
    "ucum_code",
    "unece_code",
    "symbol",
    "status",
    "name",
    "plural",
    "quantity_kinds",
}
KIND_CODES = sorted(
    [
        "mass",
        "length",
        "area",
        "volume",
        "duration",
        "temperature",
        "temperature_difference",
        "speed",
        "density",
        "mass_concentration",
        "mass_per_area",
        "volume_per_area",
        "dimensionless_ratio",
    ]
)


def incorporate(url: str, document: dict[str, Any]) -> None:
    result = incorporate_snapshot(
        document, postgres_units_repository(url), units_required_locales(), units_ucum_table()
    )
    assert result.outcome is Outcome.INCORPORATED, result.violations


def prepared_database(admin_url: str, *, units: bool = True) -> tuple[str, str]:
    """Una base con Locale y, si `units`, tres versiones: v1 (saco = 60 kg), v2 (saco = 50 kg,
    `oz` retirada y la asociación °F de la diferencia de temperatura `inactive`) y v3 (el saco
    pasa a 10^20 kg y se retira la magnitud `count` con su unidad `each`)."""
    name = f"api_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = with_database(admin_url, name)
    command.upgrade(alembic_config(url), "head")
    incorporate_locales(locale_snapshot(1), postgres_repository(url))
    if units:
        retired = {"retired": ("oz",), "inactive_links": (("temperature_difference", "degF"),)}
        incorporate(url, sack_snapshot(1, factor="60"))
        incorporate(url, sack_snapshot(2, factor="50", **retired))  # type: ignore[arg-type]
        third = sack_snapshot(3, factor=HUGE_FACTOR, **retired)  # type: ignore[arg-type]

        def retire_count(document: dict[str, Any]) -> None:
            kind_row(document, "count")["status"] = "inactive"
            unit_row(document, "each")["status"] = "inactive"
            association_row(document, "count", "each")["status"] = "inactive"

        incorporate(url, seal(edit(third, retire_count)))
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("ALTER ROLE reference_reader LOGIN PASSWORD 'reader-pw'")
    return name, make_conninfo(url, user="reference_reader", password="reader-pw")


@pytest.fixture(scope="module")
def reader_url(postgres_with_roles: str) -> Iterator[str]:
    name, url = prepared_database(postgres_with_roles)
    yield url
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def client_for(url: str, *, reader: UnitsReader | None = None) -> TestClient:
    return TestClient(
        create_catalog_app(
            postgres_reader(url),
            postgres_region_reader(url),
            postgres_country_reader(url),
            country_flag_store(),
            postgres_currency_reader(url),
            system_clock(),
            reader if reader is not None else postgres_units_reader(url),
        ),
        raise_server_exceptions=False,
    )


@pytest.fixture
def api(reader_url: str) -> TestClient:
    return client_for(reader_url)


def body(
    value: str | int | float | None = "1",
    source: str = "kg",
    target: str = "g",
    kind: str | None = "mass",
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "value": value,
        "from_unit_id": SACK_ID if source == "sack" else unit_id(source),
        "to_unit_id": SACK_ID if target == "sack" else unit_id(target),
    }
    if kind is not None:
        payload["quantity_kind_id"] = kind_id(kind)
    payload.update(extra)
    return payload


def convert(api: TestClient, payload: Any) -> Any:
    return api.post("/v1/conversions", json=payload)


def error_code(response: Any) -> str:
    assert response.status_code in (404, 422, 503), response.text
    return str(response.json()["error"]["code"])


# --- magnitudes (RF-32, RF-33)


def test_the_default_kind_list_is_active_kinds_in_code_order(api: TestClient) -> None:
    response = api.get("/v1/quantity-kinds")
    assert response.status_code == 200
    assert response.json()["snapshot_version"] == 3
    data = response.json()["data"]
    assert [k["code"] for k in data] == KIND_CODES
    assert set(data[0]) == KIND_KEYS and data[0]["name"] is None
    mass = next(k for k in data if k["code"] == "mass")
    assert mass["quantity_kind_id"] == kind_id("mass")
    assert (mass["conversion_type"], mass["reference_unit_id"]) == ("linear", unit_id("kg"))
    assert next(k for k in data if k["code"] == "temperature")["conversion_type"] == "affine"


def test_kind_filters_include_inactive_and_localization(api: TestClient) -> None:
    only = api.get("/v1/quantity-kinds", params={"code": "area", "include_inactive": "true"})
    assert [k["code"] for k in only.json()["data"]] == ["area"]
    assert api.get("/v1/quantity-kinds", params={"code": "AREA"}).json()["data"] == []
    everything = api.get("/v1/quantity-kinds", params={"include_inactive": "true"}).json()["data"]
    count = next(k for k in everything if k["code"] == "count")
    assert count["status"] == "inactive" and len(everything) == len(KIND_CODES) + 1
    found = api.get(f"/v1/quantity-kinds/{kind_id('count')}")
    assert found.status_code == 200 and found.json()["data"]["status"] == "inactive"
    for locale, expected in ((EN, "Mass"), (ES, "Masa")):
        data = api.get("/v1/quantity-kinds", params={"locale_id": locale}).json()["data"]
        assert next(k for k in data if k["code"] == "mass")["name"] == expected
    french = api.get("/v1/quantity-kinds", params={"locale_id": FR}).json()["data"]
    assert all(k["name"] is None for k in french)  # sin fallback


@pytest.mark.parametrize(
    ("locale", "code"), [("nope", "invalid_locale_id"), (GHOST, "unknown_locale")]
)
def test_an_invalid_locale_is_422_not_404(api: TestClient, locale: str, code: str) -> None:
    for path in ("/v1/quantity-kinds", "/v1/units", f"/v1/units/{unit_id('kg')}"):
        response = api.get(path, params={"locale_id": locale})
        assert response.status_code == 422 and error_code(response) == code, path


def test_a_malformed_boolean_is_422_with_the_common_envelope(api: TestClient) -> None:
    for path in ("/v1/quantity-kinds", "/v1/units"):
        response = api.get(path, params={"include_inactive": "maybe"})
        assert response.status_code == 422 and error_code(response) == "invalid_parameter"
        assert "include_inactive" in response.text


def test_a_kind_by_id_and_its_404_and_422(api: TestClient) -> None:
    found = api.get(f"/v1/quantity-kinds/{kind_id('mass')}", params={"locale_id": ES})
    assert found.status_code == 200
    assert found.json()["data"]["name"] == "Masa" and set(found.json()["data"]) == KIND_KEYS
    missing = api.get(f"/v1/quantity-kinds/{GHOST}")
    assert missing.status_code == 404 and error_code(missing) == "quantity_kind_not_found"
    assert missing.json()["snapshot_version"] == 3
    malformed = api.get("/v1/quantity-kinds/nope")
    assert malformed.status_code == 422 and error_code(malformed) == "invalid_quantity_kind_id"


# --- unidades (RF-34, RF-35, RF-36)


def test_the_default_unit_list_is_active_units_by_symbol_and_id(api: TestClient) -> None:
    response = api.get("/v1/units")
    assert response.status_code == 200
    data = response.json()["data"]
    assert all(u["status"] == "active" and set(u) == UNIT_KEYS for u in data)
    assert unit_id("oz") not in {u["unit_id"] for u in data}  # retirada en v2
    keys = [(u["symbol"].encode("utf-8"), u["unit_id"]) for u in data]
    assert keys == sorted(keys)
    withdrawn = api.get("/v1/units", params={"include_inactive": "true"}).json()["data"]
    oz = next(u for u in withdrawn if u["unit_id"] == unit_id("oz"))
    assert oz["status"] == "inactive" and oz["ucum_code"] == "[oz_av]"


def test_unit_filters(api: TestClient) -> None:
    by_kind = api.get("/v1/units", params={"quantity_kind_id": kind_id("mass")}).json()["data"]
    symbols = {u["symbol"] for u in by_kind}
    assert {"kg", "g", "sack"} <= symbols and "oz" not in symbols and "m" not in symbols
    by_ucum = api.get("/v1/units", params={"ucum_code": "kg"}).json()["data"]
    assert [u["unit_id"] for u in by_ucum] == [unit_id("kg")]
    assert api.get("/v1/units", params={"ucum_code": "KG"}).json()["data"] == []  # exacto
    by_unece = api.get("/v1/units", params={"unece_code": "KGM"}).json()["data"]
    assert [u["unit_id"] for u in by_unece] == [unit_id("kg")]
    # la asociación inactiva de °F con la diferencia de temperatura la excluye del filtro
    diff = api.get("/v1/units", params={"quantity_kind_id": kind_id("temperature_difference")})
    assert "°F" not in {u["symbol"] for u in diff.json()["data"]}
    everything = api.get(
        "/v1/units",
        params={"quantity_kind_id": kind_id("temperature_difference"), "include_inactive": "true"},
    )
    assert "°F" in {u["symbol"] for u in everything.json()["data"]}


def test_a_unit_filter_by_unknown_kind_is_404_and_by_malformed_kind_422(api: TestClient) -> None:
    missing = api.get("/v1/units", params={"quantity_kind_id": GHOST})
    assert missing.status_code == 404 and error_code(missing) == "quantity_kind_not_found"
    malformed = api.get("/v1/units", params={"quantity_kind_id": "nope"})
    assert malformed.status_code == 422 and error_code(malformed) == "invalid_quantity_kind_id"


def test_a_unit_by_id_exposes_names_and_associations(api: TestClient) -> None:
    celsius = api.get(f"/v1/units/{unit_id('Cel')}", params={"locale_id": EN})
    assert celsius.status_code == 200
    data = celsius.json()["data"]
    assert set(data) == UNIT_KEYS and data["name"] == "degree Celsius"
    # una sola identidad (CA-12) asociada a dos magnitudes
    kinds = {k["quantity_kind_id"]: k for k in data["quantity_kinds"]}
    assert set(kinds) == {kind_id("temperature"), kind_id("temperature_difference")}
    assert all(
        k["status"] == "active" and set(k) == {"quantity_kind_id", "status", "reference"}
        for k in kinds.values()
    )
    kelvin = api.get(f"/v1/units/{unit_id('K')}").json()["data"]
    assert all(k["reference"] for k in kelvin["quantity_kinds"])
    assert not any(k["reference"] for k in data["quantity_kinds"])
    sack = api.get(f"/v1/units/{SACK_ID}", params={"locale_id": ES}).json()["data"]
    assert (sack["ucum_code"], sack["unece_code"], sack["name"], sack["plural"]) == (
        None,
        None,
        "saco",
        None,
    )
    inactive = api.get(f"/v1/units/{unit_id('oz')}").json()["data"]
    assert inactive["status"] == "inactive"
    assert all(k["status"] == "inactive" for k in inactive["quantity_kinds"])


def test_unknown_unit_is_404_and_malformed_unit_422(api: TestClient) -> None:
    missing = api.get(f"/v1/units/{GHOST}")
    assert missing.status_code == 404 and error_code(missing) == "unit_not_found"
    malformed = api.get("/v1/units/nope")
    assert malformed.status_code == 422 and error_code(malformed) == "invalid_unit_id"


def test_the_fixed_version_route_is_not_swallowed_by_the_unit_id_route(api: TestClient) -> None:
    response = api.get("/v1/units/version")
    assert response.status_code == 200
    assert response.json() == {"snapshot_version": 3, "data": {"snapshot_version": 3}}
    # y un id con forma de UUID sigue siendo un id
    assert api.get(f"/v1/units/{unit_id('kg')}").json()["data"]["symbol"] == "kg"


# --- conversión (RF-21 a RF-31)


@pytest.mark.parametrize(
    ("payload", "result", "exact"),
    [
        (body("1000", "g", "kg"), "1", True),
        (body("1", "t", "kg"), "1000", True),
        (body("1", "ha", "m2", "area"), "10000", True),
        (body("1", "m3", "L", "volume"), "1000", True),
        (body("1", "h", "min", "duration"), "60", True),
        (body("0", "Cel", "K", "temperature"), "273.15", True),
        (body("32", "degF", "Cel", "temperature"), "0", True),
        (body("1", "Cel", "K", "temperature_difference"), "1", True),
        (body("150", "kg/ha", "g/m2", "mass_per_area"), "15", True),
        (body("1", "lb", "kg"), "0.45359237", True),
        (body("1", "kg", "lb"), "2.20462262184877580722973801345027", False),
        (body("-0", "kg", "g"), "0", True),
    ],
)
def test_a_conversion_succeeds_with_the_envelope_of_the_contract(
    api: TestClient, payload: dict[str, Any], result: str, exact: bool
) -> None:
    response = convert(api, payload)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "snapshot_version": 3,
        "data": {
            "result": result,
            "exact": exact,
            "unit_id": payload["to_unit_id"],
            "quantity_kind_id": payload["quantity_kind_id"],
            "catalog_version": 3,
        },
    }


def test_incompatible_and_missing_context_are_rejected_with_422(api: TestClient) -> None:
    kg_to_l = convert(api, body("1", "kg", "L", "mass"))
    assert kg_to_l.status_code == 422 and error_code(kg_to_l) == "incompatible_units"
    assert kg_to_l.json()["snapshot_version"] == 3
    assert set(kg_to_l.json()["error"]) == {"code", "message"}
    assert error_code(convert(api, body("1", "kg", "m", "length"))) == "incompatible_units"
    required = convert(api, body("1", "kg", "g", None))
    assert required.status_code == 422 and error_code(required) == "quantity_kind_required"
    assert error_code(convert(api, body("1", "kg", "g", None, quantity_kind_id=None))) == (
        "quantity_kind_required"
    )


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (body(quantity_kind_id="nope"), "invalid_quantity_kind_id"),
        (body(from_unit_id="nope"), "invalid_unit_id"),
        (body(to_unit_id="nope"), "invalid_unit_id"),
        (body(quantity_kind_id=GHOST), "quantity_kind_not_found"),
        (body(from_unit_id=GHOST), "unit_not_found"),
        (body(to_unit_id=GHOST), "unit_not_found"),
        (body("1", "oz", "kg"), "inactive_unit"),
        (body("1", "each", "each", "count"), "inactive_quantity_kind"),
        (body("1", "degF", "K", "temperature_difference"), "inactive_unit"),
        (body("1", "kg", "g", catalog_version=99), "catalog_version_not_available"),
        (body("1", "kg", "g", catalog_version=0), "invalid_catalog_version"),
        (body("1", "kg", "g", catalog_version=-1), "invalid_catalog_version"),
        (body("1", "kg", "g", catalog_version="1"), "invalid_catalog_version"),
        (body("1", "kg", "g", catalog_version=True), "invalid_catalog_version"),
        (body("1", "kg", "g", catalog_version=1.5), "invalid_catalog_version"),
        (body("999999999999999999999999999999", "sack", "kg"), "result_not_representable"),
    ],
)
def test_every_rejection_is_422_with_its_stable_code(
    api: TestClient, payload: dict[str, Any], code: str
) -> None:
    response = convert(api, payload)
    assert response.status_code == 422, response.text
    assert error_code(response) == code
    assert set(response.json()) == {"snapshot_version", "error"}


@pytest.mark.parametrize(
    "value", ["1e3", "+1", "1,5", ".5", "5.", "007", " 1", "NaN", "", "Infinity"]
)
def test_invalid_value_forms_are_rejected(api: TestClient, value: str) -> None:
    response = convert(api, body(value))
    assert response.status_code == 422 and error_code(response) == "invalid_value"


@pytest.mark.parametrize("value", [1, 1000, 1.5, True, None, [1], {"a": 1}])
def test_a_value_that_is_not_a_json_string_is_invalid_value(api: TestClient, value: Any) -> None:
    response = convert(api, body(value))
    assert response.status_code == 422 and error_code(response) == "invalid_value"


def test_value_extremes(api: TestClient) -> None:
    thirty = "9" * 30
    ok = convert(api, body(f"-{thirty}.{thirty}", "kg", "kg"))
    assert ok.status_code == 200
    too_long = convert(api, body("9" * 31))
    assert error_code(too_long) == "invalid_value"
    assert error_code(convert(api, body("0." + "1" * 31))) == "invalid_value"


@pytest.mark.parametrize(
    "payload",
    [
        {**body(), "extra": 1},
        {**body(), "tenant_id": GHOST},
        {k: v for k, v in body().items() if k != "value"},
        {k: v for k, v in body().items() if k != "from_unit_id"},
        {k: v for k, v in body().items() if k != "to_unit_id"},
        body(from_unit_id=5),
        body(to_unit_id=None),
        body(quantity_kind_id=7),
        [],
        "text",
        5,
        None,
    ],
)
def test_a_body_with_the_wrong_shape_is_invalid_request(api: TestClient, payload: Any) -> None:
    response = convert(api, payload)
    assert response.status_code == 422 and error_code(response) == "invalid_request"
    assert response.json()["snapshot_version"] == 3


@pytest.mark.parametrize("raw", [b"", b"{", b"not json", b"\xff\xfe"])
def test_an_unparseable_body_is_invalid_request(api: TestClient, raw: bytes) -> None:
    response = api.post(
        "/v1/conversions", content=raw, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422 and error_code(response) == "invalid_request"


def test_a_historical_conversion_is_reproducible_byte_for_byte(api: TestClient) -> None:
    """CA-5, CA-7."""
    sack = body("2", "sack", "kg", catalog_version=1)
    first = convert(api, sack)
    assert first.json()["data"]["result"] == "120" and first.json()["data"]["catalog_version"] == 1
    assert first.json()["snapshot_version"] == 3  # la vigente
    assert (
        convert(api, body("2", "sack", "kg", catalog_version=2)).json()["data"]["result"] == "100"
    )
    assert first.content == convert(api, sack).content
    # oz: inactiva ahora, activa en la versión 1
    assert error_code(convert(api, body("1", "oz", "kg"))) == "inactive_unit"
    then = convert(api, body("1", "oz", "kg", catalog_version=1))
    assert then.status_code == 200 and then.json()["data"]["result"] == "0.028349523125"


def test_404_422_and_503_are_distinguishable_for_conversions_and_there_is_no_404(
    api: TestClient,
) -> None:
    statuses = {convert(api, p).status_code for p in (body(from_unit_id=GHOST), body("x"), body())}
    assert statuses == {422, 200}


# --- métodos (RF-38)


@pytest.mark.parametrize("method", ["put", "patch", "delete", "post"])
def test_no_write_method_exists_on_the_read_routes(api: TestClient, method: str) -> None:
    for path in (
        "/v1/quantity-kinds",
        f"/v1/quantity-kinds/{kind_id('mass')}",
        "/v1/units",
        "/v1/units/version",
        f"/v1/units/{unit_id('kg')}",
    ):
        assert api.request(method, path, json={}).status_code == 405, (method, path)


@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_conversions_accept_only_post(api: TestClient, method: str) -> None:
    assert api.request(method, "/v1/conversions", json={}).status_code == 405


# --- sin tenant, catálogo vacío y falla técnica


def _keys(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [*node, *(k for value in node.values() for k in _keys(value))]
    if isinstance(node, list):
        return [k for item in node for k in _keys(item)]
    return []


def test_no_response_carries_a_tenant_or_consumer_data(api: TestClient) -> None:
    responses = [
        api.get("/v1/quantity-kinds", params={"include_inactive": "true"}),
        api.get(f"/v1/quantity-kinds/{kind_id('mass')}"),
        api.get("/v1/units", params={"include_inactive": "true", "locale_id": EN}),
        api.get(f"/v1/units/{unit_id('Cel')}"),
        api.get("/v1/units/version"),
        convert(api, body()),
        convert(api, body("1", "kg", "L")),
    ]
    forbidden = {"tenant_id", "organization_id", "factor", "offset", "region_id", "country_id"}
    for response in responses:
        assert not forbidden & set(_keys(response.json()))


def test_an_empty_catalog_is_never_a_server_error(postgres_with_roles: str) -> None:
    name, url = prepared_database(postgres_with_roles, units=False)
    try:
        api = client_for(url)
        kinds = api.get("/v1/quantity-kinds")
        assert kinds.status_code == 200 and kinds.json() == {"snapshot_version": None, "data": []}
        assert api.get("/v1/units").json() == {"snapshot_version": None, "data": []}
        assert api.get("/v1/units/version").json()["snapshot_version"] is None
        assert api.get(f"/v1/units/{unit_id('kg')}").status_code == 404
        assert api.get(f"/v1/quantity-kinds/{kind_id('mass')}").status_code == 404
        assert api.get("/v1/units", params={"quantity_kind_id": kind_id("mass")}).status_code == 404
        missing = convert(api, body())
        assert missing.status_code == 422
        assert error_code(missing) == "catalog_version_not_available"
        assert missing.json()["snapshot_version"] is None
        assert error_code(convert(api, body(catalog_version=1))) == "catalog_version_not_available"
        # una solicitud mal formada recibe su código de validación aunque el catálogo esté vacío
        assert error_code(convert(api, body("1e3"))) == "invalid_value"
        assert error_code(convert(api, body(from_unit_id="nope"))) == "invalid_unit_id"
        assert error_code(convert(api, body(kind=None))) == "quantity_kind_required"
        assert error_code(convert(api, body(extra=1))) == "invalid_request"
    finally:
        with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def test_a_technical_failure_is_503_never_404_or_422_and_leaks_no_credentials() -> None:
    dead = "postgresql://u:s3cr3t@127.0.0.1:1/none?connect_timeout=2"
    api = client_for(dead, reader=postgres_units_reader(dead))
    requests = [
        ("get", "/v1/quantity-kinds"),
        ("get", f"/v1/quantity-kinds/{kind_id('mass')}"),
        ("get", "/v1/units"),
        ("get", f"/v1/units/{unit_id('kg')}"),
        ("get", "/v1/units/version"),
        ("post", "/v1/conversions"),
    ]
    for method, path in requests:
        response = api.request(method, path, json=body() if method == "post" else None)
        assert response.status_code == 503, path
        assert error_code(response) == "technical_error"
        assert "s3cr3t" not in response.text
    # incluso una solicitud mal formada necesita la versión vigente para el sobre
    assert api.post("/v1/conversions", json={}).status_code == 503


# --- caché, composición y contratos publicados


class CountingReader:
    """Envuelve un lector real y cuenta las lecturas de artefacto."""

    def __init__(self, inner: UnitsReader) -> None:
        self.inner = inner
        self.artifact_reads: list[int] = []

    def session(self) -> AbstractContextManager[UnitsSession]:
        outer = self

        class Session:
            def __init__(self, session: UnitsSession) -> None:
                self._session = session

            def __getattr__(self, name: str) -> Any:
                return getattr(self._session, name)

            def artifact(self, snapshot_version: int) -> Any:
                outer.artifact_reads.append(snapshot_version)
                return self._session.artifact(snapshot_version)

        from contextlib import contextmanager

        @contextmanager
        def wrapped() -> Iterator[UnitsSession]:
            with self.inner.session() as session:
                yield Session(session)

        return wrapped()


def test_the_conversion_cache_is_per_app_and_reads_each_version_once(reader_url: str) -> None:
    first, second = (CountingReader(postgres_units_reader(reader_url)) for _ in range(2))
    apps = [client_for(reader_url, reader=r) for r in (first, second)]
    for client in apps:
        for _ in range(3):
            assert convert(client, body()).status_code == 200
            assert convert(client, body(catalog_version=1)).status_code == 200
    assert sorted(first.artifact_reads) == [1, 3]
    assert sorted(second.artifact_reads) == [1, 3]  # otra instancia, otra caché


def test_the_published_openapi_matches_the_generated_one_and_is_served(api: TestClient) -> None:
    published = json.loads((CONTRACTS / "units-api.v1.openapi.json").read_text("utf-8"))
    assert units_openapi_document() == published
    served = api.get("/v1/openapi/units.json")
    assert served.status_code == 200 and served.json() == published


def test_the_four_existing_contracts_do_not_change(api: TestClient) -> None:
    def published(name: str) -> Any:
        return json.loads((CONTRACTS / name).read_text("utf-8"))

    assert openapi_document() == published("locales-api.v1.openapi.json")
    assert regions_openapi_document() == published("regions-api.v1.openapi.json")
    assert countries_openapi_document() == published("countries-api.v1.openapi.json")
    assert currencies_openapi_document() == published("currencies-api.v1.openapi.json")
    assert api.get("/v1/openapi.json").json() == published("locales-api.v1.openapi.json")
    assert api.get("/v1/openapi/currencies.json").json() == published(
        "currencies-api.v1.openapi.json"
    )


def test_the_openapi_declares_the_operations_and_the_outcomes() -> None:
    document = units_openapi_document()
    assert set(document["paths"]) == {
        "/v1/quantity-kinds",
        "/v1/quantity-kinds/{quantity_kind_id}",
        "/v1/units",
        "/v1/units/version",
        "/v1/units/{unit_id}",
        "/v1/conversions",
    }
    for path, operations in document["paths"].items():
        expected = {"post"} if path == "/v1/conversions" else {"get"}
        assert set(operations) == expected, path
        assert "200" in operations[next(iter(operations))]["responses"]
        assert "503" in operations[next(iter(operations))]["responses"]
    post = document["paths"]["/v1/conversions"]["post"]
    assert "422" in post["responses"] and "404" not in post["responses"]
    for code in ("invalid_value", "invalid_request", "result_not_representable"):
        assert code in post["responses"]["422"]["description"]
    assert document["components"]["schemas"]["ConversionBody"]["additionalProperties"] is False
    properties = {
        name
        for schema in document["components"]["schemas"].values()
        for name in schema.get("properties", {})
    }
    assert not {"tenant_id", "factor", "offset", "price", "quantity"} & properties
    assert document["info"]["version"] == "1.0.0"


def test_units_next_to_the_other_apis_keeps_their_routes(api: TestClient) -> None:
    assert api.get("/v1/countries").status_code == 200
    assert api.get("/v1/regions").status_code == 200
    assert api.get("/v1/currencies").status_code in (200, 404)  # sin datos de Currency en esta base
    assert api.get("/v1/locales").status_code in (200, 404)


def test_an_app_built_without_units_does_not_serve_its_routes() -> None:
    from tests.fixtures.country_fakes import FakeCountryReader
    from tests.fixtures.fakes import FakeReader
    from tests.fixtures.region_fakes import FakeRegionReader

    api = TestClient(
        create_catalog_app(
            FakeReader(), FakeRegionReader(), FakeCountryReader(), country_flag_store()
        )
    )
    assert api.get("/v1/units").status_code == 404
    assert api.post("/v1/conversions", json={}).status_code in (404, 405)


def test_the_reader_url_uses_the_least_privileged_role(reader_url: str) -> None:
    with psycopg.connect(reader_url, autocommit=True) as conn:
        assert conn.execute("SELECT current_user").fetchone() == ("reference_reader",)
