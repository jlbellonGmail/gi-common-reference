"""L-4: Alembic toma su conexión de `REFERENCE_MIGRATION_DATABASE_URL`, no de la de la CLI."""

import traceback
import uuid
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from tests.conftest import with_database

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_URL = "REFERENCE_MIGRATION_DATABASE_URL"
LOADER_URL = "REFERENCE_DATABASE_URL"
READER_URL = "REFERENCE_READER_DATABASE_URL"


def config_without_url() -> Config:
    """Como se ejecuta `alembic upgrade head` en el despliegue: sin `sqlalchemy.url`."""
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    assert config.get_main_option("sqlalchemy.url") is None
    return config


@pytest.fixture
def empty_database(postgres_with_roles: str) -> str:
    name = f"env_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return with_database(postgres_with_roles, name)


def table_exists(url: str) -> bool:
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT to_regclass('reference.locale')").fetchone() != (None,)


def test_the_migration_variable_is_enough_and_a_plain_postgresql_url_works(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert empty_database.startswith("postgresql://")  # sin `+psycopg`
    monkeypatch.setenv(MIGRATION_URL, empty_database)
    monkeypatch.delenv(LOADER_URL, raising=False)
    monkeypatch.delenv(READER_URL, raising=False)

    command.upgrade(config_without_url(), "head")

    assert table_exists(empty_database)


def test_the_cli_variable_is_not_used_for_migrations(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(MIGRATION_URL, raising=False)
    monkeypatch.setenv(LOADER_URL, empty_database)
    monkeypatch.setenv(READER_URL, empty_database)

    with pytest.raises(RuntimeError, match=MIGRATION_URL):
        command.upgrade(config_without_url(), "head")

    with psycopg.connect(empty_database) as conn:
        assert conn.execute("SELECT to_regclass('reference.locale')").fetchone() == (None,)


def test_an_explicit_sqlalchemy_url_still_takes_precedence(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MIGRATION_URL, "postgresql://usuario@no-existe.invalid/x")
    config = config_without_url()
    config.set_main_option("sqlalchemy.url", empty_database)

    command.upgrade(config, "head")

    assert table_exists(empty_database)


def test_the_documented_variables_are_the_ones_the_code_reads() -> None:
    """Los nombres que usa el runbook coinciden con los que leen la CLI, la API y Alembic."""
    from gi_common_reference.app import READER_DATABASE_URL
    from gi_common_reference.locales.interfaces.cli import DATABASE_URL

    runbook = (ROOT / "docs" / "operacion.md").read_text(encoding="utf-8")
    assert {READER_DATABASE_URL, DATABASE_URL, MIGRATION_URL} == {
        READER_URL,
        LOADER_URL,
        MIGRATION_URL,
    }
    for name in (READER_URL, LOADER_URL, MIGRATION_URL):
        assert name in runbook
    assert MIGRATION_URL in (ROOT / "migrations" / "env.py").read_text(encoding="utf-8")


# --- T12 (hallazgo L-B): los errores de conexión de las migraciones no citan la conexión --------

SECRET = "SECRETPW"
HOSTILE_MIGRATION_URLS = [
    pytest.param(SECRET, id="not-a-url"),
    pytest.param(f"host=h password={SECRET} =x", id="libpq-style-malformed"),
    pytest.param(f"postgresql://u:{SECRET}@[::1/db", id="broken-ipv6"),
    pytest.param(f"postgresql://u:{SECRET}@127.0.0.1:1/db?connect_timeout=1", id="refused"),
    pytest.param(f"postgresql://u:pa@{SECRET}@127.0.0.1:1/db?connect_timeout=1", id="at-sign"),
    pytest.param(f"postgresql://u:{SECRET}@127.0.0.1:1/db?sslmode={SECRET}", id="bad-sslmode"),
]


@pytest.mark.parametrize("url", HOSTILE_MIGRATION_URLS)
def test_connection_errors_of_the_migrations_do_not_quote_the_connection(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MIGRATION_URL, url)

    with pytest.raises(RuntimeError) as raised:
        command.upgrade(config_without_url(), "head")

    printed = str(raised.value) + "".join(traceback.format_exception(raised.value))
    assert SECRET not in printed and "127.0.0.1" not in printed
    assert "no se pudo conectar para migrar" in str(raised.value)
    assert MIGRATION_URL in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__


def test_a_wrong_password_is_reported_by_error_type_without_the_password(
    postgres_with_roles: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fallo de autenticación ocurre al conectar: el driver no informa un SQLSTATE."""
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute("CREATE ROLE migrator_pw LOGIN PASSWORD 'right-pw'")
    wrong = postgres_with_roles.replace("test:test@", f"migrator_pw:{SECRET}@")
    assert SECRET in wrong
    monkeypatch.setenv(MIGRATION_URL, wrong)

    with pytest.raises(RuntimeError) as raised:
        command.upgrade(config_without_url(), "head")

    assert str(raised.value).endswith(": OperationalError")
    assert SECRET not in str(raised.value) and "migrator_pw" not in str(raised.value)


def test_a_failing_migration_is_not_reported_as_a_connection_error(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Solo se sanea el tramo de conexión: un error de la propia migración se informa completo."""
    with psycopg.connect(empty_database, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA reference")
        conn.execute("CREATE TABLE reference.locale (x int)")  # choca con la migración 0001
    monkeypatch.setenv(MIGRATION_URL, empty_database)

    with pytest.raises(Exception) as raised:
        command.upgrade(config_without_url(), "head")

    assert "no se pudo conectar" not in str(raised.value)
    assert "already exists" in str(raised.value)
