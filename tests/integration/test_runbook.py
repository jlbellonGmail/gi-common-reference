"""L-5: el SQL y los comandos del runbook (`docs/operacion.md`) se ejecutan de verdad.

Postgres limpio, sin los roles: se sigue el runbook tal como está escrito, en los dos órdenes que
admite (roles después de migrar, roles antes de migrar), y se comprueba que ambos dejan los mismos
privilegios.
"""

import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from psycopg import errors, sql
from psycopg.conninfo import make_conninfo
from testcontainers.community.postgres import PostgresContainer
from uvicorn.importer import import_from_string

from tests.conftest import alembic_config, with_database

ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = (ROOT / "docs" / "operacion.md").read_text(encoding="utf-8")
BLOCK = re.compile(r"```sql\n-- runbook:(\w+)\n(.*?)```", re.DOTALL)
PASSWORDS = {"CAMBIAR_READER": "reader-pw", "CAMBIAR_LOADER": "loader-pw"}
EXPECTED_VERIFY = (True, False, True, False, False)  # lo que documenta el runbook


def runbook_sql(name: str) -> str:
    blocks = dict(BLOCK.findall(RUNBOOK))
    script: str = blocks[name]
    for placeholder, password in PASSWORDS.items():
        script = script.replace(placeholder, password)
    return script


@pytest.fixture
def clean_postgres() -> Iterator[str]:
    """Un Postgres sin los roles `reference_*`: el estado de partida del runbook.

    Los roles son globales al cluster, así que cada prueba tiene el suyo: ninguna depende de lo que
    otra haya creado ni del orden en que corran."""
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        yield pg.get_connection_url()


def new_database(admin_url: str) -> str:
    name = f"rb_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return with_database(admin_url, name)


def run(url: str, script: str) -> tuple[object, ...] | None:
    with psycopg.connect(url, autocommit=True) as conn:
        cursor = conn.execute(script)
        return cursor.fetchone() if cursor.description else None


def privileges(url: str) -> set[tuple[str, ...]]:
    """Todo lo que el lector y el cargador pueden hacer, por tabla y por columna."""
    with psycopg.connect(url, autocommit=True) as conn:
        tables = conn.execute(
            "SELECT grantee, table_name, privilege_type FROM information_schema.table_privileges "
            "WHERE table_schema = 'reference' AND grantee LIKE 'reference\\_%'"
        ).fetchall()
        columns = conn.execute(
            "SELECT grantee, table_name || '.' || column_name, privilege_type "
            "FROM information_schema.column_privileges "
            "WHERE table_schema = 'reference' AND grantee LIKE 'reference\\_%'"
        ).fetchall()
        schema = conn.execute(
            "SELECT r.rolname, 'USAGE', "
            "has_schema_privilege(r.rolname, 'reference', 'USAGE')::text "
            "FROM pg_roles r WHERE r.rolname LIKE 'reference\\_%'"
        ).fetchall()
    return {tuple(row) for row in [*tables, *columns, *schema]}


def test_the_runbook_has_the_blocks_the_tests_execute() -> None:
    assert {"roles", "grants", "verify"} <= {name for name, _ in BLOCK.findall(RUNBOOK)}


def test_following_the_runbook_in_either_order_leaves_the_same_privileges(
    clean_postgres: str,
) -> None:
    # Orden B: se migra primero y los roles se crean después -> hay que aplicar el bloque `grants`.
    late = new_database(clean_postgres)
    command.upgrade(alembic_config(late), "head")
    run(clean_postgres, runbook_sql("roles"))
    assert run(late, runbook_sql("verify")) == (False, False, False, False, False)  # aún sin grants
    run(late, runbook_sql("grants"))
    assert run(late, runbook_sql("verify")) == EXPECTED_VERIFY

    # Orden A: los roles ya existen (son del cluster) -> la migración otorga los permisos sola.
    early = new_database(clean_postgres)
    command.upgrade(alembic_config(early), "head")
    assert run(early, runbook_sql("verify")) == EXPECTED_VERIFY

    assert privileges(late) == privileges(early)
    assert any(p[0] == "reference_loader" and p[2] == "INSERT" for p in privileges(early))


def test_the_roles_created_by_the_runbook_can_log_in_and_do_exactly_what_it_says(
    clean_postgres: str,
) -> None:
    run(clean_postgres, runbook_sql("roles"))
    database = new_database(clean_postgres)
    command.upgrade(alembic_config(database), "head")  # los roles existen: la migración otorga

    reader = make_conninfo(database, user="reference_reader", password="reader-pw")
    loader = make_conninfo(database, user="reference_loader", password="loader-pw")

    assert run(reader, "SELECT count(*) FROM reference.locale") == (0,)
    with pytest.raises(errors.InsufficientPrivilege):
        run(reader, "DELETE FROM reference.locale_alias")
    assert run(loader, "SELECT current_user") == ("reference_loader",)
    run(loader, "INSERT INTO reference.locale_alias VALUES ('iw', 'he')")
    run(loader, "DELETE FROM reference.locale_alias")
    with pytest.raises(errors.InsufficientPrivilege):
        run(loader, "TRUNCATE reference.locale_snapshot")


def test_the_documented_downgrade_leaves_what_the_runbook_says(clean_postgres: str) -> None:
    database = new_database(clean_postgres)
    config = alembic_config(database)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    with psycopg.connect(database, autocommit=True) as conn:
        left = conn.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'reference' "
            "AND tablename <> 'alembic_version'"
        ).fetchone()
        schema = conn.execute("SELECT to_regnamespace('reference') IS NOT NULL").fetchone()
    assert left == (0,) and schema == (True,)
    assert "alembic downgrade base" in RUNBOOK


# --- los comandos documentados existen ---------------------------------------------------------


def test_the_documented_uvicorn_factory_is_importable_and_callable() -> None:
    assert "uvicorn --factory gi_common_reference.app:app_from_environment" in RUNBOOK
    assert callable(import_from_string("gi_common_reference.app:app_from_environment"))


def test_the_documented_incorporation_command_targets_a_runnable_module() -> None:
    assert "python -m gi_common_reference.locales.interfaces.cli incorporate" in RUNBOOK
    module = ROOT / "src" / "gi_common_reference" / "locales" / "interfaces" / "cli.py"
    assert 'if __name__ == "__main__":' in module.read_text(encoding="utf-8")


def test_the_documented_migration_command_has_its_configuration() -> None:
    assert "alembic upgrade head" in RUNBOOK
    assert (ROOT / "alembic.ini").is_file() and (ROOT / "migrations" / "env.py").is_file()


def test_the_runbook_documents_every_exit_code_of_the_cli() -> None:
    for code in ("| 0 |", "| 1 |", "| 2 |"):
        assert code in RUNBOOK
