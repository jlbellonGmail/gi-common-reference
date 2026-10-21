"""T8: contrato de la API pública `/v1/locales` con httpx, sobre datos incorporados por T7
(RF-7–RF-13, RNF-1, RNF-2, RNF-4)."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from gi_common_reference.app import app_from_environment, create_app, openapi_document
from gi_common_reference.bootstrap import postgres_reader, postgres_repository
from gi_common_reference.locales.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.locales.domain.model import LocaleRecord
from tests.conftest import NetworkGuard
from tests.fixtures.fakes import FakeReader
from tests.fixtures.snapshots import (
    build_snapshot,
    iana_text,
    iw_scenario,
    language_entry,
    locale,
    locale_id,
)

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "locales-api.v1.openapi.json"
LOCALES = "/v1/locales"
BY_CODE = "/v1/locales/by-code/"
ENDPOINTS = [LOCALES, f"{LOCALES}/{locale_id('es')}", f"{BY_CODE}es"]


def incorporate(url: str, *documents: dict[str, Any]) -> None:
    for document in documents:
        result = incorporate_snapshot(document, postgres_repository(url))
        assert result.outcome is Outcome.INCORPORATED


@pytest.fixture
def reader_url(database_url: str, postgres_with_roles: str) -> str:
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute("ALTER ROLE reference_reader WITH LOGIN PASSWORD 'reader'")
    return make_conninfo(database_url, user="reference_reader", password="reader")


@pytest.fixture
def client_for(reader_url: str) -> Callable[[], TestClient]:
    return lambda: TestClient(create_app(postgres_reader(reader_url)))


@pytest.fixture
def api(database_url: str, client_for: Callable[[], TestClient]) -> TestClient:
    """Catálogo con `iw` publicado (v1) y luego deprecado hacia `he` (v2)."""
    v1, v2 = iw_scenario()
    incorporate(database_url, v1, v2)
    return client_for()


@pytest.fixture
def api_iw_unpublished(database_url: str, client_for: Callable[[], TestClient]) -> TestClient:
    """`iw` está en el registro IANA pero nunca se publicó como locale."""
    registry = iana_text(
        "2026-10-01",
        language_entry("es"),
        language_entry("he"),
        language_entry("iw", "1989-01-01", "he"),
    )
    snapshot = build_snapshot(
        1, registry=registry, file_date="2026-10-01", locales=[locale("es"), locale("he")]
    )
    incorporate(database_url, snapshot)
    return client_for()


@pytest.fixture
def api_empty(client_for: Callable[[], TestClient]) -> TestClient:
    return client_for()


def codes(response: Any) -> list[str]:
    return [item["code"] for item in response.json()["data"]]


# --- por id (RF-7) -----------------------------------------------------------------------------


def test_by_id_returns_200_with_the_locale_and_snapshot_version(api: TestClient) -> None:
    response = api.get(f"{LOCALES}/{locale_id('iw')}")
    assert response.status_code == 200
    assert response.json() == {
        "snapshot_version": 2,
        "data": {
            "locale_id": locale_id("iw"),
            "code": "iw",
            "status": "inactive",
            "iana_deprecated": True,
            "replacement_locale_id": locale_id("he"),
        },
    }


def test_by_id_of_an_active_locale_has_no_replacement(api: TestClient) -> None:
    data = api.get(f"{LOCALES}/{locale_id('es')}").json()["data"]
    assert data["status"] == "active" and data["iana_deprecated"] is False
    assert data["replacement_locale_id"] is None


def test_by_id_not_found_is_404_with_snapshot_version(api: TestClient) -> None:
    response = api.get(f"{LOCALES}/{locale_id('zz')}")
    assert response.status_code == 404
    body = response.json()
    assert body["snapshot_version"] == 2 and body["error"]["code"] == "not_found"
    assert "data" not in body


@pytest.mark.parametrize("raw", ["abc", "es", "by-code", "00000000-0000-0000-0000-00000000000g"])
def test_by_id_with_a_malformed_id_is_404_never_500(api: TestClient, raw: str) -> None:
    response = api.get(f"{LOCALES}/{raw}")
    assert response.status_code == 404 and response.json()["snapshot_version"] == 2


# --- por código (RF-8, RF-9, RF-10) ------------------------------------------------------------


@pytest.mark.parametrize("raw", ["es", "ES", "Es"])
def test_by_code_is_case_tolerant(api: TestClient, raw: str) -> None:
    response = api.get(BY_CODE + raw)
    assert response.status_code == 200
    assert response.json()["data"]["code"] == "es"
    assert response.json()["data"]["locale_id"] == locale_id("es")


def test_by_code_resolves_an_unpublished_deprecated_code_to_its_preferred_value(
    api_iw_unpublished: TestClient,
) -> None:
    response = api_iw_unpublished.get(BY_CODE + "iw")
    assert response.status_code == 200
    assert response.json()["data"]["code"] == "he"
    assert response.json()["data"]["locale_id"] == locale_id("he")
    assert api_iw_unpublished.get(BY_CODE + "IW").json()["data"]["code"] == "he"


def test_by_code_returns_the_published_deprecated_locale_not_its_replacement(
    api: TestClient,
) -> None:
    data = api.get(BY_CODE + "iw").json()["data"]
    assert data["code"] == "iw" and data["status"] == "inactive"
    assert data["replacement_locale_id"] == locale_id("he")


@pytest.mark.parametrize(
    "raw",
    ["es-AR", "es_AR", "es-419", "pt-BR", "zh-Hant", "x-klingon", "i-klingon", "en-u-ca-gregory"]
    + [quote(" es "), quote(" es"), "e", "espa", "e1"],
)
def test_by_code_not_well_formed_is_422_with_snapshot_version(api: TestClient, raw: str) -> None:
    response = api.get(BY_CODE + raw)
    assert response.status_code == 422
    body = response.json()
    assert body["snapshot_version"] == 2 and body["error"]["code"] == "invalid_code"


@pytest.mark.parametrize("raw", ["spa", "eng", "ger", "zz"])
def test_by_code_well_formed_but_unknown_is_404_without_fallback(api: TestClient, raw: str) -> None:
    response = api.get(BY_CODE + raw)
    assert response.status_code == 404
    assert response.json()["snapshot_version"] == 2 and "data" not in response.json()


def test_invalid_and_not_found_are_distinguishable(api: TestClient) -> None:
    assert api.get(BY_CODE + "es-AR").status_code != api.get(BY_CODE + "zz").status_code


def test_unpublished_code_without_its_preferred_locale_is_404(
    database_url: str, client_for: Callable[[], TestClient]
) -> None:
    registry = iana_text(
        "2026-10-01", language_entry("es"), language_entry("iw", "1989-01-01", "he")
    )
    snapshot = build_snapshot(1, registry=registry, file_date="2026-10-01", locales=[locale("es")])
    # `iw` figura en el registro (alias → `he`) pero ni `iw` ni `he` están publicados.
    incorporate(database_url, snapshot)
    assert client_for().get(BY_CODE + "iw").status_code == 404


# --- listado (RF-11) ---------------------------------------------------------------------------


def test_list_returns_all_locales_ordered_by_code(api: TestClient) -> None:
    response = api.get(LOCALES)
    assert response.status_code == 200
    assert response.json()["snapshot_version"] == 2
    assert codes(response) == ["en", "es", "he", "iw"]
    statuses = {item["code"]: item["status"] for item in response.json()["data"]}
    assert statuses == {"en": "active", "es": "active", "he": "active", "iw": "inactive"}


def test_list_can_be_restricted_to_active(api: TestClient) -> None:
    response = api.get(LOCALES, params={"status": "active"})
    assert response.status_code == 200 and codes(response) == ["en", "es", "he"]


def test_list_can_be_restricted_to_inactive(api: TestClient) -> None:
    assert codes(api.get(LOCALES, params={"status": "inactive"})) == ["iw"]


@pytest.mark.parametrize("status", ["", "ACTIVE", "deprecated", "all"])
def test_list_with_an_unknown_status_is_422_with_snapshot_version(
    api: TestClient, status: str
) -> None:
    response = api.get(LOCALES, params={"status": status})
    assert response.status_code == 422
    assert response.json()["snapshot_version"] == 2
    assert response.json()["error"]["code"] == "invalid_status"


# --- solo lectura (RF-12) ----------------------------------------------------------------------


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize("path", ENDPOINTS)
def test_other_methods_are_405(api: TestClient, method: str, path: str) -> None:
    response = getattr(api, method)(path)
    assert response.status_code == 405
    assert "GET" in response.headers["allow"]


def test_the_api_exposes_only_get_operations(api: TestClient) -> None:
    spec = api.get("/v1/openapi.json").json()
    methods = {m for path in spec["paths"].values() for m in path}
    assert methods == {"get"}
    assert set(spec["paths"]) == {
        LOCALES,
        f"{LOCALES}/{{locale_id}}",
        f"{LOCALES}/by-code/{{code}}",
    }


def test_api_does_not_change_the_catalog(api: TestClient, database_url: str) -> None:
    def state() -> list[Any]:
        with psycopg.connect(database_url) as conn:
            return conn.execute(
                "SELECT locale_id::text, status FROM reference.locale ORDER BY code"
            ).fetchall()

    before = state()
    for method, path in [("post", LOCALES), ("delete", f"{LOCALES}/{locale_id('es')}")]:
        getattr(api, method)(path)
    assert state() == before


# --- snapshot_version y catálogo vacío (RF-13) -------------------------------------------------


def test_snapshot_version_is_present_in_every_response_of_the_three_endpoints(
    api: TestClient,
) -> None:
    requests = [
        f"{LOCALES}/{locale_id('es')}",  # 200
        f"{LOCALES}/{locale_id('zz')}",  # 404
        f"{LOCALES}/basura",  # 404
        BY_CODE + "es",  # 200
        BY_CODE + "zz",  # 404
        BY_CODE + "es-AR",  # 422
        LOCALES,  # 200
        LOCALES + "?status=inactive",  # 200
        LOCALES + "?status=nope",  # 422
    ]
    for path in requests:
        response = api.get(path)
        assert response.json()["snapshot_version"] == 2, path


def test_empty_catalog_answers_with_null_snapshot_version_and_never_500(
    api_empty: TestClient,
) -> None:
    listing = api_empty.get(LOCALES)
    assert listing.status_code == 200
    assert listing.json() == {"snapshot_version": None, "data": []}
    for path in (f"{LOCALES}/{locale_id('es')}", BY_CODE + "es", BY_CODE + "zz"):
        response = api_empty.get(path)
        assert response.status_code == 404, path
        assert response.json()["snapshot_version"] is None
    assert api_empty.get(BY_CODE + "es-AR").status_code == 422
    assert api_empty.get(LOCALES + "?status=active").json() == {
        "snapshot_version": None,
        "data": [],
    }


def test_snapshot_version_follows_the_current_snapshot(
    database_url: str, client_for: Callable[[], TestClient]
) -> None:
    v1, v2 = iw_scenario()
    client = client_for()
    incorporate(database_url, v1)
    assert client.get(LOCALES).json()["snapshot_version"] == 1
    incorporate(database_url, v2)
    assert client.get(LOCALES).json()["snapshot_version"] == 2


def test_a_session_sees_one_consistent_state_while_a_snapshot_is_incorporated(
    database_url: str, reader_url: str
) -> None:
    """`snapshot_version` y datos de una misma consulta salen del mismo estado del catálogo."""
    v1, v2 = iw_scenario()
    incorporate(database_url, v1)
    reader = postgres_reader(reader_url)
    with reader.session() as session:
        assert session.snapshot_version() == 1
        incorporate(database_url, v2)  # otra conexión confirma el snapshot 2 en medio
        assert session.snapshot_version() == 1
        assert [r.code for r in session.all_locales(None)] == ["en", "es", "iw"]
        assert session.by_code("he") is None
    with reader.session() as session:
        assert session.snapshot_version() == 2
        assert [r.code for r in session.all_locales(None)] == ["en", "es", "he", "iw"]


# --- determinismo (RNF-1) ----------------------------------------------------------------------


def test_repeated_queries_return_the_same_answers(api: TestClient) -> None:
    paths = [LOCALES, LOCALES + "?status=active", BY_CODE + "iw", BY_CODE + "ES", BY_CODE + "zz"]
    first = [(api.get(p).status_code, api.get(p).json()) for p in paths]
    second = [(api.get(p).status_code, api.get(p).json()) for p in paths]
    assert first == second


def test_two_equal_databases_return_the_same_answers(
    database_factory: Callable[[], str], postgres_with_roles: str
) -> None:
    v1, v2 = iw_scenario()
    clients = []
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute("ALTER ROLE reference_reader WITH LOGIN PASSWORD 'reader'")
    for _ in range(2):
        url = database_factory()
        incorporate(url, v1, v2)
        reader = postgres_reader(make_conninfo(url, user="reference_reader", password="reader"))
        clients.append(TestClient(create_app(reader)))
    paths = [LOCALES, LOCALES + "?status=active", f"{LOCALES}/{locale_id('iw')}", BY_CODE + "iw"]
    paths += [BY_CODE + "ES", BY_CODE + "zz", BY_CODE + "es-AR", LOCALES + "?status=x"]
    one, two = ([(c.get(p).status_code, c.get(p).json()) for p in paths] for c in clients)
    assert one == two


# --- sin red y con el rol de solo lectura (RNF-2, RNF-4) ---------------------------------------


def test_api_answers_with_the_network_guard_active(
    api: TestClient, network_guard: NetworkGuard
) -> None:
    with network_guard:
        statuses = [api.get(p).status_code for p in (LOCALES, BY_CODE + "iw", BY_CODE + "zz")]
    assert statuses == [200, 200, 404]
    assert network_guard.blocked == []


def test_api_connects_with_the_reference_reader_role(
    database_url: str, reader_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    v1, _ = iw_scenario()
    incorporate(database_url, v1)
    seen: list[dict[str, Any]] = []
    real_connect = psycopg.connect

    def spy(conninfo: str = "", **kwargs: Any) -> Any:
        seen.append(conninfo_to_dict(conninfo, **kwargs))
        return real_connect(conninfo, **kwargs)

    monkeypatch.setattr(psycopg, "connect", spy)
    environ = {"REFERENCE_READER_DATABASE_URL": reader_url, "REFERENCE_DATABASE_URL": "ignorada"}
    client = TestClient(app_from_environment(environ))
    assert client.get(LOCALES).status_code == 200
    assert seen and {item["user"] for item in seen} == {"reference_reader"}


def test_app_from_environment_refuses_to_start_without_the_reader_url() -> None:
    with pytest.raises(RuntimeError, match="REFERENCE_READER_DATABASE_URL"):
        app_from_environment({"REFERENCE_DATABASE_URL": "postgresql://loader@db/x"})


def test_api_is_served_with_read_only_privileges_only(api: TestClient, reader_url: str) -> None:
    """El rol de la API puede leer pero no escribir: lo que sirve no puede alterar el catálogo."""
    with psycopg.connect(reader_url, autocommit=True) as conn:
        assert conn.execute("SELECT current_user").fetchone() == ("reference_reader",)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM reference.locale_alias")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE reference.locale SET status = 'inactive'")


# --- fallos de infraestructura -----------------------------------------------------------------


def test_unavailable_database_is_503_not_500() -> None:
    reader = FakeReader(version=1)
    reader.unavailable = True
    client = TestClient(create_app(reader))
    for path in ENDPOINTS:
        response = client.get(path)
        assert response.status_code == 503, path
        assert response.json()["error"]["code"] == "unavailable"
        assert response.json()["snapshot_version"] is None


def test_unexpected_errors_are_a_json_500(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = FakeReader(version=1)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("inesperado")

    monkeypatch.setattr(FakeReader, "session", boom)
    client = TestClient(create_app(reader), raise_server_exceptions=False)
    response = client.get(LOCALES)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"


def test_by_code_does_not_fold_non_ascii_lookalikes_into_a_published_code() -> None:
    """`K` (signo Kelvin) se pliega a `k` con `str.lower()`: no es una letra ASCII (RF-8)."""
    record = LocaleRecord(locale_id("ko"), "ko", "active", False, None)
    client = TestClient(create_app(FakeReader(version=1, locales=[record])))
    assert client.get(BY_CODE + "ko").status_code == 200
    response = client.get(BY_CODE + quote("Ko"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_code"


def test_trailing_slash_is_not_redirected(api: TestClient) -> None:
    assert api.get(LOCALES + "/", follow_redirects=False).status_code in (404, 405)


# --- contrato OpenAPI --------------------------------------------------------------------------


def test_openapi_document_matches_the_published_contract() -> None:
    published = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert openapi_document() == published


def test_openapi_describes_the_error_envelope_and_the_status_filter() -> None:
    spec = openapi_document()
    by_code = spec["paths"]["/v1/locales/by-code/{code}"]["get"]
    assert {"200", "404", "422"} <= set(by_code["responses"])
    listing = spec["paths"]["/v1/locales"]["get"]
    assert {"200", "422"} <= set(listing["responses"])
    schemas = spec["components"]["schemas"]
    assert {"Locale", "LocaleEnvelope", "LocaleListEnvelope", "ErrorEnvelope"} <= set(schemas)
    assert set(schemas["Locale"]["properties"]) == {
        "locale_id",
        "code",
        "status",
        "iana_deprecated",
        "replacement_locale_id",
    }


def test_openapi_declares_only_the_responses_each_endpoint_really_returns() -> None:
    paths = openapi_document()["paths"]
    assert set(paths["/v1/locales/{locale_id}"]["get"]["responses"]) == {"200", "404"}
    assert set(paths["/v1/locales/by-code/{code}"]["get"]["responses"]) == {"200", "404", "422"}
    assert set(paths["/v1/locales"]["get"]["responses"]) == {"200", "422"}


def test_openapi_has_no_framework_default_validation_schemas() -> None:
    schemas = openapi_document()["components"]["schemas"]
    assert "HTTPValidationError" not in schemas and "ValidationError" not in schemas
    assert set(schemas) == {
        "ErrorBody",
        "ErrorEnvelope",
        "Locale",
        "LocaleEnvelope",
        "LocaleListEnvelope",
    }


def test_openapi_status_filter_is_a_plain_string_enum() -> None:
    parameter = openapi_document()["paths"]["/v1/locales"]["get"]["parameters"][0]
    assert parameter["name"] == "status" and parameter["required"] is False
    assert parameter["schema"] == {"type": "string", "enum": ["active", "inactive"]}


def test_every_error_response_uses_the_error_envelope() -> None:
    for path in openapi_document()["paths"].values():
        for code, response in path["get"]["responses"].items():
            if code != "200":
                ref = response["content"]["application/json"]["schema"]["$ref"]
                assert ref == "#/components/schemas/ErrorEnvelope"


def test_locale_schema_has_no_tenant_or_translatable_text() -> None:
    """RF-1, RF-6, CA-18 en el contrato público."""
    properties = set(openapi_document()["components"]["schemas"]["Locale"]["properties"])
    forbidden = {"tenant_id", "name", "display_name", "localized_name", "description", "label"}
    assert not properties & forbidden
