"""T8: API pública read-only de Regions sobre datos incorporados (RF-14–RF-20, RF-37, RNF-1,
RNF-2, RNF-4) y composición con la API de Locale (D4, D5)."""

import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from gi_common_reference.app import (
    app_from_environment,
    belongs_to_regions,
    create_catalog_app,
    openapi_document,
    regions_openapi_document,
)
from gi_common_reference.bootstrap import (
    country_flag_store,
    postgres_country_reader,
    postgres_reader,
    postgres_region_reader,
    postgres_region_repository,
    postgres_repository,
    required_locales,
)
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.regions.application.incorporate import Outcome, incorporate_snapshot
from tests.conftest import NetworkGuard, alembic_config, with_database
from tests.fixtures.country_fakes import FakeCountryReader
from tests.fixtures.fakes import FakeReader
from tests.fixtures.region_fakes import FakeRegionReader
from tests.fixtures.regions import (
    EN,
    ES,
    FR,
    build_snapshot,
    locale_snapshot,
    recoding,
    region,
    region_id,
    seal,
    subregion,
    subregion_id,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "regions-api.v1.openapi.json"
LOCALES_CONTRACT = ROOT / "contracts" / "locales-api.v1.openapi.json"
READER_URL = "REFERENCE_READER_DATABASE_URL"


def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
    """v1: Africa y Americas con sus subregiones; 019 también en francés.
    v2: 021 se recodifica a 456, 202 pasa a inactive y se agrega Asia (142) inactive."""
    v1 = build_snapshot(1)
    v1["region_names"].append({"region_id": region_id("019"), "locale_id": FR, "name": "Amériques"})
    v1 = seal(v1)
    v2 = build_snapshot(
        2,
        regions=[region("002"), region("019"), region("142", status="inactive")],
        subregions=[
            subregion("015"),
            subregion("202", status="inactive"),
            subregion("419"),
            subregion("021", code="456"),
        ],
        recodings=[recoding("subregion", "021", "021", "456")],
    )
    v2["region_names"].append({"region_id": region_id("019"), "locale_id": FR, "name": "Amériques"})
    return v1, seal(v2)


@pytest.fixture(scope="module")
def reader_url(postgres_with_roles: str) -> Iterator[str]:
    """Una base con Locale y los dos snapshots de Regions; la API se conecta como reader."""
    name = f"api_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = with_database(postgres_with_roles, name)
    command.upgrade(alembic_config(url), "head")
    incorporate_locales(locale_snapshot(1), postgres_repository(url))
    for document in scenario():
        result = incorporate_snapshot(document, postgres_region_repository(url), required_locales())
        assert result.outcome is Outcome.INCORPORATED, result.violations
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("ALTER ROLE reference_reader LOGIN PASSWORD 'reader-pw'")
    yield make_conninfo(url, user="reference_reader", password="reader-pw")
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def api(reader_url: str) -> TestClient:
    return TestClient(app_from_environment({READER_URL: reader_url}))


def codes(response: Any) -> list[str | None]:
    return [item["code"] for item in response.json()["data"]]


# --- listados (RF-14, RF-15, RF-18) -----------------------------------------------------------


def test_regions_are_listed_in_code_order_with_the_catalog_version(api: TestClient) -> None:
    response = api.get("/v1/regions")
    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_version"] == 2
    assert codes(response) == ["002", "019", "142"]
    assert all(item["name"] is None for item in body["data"])
    assert set(body["data"][0]) == {"region_id", "code", "status", "replacement_region_id", "name"}


def test_regions_can_be_restricted_to_active(api: TestClient) -> None:
    assert codes(api.get("/v1/regions", params={"status": "active"})) == ["002", "019"]
    assert codes(api.get("/v1/regions", params={"status": "inactive"})) == ["142"]


def test_names_come_in_the_requested_locale_without_fallback(api: TestClient) -> None:
    english = api.get("/v1/regions", params={"locale_id": EN}).json()["data"]
    assert [item["name"] for item in english] == ["Africa", "Americas", "Asia"]
    spanish = api.get("/v1/regions", params={"locale_id": ES.upper()}).json()["data"]
    assert spanish[1]["name"] == "Américas"
    french = api.get("/v1/regions", params={"locale_id": FR}).json()["data"]
    assert [item["name"] for item in french] == [None, "Amériques", None]


def test_subregions_are_listed_with_their_region_and_filters(api: TestClient) -> None:
    everything = api.get("/v1/subregions")
    assert everything.status_code == 200
    assert codes(everything) == ["015", "202", "419", "456"]
    item = everything.json()["data"][2]
    assert item["region_id"] == region_id("019") and item["subregion_id"] == subregion_id("419")
    americas = api.get("/v1/subregions", params={"region_id": region_id("019").upper()})
    assert codes(americas) == ["419", "456"]
    active = api.get("/v1/subregions", params={"status": "active", "region_id": region_id("002")})
    assert codes(active) == ["015"]
    unknown = api.get("/v1/subregions", params={"region_id": str(uuid.uuid4())})
    assert unknown.status_code == 200 and unknown.json()["data"] == []
    spanish = api.get("/v1/subregions", params={"locale_id": ES}).json()["data"]
    assert spanish[2]["name"] == "América Latina y el Caribe"


@pytest.mark.parametrize(
    ("path", "params", "error"),
    [
        ("/v1/regions", {"locale_id": "es"}, "invalid_locale_id"),
        ("/v1/regions", {"locale_id": str(uuid.uuid4())}, "unknown_locale"),
        ("/v1/regions", {"status": "deprecated"}, "invalid_status"),
        ("/v1/subregions", {"region_id": "019"}, "invalid_region_id"),
        ("/v1/subregions", {"status": "ACTIVE"}, "invalid_status"),
        ("/v1/subregions", {"locale_id": str(uuid.uuid4())}, "unknown_locale"),
        ("/v1/regions/by-code/019", {"locale_id": "en"}, "invalid_locale_id"),
        (f"/v1/regions/{region_id('019')}", {"locale_id": str(uuid.uuid4())}, "unknown_locale"),
        ("/v1/subregions/by-code/19", {}, "invalid_code"),
        ("/v1/regions/by-code/0019", {}, "invalid_code"),
        ("/v1/regions/by-code/abc", {}, "invalid_code"),
    ],
)
def test_invalid_parameters_are_422_distinct_from_404(
    api: TestClient, path: str, params: dict[str, str], error: str
) -> None:
    response = api.get(path, params=params)
    assert response.status_code == 422
    assert response.json() == {
        "snapshot_version": 2,
        "error": {"code": error, "message": response.json()["error"]["message"]},
    }


# --- por id y por código (RF-16, RF-17) --------------------------------------------------------


def test_an_entity_is_found_by_id_whatever_its_status(api: TestClient) -> None:
    response = api.get(f"/v1/regions/{region_id('142')}", params={"locale_id": EN})
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["code"], data["status"]) == ("142", "inactive")
    sub = api.get(f"/v1/subregions/{subregion_id('202').upper()}").json()
    assert sub["snapshot_version"] == 2 and sub["data"]["status"] == "inactive"
    assert sub["data"]["region_id"] == region_id("002")


@pytest.mark.parametrize(
    "path",
    [
        f"/v1/regions/{uuid.uuid4()}",
        "/v1/regions/not-a-uuid",
        f"/v1/subregions/{region_id('019')}",
        f"/v1/regions/{subregion_id('419')}",
    ],
)
def test_an_unknown_id_is_404(api: TestClient, path: str) -> None:
    response = api.get(path)
    assert response.status_code == 404
    assert response.json()["snapshot_version"] == 2
    assert response.json()["error"]["code"] == "not_found"


def test_lookup_by_code_uses_the_current_code(api: TestClient) -> None:
    americas = api.get("/v1/regions/by-code/019", params={"locale_id": ES}).json()["data"]
    assert americas["region_id"] == region_id("019") and americas["name"] == "Américas"
    assert api.get("/v1/regions/by-code/419").status_code == 404
    latam = api.get("/v1/subregions/by-code/419")
    assert latam.status_code == 200 and latam.json()["data"]["subregion_id"] == subregion_id("419")
    recoded = api.get("/v1/subregions/by-code/456").json()["data"]
    assert recoded["subregion_id"] == subregion_id("021")


def test_a_historical_code_is_not_found(api: TestClient) -> None:
    response = api.get("/v1/subregions/by-code/021")
    assert response.status_code == 404 and response.json()["snapshot_version"] == 2


def test_the_code_of_an_inactive_entity_still_resolves(api: TestClient) -> None:
    data = api.get("/v1/regions/by-code/142").json()["data"]
    assert (data["region_id"], data["status"]) == (region_id("142"), "inactive")
    assert api.get("/v1/subregions/by-code/202").json()["data"]["status"] == "inactive"


# --- solo lectura, determinismo, red -----------------------------------------------------------


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize(
    "path", ["/v1/regions", f"/v1/regions/{region_id('019')}", "/v1/subregions/by-code/419"]
)
def test_the_api_is_read_only(api: TestClient, method: str, path: str) -> None:
    assert getattr(api, method)(path).status_code == 405


def test_repeated_queries_return_the_same(api: TestClient) -> None:
    paths = ["/v1/regions", "/v1/subregions", "/v1/subregions/by-code/456"]
    first = [api.get(path, params={"locale_id": EN}).json() for path in paths]
    again = [api.get(path, params={"locale_id": EN}).json() for path in paths]
    assert first == again


def test_the_api_answers_without_network(reader_url: str, network_guard: NetworkGuard) -> None:
    with network_guard:
        client = TestClient(app_from_environment({READER_URL: reader_url}))
        assert client.get("/v1/regions").status_code == 200
        assert client.get("/v1/subregions/by-code/419").status_code == 200
    assert network_guard.blocked == []


def test_the_reader_role_cannot_write_through_the_api_connection(reader_url: str) -> None:
    with psycopg.connect(reader_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE reference.region SET status = 'inactive'")


# --- catálogo vacío y no disponible ------------------------------------------------------------


@pytest.fixture
def empty(database_factory: Callable[[], str]) -> TestClient:
    url = database_factory()
    incorporate_locales(locale_snapshot(1), postgres_repository(url))
    return TestClient(
        create_catalog_app(
            postgres_reader(url),
            postgres_region_reader(url),
            postgres_country_reader(url),
            country_flag_store(),
        )
    )


def test_an_empty_catalog_is_never_an_error(empty: TestClient) -> None:
    assert empty.get("/v1/regions").json() == {"snapshot_version": None, "data": []}
    assert empty.get("/v1/subregions", params={"locale_id": EN}).json() == {
        "snapshot_version": None,
        "data": [],
    }
    for path in ("/v1/regions/by-code/019", f"/v1/subregions/{uuid.uuid4()}"):
        response = empty.get(path)
        assert response.status_code == 404 and response.json()["snapshot_version"] is None


def test_an_unavailable_database_is_503_without_details() -> None:
    reader = FakeRegionReader()
    reader.unavailable = True
    client = TestClient(
        create_catalog_app(FakeReader(), reader, FakeCountryReader(), country_flag_store())
    )
    response = client.get("/v1/regions")
    assert response.status_code == 503
    assert response.json() == {
        "snapshot_version": None,
        "error": {"code": "unavailable", "message": "el catálogo no está disponible"},
    }


def test_each_query_uses_a_single_session() -> None:
    reader = FakeRegionReader(version=1, locale_ids=[EN])
    client = TestClient(
        create_catalog_app(FakeReader(), reader, FakeCountryReader(), country_flag_store())
    )
    client.get("/v1/regions", params={"locale_id": EN})
    client.get("/v1/subregions/by-code/419", params={"locale_id": EN})
    assert reader.sessions == 2


# --- composición y contratos -------------------------------------------------------------------


def test_the_locales_api_keeps_answering_in_the_same_application(api: TestClient) -> None:
    locales = api.get("/v1/locales")
    assert locales.status_code == 200
    assert {item["code"] for item in locales.json()["data"]} == {"en", "es", "fr"}
    published = json.loads(LOCALES_CONTRACT.read_text(encoding="utf-8"))
    assert api.get("/v1/openapi.json").json() == published
    assert openapi_document() == published


def test_the_regions_openapi_matches_the_published_contract(api: TestClient) -> None:
    published = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert regions_openapi_document() == published
    assert api.get("/v1/openapi/regions.json").json() == published


def test_the_regions_contract_declares_only_get_operations_and_its_errors() -> None:
    document = regions_openapi_document()
    assert set(document["paths"]) == {
        "/v1/regions",
        "/v1/regions/{region_id}",
        "/v1/regions/by-code/{code}",
        "/v1/subregions",
        "/v1/subregions/{subregion_id}",
        "/v1/subregions/by-code/{code}",
    }
    for operations in document["paths"].values():
        assert set(operations) == {"get"}
        assert {"200", "422"} <= set(operations["get"]["responses"])
    schemas = document["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    assert "tenant_id" not in json.dumps(document)
    assert set(schemas["Subregion"]["properties"]) == {
        "subregion_id",
        "region_id",
        "code",
        "status",
        "replacement_subregion_id",
        "name",
    }


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/v1/regions", True),
        ("/v1/regions/by-code/019", True),
        ("/v1/subregions/x", True),
        ("/v1/openapi/regions.json", True),
        ("/v1/regionsx", False),
        ("/v1/locales", False),
        ("/v1/openapi.json", False),
        ("/", False),
    ],
)
def test_requests_are_routed_by_path(path: str, expected: bool) -> None:
    assert belongs_to_regions(path) is expected
