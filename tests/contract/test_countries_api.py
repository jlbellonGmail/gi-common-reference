"""T9: API pública read-only de Countries sobre datos incorporados.

RF-8–RF-18, RF-37, RF-38, RF-50, RNF-1, RNF-6, RNF-8, RNF-9, y composición con Locale y Regions.
"""

import json
import shutil
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
    belongs_to_countries,
    belongs_to_regions,
    countries_openapi_document,
    create_catalog_app,
    openapi_document,
    regions_openapi_document,
)
from gi_common_reference.bootstrap import (
    postgres_country_reader,
    postgres_country_repository,
    postgres_reader,
    postgres_region_reader,
    postgres_region_repository,
    postgres_repository,
    required_locales,
)
from gi_common_reference.countries.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.countries.infrastructure.flag_store import DirectoryFlagStore
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.regions.application.incorporate import (
    incorporate_snapshot as incorporate_regions,
)
from tests.conftest import NetworkGuard, alembic_config, with_database
from tests.fixtures.countries import (
    FLAGS_DIR,
    POLICY,
    build_snapshot,
    country,
    country_id,
    flag,
    flag_bytes,
    flag_digest,
    flag_exception,
    names,
    recoding,
    regions_snapshot,
    seal,
)
from tests.fixtures.country_fakes import FakeCountryReader
from tests.fixtures.fakes import FakeReader
from tests.fixtures.region_fakes import FakeRegionReader
from tests.fixtures.regions import EN, ES, FR, locale_snapshot, region_id, subregion_id

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "countries-api.v1.openapi.json"
REGIONS_CONTRACT = ROOT / "contracts" / "regions-api.v1.openapi.json"
LOCALES_CONTRACT = ROOT / "contracts" / "locales-api.v1.openapi.json"
READER_URL = "REFERENCE_READER_DATABASE_URL"
BASE = ("AR", "NA", "AQ", "TW", "US", "CA", "PR", "BV")
FRENCH_AR = {
    "country_id": country_id("AR"),
    "locale_id": FR,
    "name": "Argentine",
    "official_name": "République argentine",
}
ACTIVE = ["AF", "AQ", "AR", "BV", "CA", "NA", "PR", "TL", "TW", "US"]


def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
    """v1: los países base + AF (004), TP y AN; AR también en francés.
    v2: TP se recodifica a TL (mismo id) y AN se retira (`inactive`)."""
    v1 = build_snapshot(1, keys=(*BASE, "AF", "TP", "AN"))
    v1["country_names"].append(FRENCH_AR)
    keys = (*BASE, "AF")
    v2 = build_snapshot(
        2,
        countries=[
            *(country(k) for k in keys),
            country("TL", identity="TP"),
            country("AN", status="inactive"),
        ],
        country_names=[
            *(n for k in keys for n in names(k)),
            *names("TP"),
            *names("AN"),
            FRENCH_AR,
        ],
        flags=[*(flag(k) for k in keys if k not in ("AQ", "BV")), flag("TP"), flag("AN")],
        flag_exceptions=[flag_exception("AQ"), flag_exception("BV")],
        recodings=[recoding("TP", ("TP", "TMP", "626"), ("TL", "TLS", "626"))],
    )
    return seal(v1), seal(v2)


@pytest.fixture(scope="module")
def reader_url(postgres_with_roles: str) -> Iterator[str]:
    """Una base con Locale, Regions y los dos snapshots de Countries; la API usa `reader`."""
    name = f"api_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = with_database(postgres_with_roles, name)
    command.upgrade(alembic_config(url), "head")
    incorporate_locales(locale_snapshot(1), postgres_repository(url))
    incorporate_regions(regions_snapshot(1), postgres_region_repository(url), required_locales())
    store = DirectoryFlagStore(FLAGS_DIR)
    for document in scenario():
        result = incorporate_snapshot(document, postgres_country_repository(url), POLICY, store)
        assert result.outcome is Outcome.INCORPORATED, result.violations
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("ALTER ROLE reference_reader LOGIN PASSWORD 'reader-pw'")
    yield make_conninfo(url, user="reference_reader", password="reader-pw")
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def client_for(url: str, flags_dir: Path = FLAGS_DIR) -> TestClient:
    return TestClient(
        create_catalog_app(
            postgres_reader(url),
            postgres_region_reader(url),
            postgres_country_reader(url),
            DirectoryFlagStore(flags_dir),
        )
    )


@pytest.fixture
def api(reader_url: str) -> TestClient:
    return client_for(reader_url)


def alpha2(response: Any) -> list[str]:
    return [item["alpha2"] for item in response.json()["data"]]


# --- listado (RF-13, RF-15, RF-16, RF-38) ---------------------------------------------------------


def test_the_default_list_is_active_countries_in_binary_alpha2_order(api: TestClient) -> None:
    response = api.get("/v1/countries")
    assert response.status_code == 200
    assert response.json()["snapshot_version"] == 2
    assert alpha2(response) == ACTIVE
    first = response.json()["data"][0]
    assert set(first) == {
        "country_id",
        "alpha2",
        "alpha3",
        "numeric_code",
        "status",
        "replacement_country_id",
        "region_id",
        "subregion_id",
        "calling_code",
        "name",
        "official_name",
    }
    assert first["name"] is None and first["official_name"] is None


def test_inactive_countries_are_listed_only_on_request(api: TestClient) -> None:
    assert alpha2(api.get("/v1/countries", params={"status": "all"})) == [
        "AF",
        "AN",
        *ACTIVE[1:],
    ]
    assert alpha2(api.get("/v1/countries", params={"status": "inactive"})) == ["AN"]
    assert alpha2(api.get("/v1/countries", params={"status": "active"})) == ACTIVE


def test_the_list_can_be_filtered_by_region_and_subregion(api: TestClient) -> None:
    americas = api.get("/v1/countries", params={"region_id": region_id("019").upper()})
    assert alpha2(americas) == ["AR", "BV", "CA", "PR", "US"]
    northern = api.get("/v1/countries", params={"subregion_id": subregion_id("021")})
    assert alpha2(northern) == ["CA", "US"]
    both = api.get(
        "/v1/countries",
        params={
            "region_id": region_id("019"),
            "subregion_id": subregion_id("419"),
            "status": "all",
        },
    )
    assert alpha2(both) == ["AN", "AR", "BV", "PR"]
    unknown = api.get("/v1/countries", params={"region_id": str(uuid.uuid4())})
    assert unknown.status_code == 200 and unknown.json()["data"] == []


def test_names_come_from_the_requested_locale_without_fallback(api: TestClient) -> None:
    english = {
        c["alpha2"]: c for c in api.get("/v1/countries", params={"locale_id": EN}).json()["data"]
    }
    assert (
        english["AR"]["name"] == "Argentina"
        and english["AR"]["official_name"] == "Argentine Republic"
    )
    assert english["CA"]["official_name"] is None  # sin official_name: ausente, no inventado
    spanish = api.get("/v1/countries", params={"locale_id": ES.upper()}).json()["data"]
    assert {c["alpha2"]: c["name"] for c in spanish}["US"] == "Estados Unidos"
    french = {
        c["alpha2"]: c for c in api.get("/v1/countries", params={"locale_id": FR}).json()["data"]
    }
    assert french["AR"]["name"] == "Argentine"
    assert french["NA"]["name"] is None and french["NA"]["official_name"] is None  # sin fallback


@pytest.mark.parametrize(
    ("path", "params", "error"),
    [
        ("/v1/countries", {"locale_id": "es"}, "invalid_locale_id"),
        ("/v1/countries", {"locale_id": str(uuid.uuid4())}, "unknown_locale"),
        ("/v1/countries", {"status": "deprecated"}, "invalid_status"),
        ("/v1/countries", {"status": "ACTIVE"}, "invalid_status"),
        ("/v1/countries", {"region_id": "019"}, "invalid_region_id"),
        ("/v1/countries", {"subregion_id": "419"}, "invalid_subregion_id"),
        ("/v1/countries/by-alpha2/ar", {"locale_id": "en"}, "invalid_locale_id"),
        (f"/v1/countries/{country_id('AR')}", {"locale_id": str(uuid.uuid4())}, "unknown_locale"),
        ("/v1/countries/by-alpha2/A1", {}, "invalid_code"),
        ("/v1/countries/by-alpha2/ARG", {}, "invalid_code"),
        ("/v1/countries/by-alpha2/%20ar", {}, "invalid_code"),
        ("/v1/countries/by-alpha2/a-r", {}, "invalid_code"),
        ("/v1/countries/by-alpha3/AR", {}, "invalid_code"),
        ("/v1/countries/by-alpha3/AR1", {}, "invalid_code"),
        ("/v1/countries/by-numeric/4", {}, "invalid_code"),
        ("/v1/countries/by-numeric/04", {}, "invalid_code"),
        ("/v1/countries/by-numeric/0004", {}, "invalid_code"),
        ("/v1/countries/by-numeric/na", {}, "invalid_code"),
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


# --- por id, alpha2, alpha3 y numérico (RF-8–RF-15) -----------------------------------------------


def test_a_country_resolves_the_same_by_id_and_by_every_code(api: TestClient) -> None:
    by_id = api.get(f"/v1/countries/{country_id('AR')}", params={"locale_id": EN})
    assert by_id.status_code == 200
    expected = by_id.json()
    assert expected["snapshot_version"] == 2
    assert expected["data"]["alpha2"] == "AR" and expected["data"]["numeric_code"] == "032"
    for path in (
        "by-alpha2/ar",
        "by-alpha2/AR",
        "by-alpha3/arg",
        "by-alpha3/ARG",
        "by-numeric/032",
    ):
        response = api.get(f"/v1/countries/{path}", params={"locale_id": EN})
        assert response.status_code == 200 and response.json() == expected, path
    assert api.get(f"/v1/countries/{country_id('AR').upper()}").status_code == 200


def test_namibia_is_not_null_and_leading_zeros_survive(api: TestClient) -> None:
    for code in ("NA", "na", "Na"):
        found = api.get(f"/v1/countries/by-alpha2/{code}").json()["data"]
        assert (found["alpha2"], found["alpha3"], found["numeric_code"]) == ("NA", "NAM", "516")
    afghanistan = api.get("/v1/countries/by-numeric/004").json()["data"]
    assert (afghanistan["alpha2"], afghanistan["numeric_code"]) == ("AF", "004")
    assert api.get("/v1/countries/by-alpha3/nam").json()["data"]["alpha2"] == "NA"


def test_shared_calling_codes_and_optional_fields_are_returned_as_is(api: TestClient) -> None:
    data = {c["alpha2"]: c for c in api.get("/v1/countries").json()["data"]}
    assert {data[k]["calling_code"] for k in ("US", "CA", "PR")} == {"1"}
    assert data["BV"]["calling_code"] is None
    assert data["AQ"]["region_id"] is None and data["AQ"]["subregion_id"] is None
    assert data["TW"]["region_id"] is None
    assert data["NA"]["region_id"] == region_id("002") and data["NA"][
        "subregion_id"
    ] == subregion_id("202")


@pytest.mark.parametrize(
    "path",
    [
        f"/v1/countries/{uuid.uuid4()}",
        "/v1/countries/not-a-uuid",
        "/v1/countries/by-alpha2/ZZ",
        "/v1/countries/by-alpha3/ZZZ",
        "/v1/countries/by-numeric/999",
    ],
)
def test_an_unknown_id_or_code_is_404(api: TestClient, path: str) -> None:
    response = api.get(path)
    assert response.status_code == 404
    assert response.json()["snapshot_version"] == 2
    assert response.json()["error"]["code"] == "country_not_found"


def test_active_inactive_and_not_found_are_distinguishable(api: TestClient) -> None:
    """RF-14."""
    active = api.get(f"/v1/countries/{country_id('AR')}").json()["data"]["status"]
    inactive = api.get(f"/v1/countries/{country_id('AN')}")
    missing = api.get(f"/v1/countries/{uuid.uuid4()}")
    assert (active, inactive.status_code, inactive.json()["data"]["status"]) == (
        "active",
        200,
        "inactive",
    )
    assert missing.status_code == 404


def test_the_code_of_an_inactive_country_still_resolves_with_its_status(api: TestClient) -> None:
    data = api.get("/v1/countries/by-alpha2/AN").json()["data"]
    assert (data["country_id"], data["status"]) == (country_id("AN"), "inactive")
    assert api.get("/v1/countries/by-numeric/530").json()["data"]["status"] == "inactive"


def test_a_recoded_country_resolves_by_its_current_codes_not_the_historical(
    api: TestClient,
) -> None:
    tl = api.get("/v1/countries/by-alpha2/TL").json()["data"]
    assert tl["country_id"] == country_id("TP") and tl["alpha3"] == "TLS"
    assert api.get("/v1/countries/by-alpha3/TLS").json()["data"]["country_id"] == country_id("TP")
    assert api.get("/v1/countries/by-alpha2/TP").status_code == 404  # histórico
    assert api.get("/v1/countries/by-alpha3/TMP").status_code == 404
    assert api.get("/v1/countries/by-numeric/626").json()["data"]["country_id"] == country_id("TP")
    by_id = api.get(f"/v1/countries/{country_id('TP')}").json()["data"]
    assert (by_id["alpha2"], by_id["status"]) == ("TL", "active")


def test_routes_do_not_overlap(api: TestClient) -> None:
    assert api.get("/v1/countries/by-alpha2/flag").json()["error"]["code"] == "invalid_code"
    assert api.get("/v1/countries/by-numeric/na").status_code == 422
    assert api.get("/v1/countries/by-alpha2").status_code == 404
    assert api.get(f"/v1/countries/{country_id('AR')}/flag").status_code == 200


# --- banderas (RF-19, RF-50) ----------------------------------------------------------------------


def test_the_flag_is_served_verified_with_its_checksum_as_etag(api: TestClient) -> None:
    response = api.get(f"/v1/countries/{country_id('AR')}/flag")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.content == flag_bytes("AR")
    assert response.headers["etag"] == f'"{flag_digest(flag_bytes("AR"))}"'
    tl = api.get(f"/v1/countries/{country_id('TP')}/flag")
    assert tl.status_code == 200 and tl.content == flag_bytes("TP")  # la bandera sigue al id


def test_a_declared_exception_is_not_the_same_as_an_unknown_country(api: TestClient) -> None:
    exception = api.get(f"/v1/countries/{country_id('AQ')}/flag")
    unknown = api.get(f"/v1/countries/{uuid.uuid4()}/flag")
    malformed = api.get("/v1/countries/not-a-uuid/flag")
    assert (exception.status_code, exception.json()["error"]["code"]) == (404, "flag_not_declared")
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "country_not_found")
    assert (malformed.status_code, malformed.json()["error"]["code"]) == (404, "country_not_found")


def test_a_tampered_or_missing_asset_is_an_integrity_error(reader_url: str, tmp_path: Path) -> None:
    for name in ("ar.svg", "tp.svg"):
        shutil.copy(FLAGS_DIR / name, tmp_path / name)
    (tmp_path / "ar.svg").write_bytes(flag_bytes("AR") + b"<!-- alterado -->")
    client = client_for(reader_url, tmp_path)
    tampered = client.get(f"/v1/countries/{country_id('AR')}/flag")
    missing = client.get(f"/v1/countries/{country_id('US')}/flag")
    healthy = client.get(f"/v1/countries/{country_id('TP')}/flag")
    assert (tampered.status_code, tampered.json()["error"]["code"]) == (500, "flag_integrity_error")
    assert (missing.status_code, missing.json()["error"]["code"]) == (500, "flag_integrity_error")
    assert healthy.status_code == 200


# --- solo lectura, determinismo, red, errores estables --------------------------------------------


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize(
    "path",
    [
        "/v1/countries",
        f"/v1/countries/{country_id('AR')}",
        "/v1/countries/by-alpha2/AR",
        f"/v1/countries/{country_id('AR')}/flag",
    ],
)
def test_the_api_is_read_only(api: TestClient, method: str, path: str) -> None:
    assert getattr(api, method)(path).status_code == 405


def test_repeated_queries_return_the_same(api: TestClient) -> None:
    paths = ["/v1/countries", "/v1/countries/by-alpha2/TL", f"/v1/countries/{country_id('AN')}"]
    first = [api.get(path, params={"locale_id": EN}).json() for path in paths]
    again = [api.get(path, params={"locale_id": EN}).json() for path in paths]
    assert first == again


def test_error_codes_are_stable_and_do_not_depend_on_the_client_language(api: TestClient) -> None:
    """D-19, RNF-9: el catálogo no localiza mensajes; eso es de la capa consumidora."""
    for path in (
        "/v1/countries/by-alpha2/A1",
        "/v1/countries/by-alpha2/ZZ",
        "/v1/countries?status=x",
    ):
        english = api.get(path, headers={"Accept-Language": "en"}).json()
        french = api.get(path, headers={"Accept-Language": "fr-FR"}).json()
        assert english == french
    assert api.get("/v1/countries/by-alpha2/ZZ").json()["error"]["code"] == "country_not_found"


def test_the_api_answers_without_network(reader_url: str, network_guard: NetworkGuard) -> None:
    with network_guard:
        client = client_for(reader_url)
        assert client.get("/v1/countries").status_code == 200
        assert client.get("/v1/countries/by-alpha2/AR").status_code == 200
        assert client.get(f"/v1/countries/{country_id('AR')}/flag").status_code == 200
    assert network_guard.blocked == []


def test_the_reader_role_cannot_write_through_the_api_connection(reader_url: str) -> None:
    with psycopg.connect(reader_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE reference.country SET status = 'inactive'")


def test_app_from_environment_serves_countries_with_the_packaged_assets(reader_url: str) -> None:
    client = TestClient(app_from_environment({READER_URL: reader_url}))
    assert client.get("/v1/countries/by-alpha2/AR").status_code == 200
    # El paquete instalado no trae los SVG de prueba: la bandera falla de forma explícita.
    assert client.get(f"/v1/countries/{country_id('AR')}/flag").status_code == 500


# --- catálogo vacío y no disponible ---------------------------------------------------------------


@pytest.fixture
def empty(database_factory: Callable[[], str]) -> TestClient:
    url = database_factory()
    incorporate_locales(locale_snapshot(1), postgres_repository(url))
    return client_for(url)


def test_an_empty_catalog_is_never_an_error(empty: TestClient) -> None:
    assert empty.get("/v1/countries").json() == {"snapshot_version": None, "data": []}
    assert empty.get("/v1/countries", params={"locale_id": EN, "status": "all"}).json() == {
        "snapshot_version": None,
        "data": [],
    }
    for path in (
        "/v1/countries/by-alpha2/AR",
        "/v1/countries/by-numeric/032",
        f"/v1/countries/{uuid.uuid4()}",
        f"/v1/countries/{uuid.uuid4()}/flag",
    ):
        response = empty.get(path)
        assert response.status_code == 404 and response.json()["snapshot_version"] is None


def test_an_unavailable_database_is_503_without_details() -> None:
    reader = FakeCountryReader()
    reader.unavailable = True
    client = TestClient(
        create_catalog_app(FakeReader(), FakeRegionReader(), reader, DirectoryFlagStore(FLAGS_DIR))
    )
    response = client.get("/v1/countries")
    assert response.status_code == 503
    assert response.json() == {
        "snapshot_version": None,
        "error": {"code": "unavailable", "message": "el catálogo no está disponible"},
    }


def test_each_query_uses_a_single_session() -> None:
    reader = FakeCountryReader(version=1, locale_ids=[EN])
    client = TestClient(
        create_catalog_app(FakeReader(), FakeRegionReader(), reader, DirectoryFlagStore(FLAGS_DIR))
    )
    client.get("/v1/countries", params={"locale_id": EN})
    client.get("/v1/countries/by-alpha2/AR", params={"locale_id": EN})
    client.get(f"/v1/countries/{country_id('AR')}/flag")
    assert reader.sessions == 3


# --- composición y contratos ---------------------------------------------------------------------


def test_locales_and_regions_keep_answering_in_the_same_application(api: TestClient) -> None:
    locales = api.get("/v1/locales")
    assert locales.status_code == 200
    assert {item["code"] for item in locales.json()["data"]} == {"en", "es", "fr"}
    assert api.get("/v1/regions").status_code == 200
    assert api.get("/v1/subregions/by-code/419").status_code == 200
    assert api.get("/v1/openapi.json").json() == json.loads(LOCALES_CONTRACT.read_text("utf-8"))
    assert api.get("/v1/openapi/regions.json").json() == json.loads(
        REGIONS_CONTRACT.read_text("utf-8")
    )


def test_the_locale_and_regions_contracts_did_not_change() -> None:
    assert openapi_document() == json.loads(LOCALES_CONTRACT.read_text(encoding="utf-8"))
    assert regions_openapi_document() == json.loads(REGIONS_CONTRACT.read_text(encoding="utf-8"))


def test_the_countries_openapi_matches_the_published_contract(api: TestClient) -> None:
    published = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert countries_openapi_document() == published
    assert api.get("/v1/openapi/countries.json").json() == published


def test_the_countries_contract_declares_only_get_operations_and_its_errors() -> None:
    document = countries_openapi_document()
    assert set(document["paths"]) == {
        "/v1/countries",
        "/v1/countries/{country_id}",
        "/v1/countries/{country_id}/flag",
        "/v1/countries/by-alpha2/{code}",
        "/v1/countries/by-alpha3/{code}",
        "/v1/countries/by-numeric/{code}",
    }
    for operations in document["paths"].values():
        assert set(operations) == {"get"}
        assert "200" in operations["get"]["responses"]
    schemas = document["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    assert set(schemas["Country"]["properties"]) == {
        "country_id",
        "alpha2",
        "alpha3",
        "numeric_code",
        "status",
        "replacement_country_id",
        "region_id",
        "subregion_id",
        "calling_code",
        "name",
        "official_name",
    }
    text = json.dumps(document)
    for forbidden in ("tenant_id", "region_code", "region_name", "is_active", "country_code"):
        assert forbidden not in text
    flag_ok = document["paths"]["/v1/countries/{country_id}/flag"]["get"]["responses"]["200"]
    assert "image/svg+xml" in flag_ok["content"]


@pytest.mark.parametrize(
    ("path", "countries", "regions"),
    [
        ("/v1/countries", True, False),
        ("/v1/countries/by-alpha2/AR", True, False),
        ("/v1/countries/x/flag", True, False),
        ("/v1/openapi/countries.json", True, False),
        ("/v1/countriesx", False, False),
        ("/v1/regions", False, True),
        ("/v1/subregions/x", False, True),
        ("/v1/openapi/regions.json", False, True),
        ("/v1/locales", False, False),
        ("/v1/openapi.json", False, False),
        ("/", False, False),
    ],
)
def test_requests_are_routed_by_path(path: str, countries: bool, regions: bool) -> None:
    assert belongs_to_countries(path) is countries
    assert belongs_to_regions(path) is regions
