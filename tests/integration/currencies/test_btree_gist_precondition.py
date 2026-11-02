"""004: `btree_gist` es una precondición de despliegue y la migración falla si falta (D10, RF-45).

Sin la extensión no existiría la exclusión temporal persistente por par país–moneda. La migración
no tiene alternativa silenciosa: si la extensión no puede habilitarse, `alembic upgrade` aborta con
el error de la base y ésta queda en `0003`, sin ninguna tabla de 004.

La imposibilidad se simula con un event trigger que rechaza `CREATE EXTENSION`, como haría una
política de un hosting que restringe extensiones (el error exacto depende del entorno: privilegio,
extensión no instalada o política; el comportamiento de la migración es el mismo).
"""

import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from psycopg import sql
from sqlalchemy.exc import DBAPIError

from tests.conftest import alembic_config, with_database

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (ROOT / "migrations" / "versions" / "0004_currencies.py").read_text("utf-8")

BLOCK_EXTENSIONS = """
CREATE FUNCTION public.deny_extensions() RETURNS event_trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'extension creation is restricted in this environment';
END $$;
CREATE EVENT TRIGGER deny_extensions ON ddl_command_start
  WHEN TAG IN ('CREATE EXTENSION') EXECUTE FUNCTION public.deny_extensions();
"""


@pytest.fixture
def at_0003(postgres_with_roles: str) -> Iterator[str]:
    """Base en `0003` y sin la extensión `btree_gist`."""
    name = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = with_database(postgres_with_roles, name)
    command.upgrade(alembic_config(url), "0003")
    with psycopg.connect(url, autocommit=True) as admin:
        found = admin.execute(
            "SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'"
        ).fetchone()
    assert found == (0,)
    try:
        yield url
    finally:
        with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def state(url: str) -> tuple[str, int, int]:
    with psycopg.connect(url, autocommit=True) as conn:
        version = conn.execute("SELECT version_num FROM reference.alembic_version").fetchone()
        tables = conn.execute(
            "SELECT count(*) FROM pg_class WHERE relnamespace = 'reference'::regnamespace "
            "AND relname IN ('currency', 'country_currency', 'currency_snapshot', "
            "'currency_locale')"
        ).fetchone()
        extension = conn.execute(
            "SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'"
        ).fetchone()
    assert version is not None and tables is not None and extension is not None
    return str(version[0]), int(tables[0]), int(extension[0])


def test_the_migration_fails_clearly_and_leaves_0003_when_the_extension_cannot_be_enabled(
    at_0003: str,
) -> None:
    with psycopg.connect(at_0003, autocommit=True) as admin:
        admin.execute(BLOCK_EXTENSIONS)
    with pytest.raises(DBAPIError) as failure:
        command.upgrade(alembic_config(at_0003), "0004")
    assert "extension creation is restricted" in str(failure.value)
    # DDL transaccional: ni la versión, ni la extensión, ni las tablas de 004 cambian.
    assert state(at_0003) == ("0003", 0, 0)


def test_with_the_extension_enabled_the_migration_deploys_and_the_exclusion_guards_overlaps(
    at_0003: str,
) -> None:
    """Precondición del runbook: con la extensión habilitada, la garantía persistente existe."""
    command.upgrade(alembic_config(at_0003), "0004")
    assert state(at_0003) == ("0004", 4, 1)
    with psycopg.connect(at_0003, autocommit=True) as conn:
        definition = conn.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'country_currency_active_no_overlap'"
        ).fetchone()
    assert definition is not None and "EXCLUDE USING gist" in definition[0]


def test_the_migration_has_no_silent_fallback_around_the_extension() -> None:
    assert re.search(r"^CREATE EXTENSION IF NOT EXISTS btree_gist;$", MIGRATION, re.MULTILINE)
    # La extensión no se crea dentro de un bloque con captura de excepciones.
    assert not re.search(r"EXCEPTION\s+WHEN", MIGRATION, re.IGNORECASE)
    assert not re.search(r"(?is)DO\s+\$\$(?:(?!\$\$).)*btree_gist", MIGRATION)
    # La exclusión que depende de la extensión sigue declarada en la tabla.
    assert "country_currency_active_no_overlap" in MIGRATION
    assert "EXCLUDE USING gist" in MIGRATION


def test_the_deployment_precondition_is_documented() -> None:
    runbook = (ROOT / "docs" / "operacion.md").read_text("utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist;" in runbook
    assert "Sin ella no existe la garantía persistente" in runbook
