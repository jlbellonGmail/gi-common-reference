"""T2: migración 0001 (schema `reference`). Todo se prueba con SQL directo, sin la aplicación."""

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic import command
from psycopg import errors, sql
from testcontainers.community.postgres import PostgresContainer

from tests.conftest import alembic_config

SNAPSHOT_COLUMNS = [
    "snapshot_version",
    "content_digest",
    "iana_file_date",
    "iana_digest",
    "provenance",
    "artifact",
    "incorporated_at",
]
LOCALE_COLUMNS = [
    "locale_id",
    "code",
    "status",
    "iana_deprecated",
    "replacement_locale_id",
    "first_snapshot_version",
]
ALIAS_COLUMNS = ["subtag", "preferred_value"]
TABLES = ("locale", "locale_alias", "locale_snapshot")


def snapshot_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "snapshot_version": 1,
        "content_digest": "sha256:" + "a" * 64,
        "iana_file_date": "2026-09-01",
        "iana_digest": "sha256:" + "b" * 64,
        "provenance": "{}",
        "artifact": "{}",
        "incorporated_at": "2026-10-01T00:00:00Z",
    }
    return {**row, **overrides}


def locale_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "locale_id": uuid.uuid4(),
        "code": "es",
        "status": "active",
        "iana_deprecated": False,
        "replacement_locale_id": None,
        "first_snapshot_version": 1,
    }
    return {**row, **overrides}


def deprecated(**overrides: Any) -> dict[str, Any]:
    return locale_row(status="inactive", iana_deprecated=True, **overrides)


def insert(conn: psycopg.Connection, table: str, row: dict[str, Any]) -> None:
    columns = sql.SQL(", ").join(sql.Identifier(name) for name in row)
    marks = sql.SQL(", ").join(sql.Placeholder() for _ in row)
    query = sql.SQL("INSERT INTO reference.{} ({}) VALUES ({})").format(
        sql.Identifier(table), columns, marks
    )
    conn.execute(query, list(row.values()))


def rejected(error: type[Exception], constraint: str | None = None) -> Any:
    """Exige el tipo de error y, si se indica, el constraint que lo causó."""
    return _Rejected(error, constraint)


class _Rejected:
    def __init__(self, error: type[Exception], constraint: str | None) -> None:
        self.constraint = constraint
        self.context = pytest.raises(error)

    def __enter__(self) -> None:
        self.info = self.context.__enter__()

    def __exit__(self, *exc: Any) -> bool:
        swallowed = bool(self.context.__exit__(*exc))
        if swallowed and self.constraint is not None:
            diag = getattr(self.info.value, "diag")  # noqa: B009
            assert diag.constraint_name == self.constraint
        return swallowed


@pytest.fixture
def seeded(conn: psycopg.Connection) -> psycopg.Connection:
    insert(conn, "locale_snapshot", snapshot_row())
    return conn


def columns_of(conn: psycopg.Connection, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'reference' AND table_name = %s ORDER BY ordinal_position",
        [table],
    ).fetchall()
    return [r[0] for r in rows]


# --- estructura -------------------------------------------------------------------------------


def test_tables_have_exactly_the_planned_columns(conn: psycopg.Connection) -> None:
    assert columns_of(conn, "locale_snapshot") == SNAPSHOT_COLUMNS
    assert columns_of(conn, "locale") == LOCALE_COLUMNS
    assert columns_of(conn, "locale_alias") == ALIAS_COLUMNS


def test_tables_have_no_tenant_or_text_columns(conn: psycopg.Connection) -> None:
    """RF-1, RF-6, CA-18: allowlist de columnas."""
    forbidden = {"tenant_id", "name", "display_name", "localized_name", "description", "label"}
    for table in TABLES:
        assert not forbidden & set(columns_of(conn, table))


def test_foreign_keys_stay_inside_schema_reference(conn: psycopg.Connection) -> None:
    """RNF-6: ninguna FK hacia otros catálogos o schemas."""
    rows = conn.execute(
        "SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint "
        "WHERE contype = 'f' AND connamespace = 'reference'::regnamespace"
    ).fetchall()
    assert rows
    assert all(a.startswith("reference.") and b.startswith("reference.") for a, b in rows)


def test_replacement_fk_is_deferred_and_first_snapshot_fk_is_not(conn: psycopg.Connection) -> None:
    deferred: dict[str, bool] = dict(
        conn.execute(
            "SELECT a.attname, c.condeferrable AND c.condeferred FROM pg_constraint c "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
            "WHERE c.contype = 'f' AND c.conrelid = 'reference.locale'::regclass"
        ).fetchall()
    )
    assert deferred == {"replacement_locale_id": True, "first_snapshot_version": False}


def test_code_format_check_exists_with_stable_name(conn: psycopg.Connection) -> None:
    """RNF-7: el CHECK de formato tiene nombre explícito y estable."""
    rows = conn.execute(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE contype = 'c' AND conrelid = 'reference.locale'::regclass "
        "AND conname = 'locale_code_format'"
    ).fetchall()
    assert len(rows) == 1
    assert "[a-z]{2,3}" in rows[0][1]


# --- NOT NULL ---------------------------------------------------------------------------------


@pytest.mark.parametrize("column", SNAPSHOT_COLUMNS)
def test_snapshot_columns_reject_null(conn: psycopg.Connection, column: str) -> None:
    with rejected(errors.NotNullViolation):
        insert(conn, "locale_snapshot", snapshot_row(**{column: None}))


@pytest.mark.parametrize("column", [c for c in LOCALE_COLUMNS if c != "replacement_locale_id"])
def test_locale_columns_reject_null(seeded: psycopg.Connection, column: str) -> None:
    with rejected(errors.NotNullViolation):
        insert(seeded, "locale", locale_row(**{column: None}))


def test_replacement_is_the_only_nullable_locale_column(seeded: psycopg.Connection) -> None:
    insert(seeded, "locale", locale_row(replacement_locale_id=None))


@pytest.mark.parametrize("column", ALIAS_COLUMNS)
def test_alias_columns_reject_null(conn: psycopg.Connection, column: str) -> None:
    row = {"subtag": "iw", "preferred_value": "he", column: None}
    with rejected(errors.NotNullViolation):
        insert(conn, "locale_alias", row)


# --- unicidad y formato -----------------------------------------------------------------------


def test_duplicate_locale_id_is_rejected(seeded: psycopg.Connection) -> None:
    same = uuid.uuid4()
    insert(seeded, "locale", locale_row(locale_id=same, code="es"))
    with rejected(errors.UniqueViolation, "locale_pkey"):
        insert(seeded, "locale", locale_row(locale_id=same, code="en"))


def test_duplicate_code_is_rejected(seeded: psycopg.Connection) -> None:
    insert(seeded, "locale", locale_row(code="es"))
    with rejected(errors.UniqueViolation, "locale_code_key"):
        insert(seeded, "locale", locale_row(code="es"))


def test_duplicate_snapshot_version_is_rejected(seeded: psycopg.Connection) -> None:
    with rejected(errors.UniqueViolation, "locale_snapshot_pkey"):
        insert(seeded, "locale_snapshot", snapshot_row())


@pytest.mark.parametrize("version", [0, -1])
def test_non_positive_snapshot_version_is_rejected(conn: psycopg.Connection, version: int) -> None:
    with rejected(errors.CheckViolation, "locale_snapshot_version_positive"):
        insert(conn, "locale_snapshot", snapshot_row(snapshot_version=version))


@pytest.mark.parametrize("code", ["ES", "He", "e", "espa", "es-AR", "es_AR", " es", "e1", ""])
def test_code_outside_format_is_rejected(seeded: psycopg.Connection, code: str) -> None:
    with rejected(errors.CheckViolation, "locale_code_format"):
        insert(seeded, "locale", locale_row(code=code))


@pytest.mark.parametrize("code", ["es", "fil"])
def test_code_inside_format_is_accepted(seeded: psycopg.Connection, code: str) -> None:
    insert(seeded, "locale", locale_row(code=code))


def test_invalid_status_is_rejected(seeded: psycopg.Connection) -> None:
    with rejected(errors.CheckViolation, "locale_status_valid"):
        insert(seeded, "locale", locale_row(status="deprecated"))


def test_alias_subtag_is_unique(conn: psycopg.Connection) -> None:
    insert(conn, "locale_alias", {"subtag": "iw", "preferred_value": "he"})
    with rejected(errors.UniqueViolation, "locale_alias_pkey"):
        insert(conn, "locale_alias", {"subtag": "iw", "preferred_value": "he"})


# --- replacement y estado ---------------------------------------------------------------------


def test_replacement_to_self_is_rejected(seeded: psycopg.Connection) -> None:
    own = uuid.uuid4()
    with rejected(errors.CheckViolation, "locale_replacement_not_self"):
        insert(seeded, "locale", deprecated(locale_id=own, code="iw", replacement_locale_id=own))


def test_replacement_to_missing_locale_is_rejected(seeded: psycopg.Connection) -> None:
    with rejected(errors.ForeignKeyViolation, "locale_replacement_fk"):
        insert(seeded, "locale", deprecated(code="iw", replacement_locale_id=uuid.uuid4()))


def test_replacement_without_iana_deprecation_is_rejected(seeded: psycopg.Connection) -> None:
    target = uuid.uuid4()
    insert(seeded, "locale", locale_row(locale_id=target, code="he"))
    with rejected(errors.CheckViolation, "locale_replacement_requires_deprecation"):
        insert(seeded, "locale", locale_row(code="iw", replacement_locale_id=target))


def test_deprecated_locale_cannot_be_active(seeded: psycopg.Connection) -> None:
    with rejected(errors.CheckViolation, "locale_deprecated_is_inactive"):
        insert(seeded, "locale", locale_row(code="iw", iana_deprecated=True, status="active"))


def test_replacement_to_existing_locale_is_accepted(seeded: psycopg.Connection) -> None:
    target = uuid.uuid4()
    insert(seeded, "locale", locale_row(locale_id=target, code="he"))
    insert(seeded, "locale", deprecated(code="iw", replacement_locale_id=target))


def test_replacement_may_reference_a_locale_inserted_later_in_the_transaction(
    database_url: str,
) -> None:
    """La FK diferida admite un `replacement` hacia un locale nuevo del mismo snapshot."""
    target, old = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(database_url) as conn:
        insert(conn, "locale_snapshot", snapshot_row())
        insert(conn, "locale", deprecated(locale_id=old, code="iw", replacement_locale_id=target))
        insert(conn, "locale", locale_row(locale_id=target, code="he"))
        conn.commit()


def test_inactive_without_deprecation_is_allowed(seeded: psycopg.Connection) -> None:
    insert(seeded, "locale", locale_row(status="inactive"))


def test_first_snapshot_version_must_exist(seeded: psycopg.Connection) -> None:
    with rejected(errors.ForeignKeyViolation, "locale_first_snapshot_fk"):
        insert(seeded, "locale", locale_row(first_snapshot_version=99))


# --- triggers de inmutabilidad ----------------------------------------------------------------


def test_locale_cannot_be_deleted(seeded: psycopg.Connection) -> None:
    insert(seeded, "locale", locale_row(code="es"))
    with rejected(errors.RestrictViolation):
        seeded.execute("DELETE FROM reference.locale")


def test_locale_id_and_code_cannot_change(seeded: psycopg.Connection) -> None:
    insert(seeded, "locale", locale_row(code="es"))
    with rejected(errors.RestrictViolation):
        seeded.execute("UPDATE reference.locale SET code = 'en'")
    with rejected(errors.RestrictViolation):
        seeded.execute("UPDATE reference.locale SET locale_id = gen_random_uuid()")


def test_locale_metadata_can_change(seeded: psycopg.Connection) -> None:
    insert(seeded, "locale", locale_row(code="es"))
    seeded.execute("UPDATE reference.locale SET status = 'inactive'")
    assert seeded.execute("SELECT status FROM reference.locale").fetchone() == ("inactive",)


def test_locale_snapshot_is_immutable(seeded: psycopg.Connection) -> None:
    with rejected(errors.RestrictViolation):
        seeded.execute("UPDATE reference.locale_snapshot SET content_digest = 'x'")
    with rejected(errors.RestrictViolation):
        seeded.execute("DELETE FROM reference.locale_snapshot")


# --- TRUNCATE (L-8) ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", ["locale_snapshot", "locale"])
def test_truncate_has_a_before_statement_trigger(conn: psycopg.Connection, table: str) -> None:
    """tgtype: 1 = por fila, 2 = BEFORE, 32 = TRUNCATE. TRUNCATE no dispara triggers por fila."""
    rows = conn.execute(
        "SELECT tgtype::int FROM pg_trigger WHERE tgrelid = %s::regclass AND NOT tgisinternal",
        [f"reference.{table}"],
    ).fetchall()
    truncate = [t for (t,) in rows if t & 32]
    assert len(truncate) == 1
    assert truncate[0] & 2 and not truncate[0] & 1


def test_locale_snapshot_cannot_be_truncated(seeded: psycopg.Connection) -> None:
    insert(seeded, "locale", locale_row(code="es"))
    with rejected(errors.RestrictViolation):
        seeded.execute("TRUNCATE reference.locale_snapshot CASCADE")
    with pytest.raises(psycopg.Error):
        seeded.execute("TRUNCATE reference.locale_snapshot")  # lo frena la FK o el trigger
    assert seeded.execute("SELECT count(*) FROM reference.locale_snapshot").fetchone() == (1,)
    assert seeded.execute("SELECT count(*) FROM reference.locale").fetchone() == (1,)


def test_locale_cannot_be_truncated(seeded: psycopg.Connection) -> None:
    insert(seeded, "locale", locale_row(code="es"))
    with rejected(errors.RestrictViolation):
        seeded.execute("TRUNCATE reference.locale")
    assert seeded.execute("SELECT count(*) FROM reference.locale").fetchone() == (1,)


def test_the_truncate_protection_also_applies_to_an_empty_table(conn: psycopg.Connection) -> None:
    with rejected(errors.RestrictViolation):
        conn.execute("TRUNCATE reference.locale")
    with rejected(errors.RestrictViolation):
        conn.execute("TRUNCATE reference.locale_snapshot CASCADE")


def test_alias_may_still_be_replaced_because_it_is_not_historical(conn: psycopg.Connection) -> None:
    insert(conn, "locale_alias", {"subtag": "iw", "preferred_value": "he"})
    conn.execute("TRUNCATE reference.locale_alias")
    assert conn.execute("SELECT count(*) FROM reference.locale_alias").fetchone() == (0,)


# --- privilegios (RNF-4, D10) -----------------------------------------------------------------


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_supabase_api_roles_have_no_access(conn: psycopg.Connection, role: str) -> None:
    usage = conn.execute("SELECT has_schema_privilege(%s, 'reference', 'USAGE')", [role])
    assert usage.fetchone() == (False,)
    for table in TABLES:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            granted = conn.execute(
                "SELECT has_table_privilege(%s, %s, %s)", [role, f"reference.{table}", privilege]
            ).fetchone()
            assert granted == (False,), (role, table, privilege)


def test_public_has_no_access(conn: psycopg.Connection) -> None:
    schema_public = conn.execute(
        "SELECT count(*) FROM pg_namespace n, aclexplode(n.nspacl) a "
        "WHERE n.nspname = 'reference' AND a.grantee = 0"
    ).fetchone()
    tables_public = conn.execute(
        "SELECT count(*) FROM pg_class c, aclexplode(c.relacl) a "
        "WHERE c.relnamespace = 'reference'::regnamespace AND a.grantee = 0"
    ).fetchone()
    assert schema_public == (0,)
    assert tables_public == (0,)


def as_role(conn: psycopg.Connection, role: str) -> Iterator[None]:
    conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
    try:
        yield
    finally:
        conn.execute("RESET ROLE")


def test_reader_can_select_but_not_write(seeded: psycopg.Connection) -> None:
    insert(seeded, "locale", locale_row(code="es"))
    for _ in as_role(seeded, "reference_reader"):
        for table in TABLES:
            seeded.execute(sql.SQL("SELECT * FROM reference.{}").format(sql.Identifier(table)))
        with rejected(errors.InsufficientPrivilege):
            insert(seeded, "locale_alias", {"subtag": "iw", "preferred_value": "he"})
        with rejected(errors.InsufficientPrivilege):
            seeded.execute("UPDATE reference.locale SET status = 'inactive'")
        with rejected(errors.InsufficientPrivilege):
            seeded.execute("DELETE FROM reference.locale_alias")
        with rejected(errors.InsufficientPrivilege):
            insert(seeded, "locale_snapshot", snapshot_row(snapshot_version=2))


def test_loader_can_load_but_not_alter_identity_or_history(conn: psycopg.Connection) -> None:
    for _ in as_role(conn, "reference_loader"):
        insert(conn, "locale_snapshot", snapshot_row())
        insert(conn, "locale", locale_row(code="es"))
        conn.execute("UPDATE reference.locale SET status = 'inactive'")
        insert(conn, "locale_alias", {"subtag": "iw", "preferred_value": "he"})
        conn.execute("DELETE FROM reference.locale_alias")
        with rejected(errors.InsufficientPrivilege):
            conn.execute("UPDATE reference.locale SET code = 'en'")
        with rejected(errors.InsufficientPrivilege):
            conn.execute("DELETE FROM reference.locale")
        with rejected(errors.InsufficientPrivilege):
            conn.execute("UPDATE reference.locale_snapshot SET content_digest = 'x'")
        with rejected(errors.InsufficientPrivilege):
            conn.execute("DELETE FROM reference.locale_snapshot")
        with rejected(errors.InsufficientPrivilege):
            conn.execute("TRUNCATE reference.locale_snapshot")
        with rejected(errors.InsufficientPrivilege):
            conn.execute("TRUNCATE reference.locale")


# --- downgrade y roles ausentes ---------------------------------------------------------------


def test_downgrade_removes_tables_and_upgrade_can_repeat(database_url: str) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "base")
    with psycopg.connect(database_url, autocommit=True) as conn:
        left = conn.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'reference' "
            "AND tablename IN ('locale', 'locale_alias', 'locale_snapshot')"
        ).fetchone()
        assert left == (0,)
    command.upgrade(config, "head")


@pytest.fixture(scope="module")
def bare_postgres_url() -> Iterator[str]:
    """Un Postgres sin los roles de la API, como un entorno donde aún no se crearon."""
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        yield pg.get_connection_url()


def test_migration_runs_when_reader_and_loader_roles_do_not_exist(bare_postgres_url: str) -> None:
    command.upgrade(alembic_config(bare_postgres_url), "head")
    with psycopg.connect(bare_postgres_url) as conn:
        assert conn.execute("SELECT to_regclass('reference.locale')").fetchone() == (
            "reference.locale",
        )
        roles = conn.execute(
            "SELECT count(*) FROM pg_roles "
            "WHERE rolname IN ('reference_reader', 'reference_loader')"
        ).fetchone()
        assert roles == (0,)
