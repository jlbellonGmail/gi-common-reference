"""L-3: la causa de los errores 500/503 queda en el log; al cliente, un mensaje genérico."""

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gi_common_reference.app import app_from_environment, create_app
from gi_common_reference.bootstrap import postgres_reader
from gi_common_reference.locales.domain.errors import InvalidConnectionString
from tests.fixtures.fakes import FakeReader

LOGGER = "gi_common_reference.locales.interfaces.http"
SECRET = "SECRETPW"
UNREACHABLE = f"postgresql://user:{SECRET}@127.0.0.1:1/db?connect_timeout=1"


@pytest.fixture(autouse=True)
def capture(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)


def errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER and r.levelno == logging.ERROR]


def test_unavailable_catalog_logs_the_cause_and_answers_a_generic_503(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(version=1)
    reader.unavailable = True
    response = TestClient(create_app(reader)).get("/v1/locales/by-code/es")

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "unavailable",
        "message": "el catálogo no está disponible",
    }
    (record,) = errors(caplog)
    assert "la base no responde" in record.getMessage()  # la causa, en el log
    assert "/v1/locales/by-code/es" in record.getMessage() and "GET" in record.getMessage()
    assert "la base no responde" not in response.text  # no en la respuesta


def test_unexpected_error_logs_the_traceback_and_answers_a_generic_500(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("detalle interno inesperado")

    monkeypatch.setattr(FakeReader, "session", boom)
    client = TestClient(create_app(FakeReader(version=1)), raise_server_exceptions=False)
    response = client.get("/v1/locales")

    assert response.status_code == 500
    assert response.json()["error"] == {"code": "internal_error", "message": "error interno"}
    (record,) = errors(caplog)
    assert record.exc_info is not None and record.exc_info[0] is ValueError
    assert "detalle interno inesperado" in str(record.exc_info[1])
    assert "detalle interno inesperado" not in response.text
    assert "Traceback" not in response.text


def test_the_query_string_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    reader = FakeReader(version=1)
    reader.unavailable = True
    TestClient(create_app(reader)).get("/v1/locales", params={"status": "VALOR_SENSIBLE"})
    assert "VALOR_SENSIBLE" not in caplog.text


def test_an_unreachable_database_is_a_503_and_neither_log_nor_response_expose_the_connection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(create_app(postgres_reader(UNREACHABLE)))
    response = client.get("/v1/locales")

    assert response.status_code == 503
    (record,) = errors(caplog)
    assert "Error" in record.getMessage() or "Timeout" in record.getMessage()
    for text in (record.getMessage(), response.text, caplog.text):
        assert SECRET not in text and "127.0.0.1" not in text


def test_a_malformed_connection_string_stops_the_app_from_starting_without_echoing_it() -> None:
    with pytest.raises(InvalidConnectionString) as raised:
        app_from_environment({"REFERENCE_READER_DATABASE_URL": SECRET})
    assert SECRET not in str(raised.value)


def test_handled_responses_do_not_log_errors(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(create_app(FakeReader(version=1)))
    assert client.get("/v1/locales").status_code == 200
    assert client.get("/v1/locales/by-code/zz").status_code == 404
    assert client.get("/v1/locales/by-code/es-AR").status_code == 422
    assert errors(caplog) == []


@pytest.mark.parametrize(
    "conninfo",
    [
        f"host=127.0.0.1 port=1 password={SECRET} connect_timeout={SECRET}",
        f"postgresql://u:{SECRET}@127.0.0.1:1/db?sslmode={SECRET}",
        f"postgresql://u:pa@{SECRET}@127.0.0.1:1/db?connect_timeout=1",
    ],
    ids=["programming-error", "bad-sslmode", "at-sign-in-password"],
)
def test_hostile_connection_strings_are_a_503_and_never_reach_the_client_or_the_log(
    caplog: pytest.LogCaptureFixture, conninfo: str
) -> None:
    """T11 (L-A): antes, un `ProgrammingError` al conectar era un 500 con el valor en el log."""
    client = TestClient(create_app(postgres_reader(conninfo)), raise_server_exceptions=False)
    response = client.get("/v1/locales")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "unavailable"
    (record,) = errors(caplog)
    assert record.exc_info is None  # el 503 registra la descripción segura, no un traceback
    for text in (response.text, caplog.text):
        assert SECRET not in text and "127.0.0.1" not in text
