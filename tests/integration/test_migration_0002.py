"""T2: migración 0002 (regiones y subregiones), probada con SQL directo, sin la aplicación."""

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic import command
from psycopg import errors, sql

from tests.conftest import alembic_config
from tests.integration.test_migration_0001 import columns_of, insert, locale_row, rejected
from tests.integration.test_migration_0001 import snapshot_row as locale_snapshot_row

COLUMNS = {
    "region_snapshot": [
        "snapshot_version",
        "content_digest",
        "locale_snapshot_version",
        "required_locales_version",
        "provenance",
        "artifact",
        "incorporated_at",
    ],
    "region": [
        "region_id",
        "code",
        "code_snapshot_version",
        "status",
        "replacement_region_id",
        "first_snapshot_version",
    ],
    "subregion": [
        "subregion_id",
        "region_id",
        "code",
        "code_snapshot_version",
        "status",
        "replacement_subregion_id",
        "first_snapshot_version",
    ],
    "region_locale": ["region_id", "locale_id", "name"],
    "subregion_locale": ["subregion_id", "locale_id", "name"],
    "subregion_reclassification": [
        "subregion_id",
        "snapshot_version",
        "previous_region_id",
        "new_region_id",
    ],
    "region_recoding": [
        "region_id",
        "snapshot_version",
        "previous_code",
        "new_code",
        "provenance",
    ],
    "subregion_recoding": [
        "subregion_id",
        "snapshot_version",
        "previous_code",
        "new_code",
        "provenance",
    ],
}
NULLABLE = {
    "code",
    "code_snapshot_version",
    "replacement_region_id",
    "replacement_subregion_id",
}
HISTORY = ("region_snapshot", "subregion_reclassification", "region_recoding", "subregion_recoding")
CATALOG = ("region", "subregion", "region_locale", "subregion_locale")
# Una tabla referenciada por FK no se puede vaciar sin CASCADE (0A000); con CASCADE lo impide el
# trigger. En ambos casos la tabla queda intacta.
TRUNCATE_REJECTIONS = (errors.RestrictViolation, errors.FeatureNotSupported)

LOCALE_ID = str(uuid.uuid4())
AMERICAS = str(uuid.uuid4())
AFRICA = str(uuid.uuid4())
LATAM = str(uuid.uuid4())
NORTHERN_AMERICA = str(uuid.uuid4())


def region_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "region_id": str(uuid.uuid4()),
        "code": "019",
        "code_snapshot_version": 1,
        "status": "active",
        "replacement_region_id": None,
        "first_snapshot_version": 1,
    }
    return {**row, **overrides}


def subregion_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "subregion_id": str(uuid.uuid4()),
        "region_id": AMERICAS,
        "code": "419",
        "code_snapshot_version": 1,
        "status": "active",
        "replacement_subregion_id": None,
        "first_snapshot_version": 1,
    }
    return {**row, **overrides}


def region_snapshot_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "snapshot_version": 1,
        "content_digest": "sha256:" + "c" * 64,
        "locale_snapshot_version": 1,
        "required_locales_version": 1,
        "provenance": "{}",
        "artifact": "{}",
    }
    return {**row, **overrides}


@pytest.fixture
def base(conn: psycopg.Connection) -> psycopg.Connection:
    """Locale publicado y un snapshot de regiones, sin entidades."""
    insert(conn, "locale_snapshot", locale_snapshot_row())
    insert(conn, "locale", locale_row(locale_id=LOCALE_ID, code="en"))
    insert(conn, "region_snapshot", region_snapshot_row())
    return conn


@pytest.fixture
def catalog(base: psycopg.Connection) -> psycopg.Connection:
    """Americas (019) con Latin America and the Caribbean (419); Africa (002) sin subregiones."""
    insert(base, "region", region_row(region_id=AMERICAS, code="019"))
    insert(base, "region", region_row(region_id=AFRICA, code="002"))
    insert(base, "subregion", subregion_row(subregion_id=LATAM, code="419"))
    insert(base, "region_locale", {"region_id": AMERICAS, "locale_id": LOCALE_ID, "name": "x"})
    insert(base, "subregion_locale", {"subregion_id": LATAM, "locale_id": LOCALE_ID, "name": "y"})
    return base


def constraint_of(error: pytest.ExceptionInfo[Exception]) -> str | None:
    name: str | None = getattr(error.value, "diag").constraint_name  # noqa: B009
    return name


# --- estructura -------------------------------------------------------------------------------


def test_tables_have_exactly_the_planned_columns(conn: psycopg.Connection) -> None:
    for table, columns in COLUMNS.items():
        assert columns_of(conn, table) == columns, table


def test_region_and_subregion_have_no_tenant_or_text_columns(conn: psycopg.Connection) -> None:
    """RF-1, RF-8, CA-1: los nombres solo viven en las tablas `*_locale`."""
    forbidden = {"tenant_id", "name", "display_name", "localized_name", "description", "label"}
    for table in COLUMNS:
        assert "tenant_id" not in columns_of(conn, table)
    for table in ("region", "subregion", "region_snapshot"):
        assert not forbidden & set(columns_of(conn, table))
    assert not {"region_code", "region_name", "language", "lang"} & set(columns_of(conn, "region"))


def test_foreign_keys_stay_inside_schema_reference_and_point_only_to_locale(
    conn: psycopg.Connection,
) -> None:
    """RNF-6: Regions depende solo de Locale (y de sí mismo)."""
    rows = conn.execute(
        "SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint "
        "WHERE contype = 'f' AND connamespace = 'reference'::regnamespace"
    ).fetchall()
    targets = {target for source, target in rows if source.removeprefix("reference.") in COLUMNS}
    assert targets == {
        "reference.region",
        "reference.subregion",
        "reference.region_snapshot",
        "reference.locale",
        "reference.locale_snapshot",
    }


def test_active_code_constraints_are_deferred_to_the_commit(conn: psycopg.Connection) -> None:
    """RF-42: se evalúan sobre el estado final de la transacción."""
    rows: dict[str, bool] = dict(
        conn.execute(
            "SELECT conname, condeferrable AND condeferred FROM pg_constraint "
            "WHERE connamespace = 'reference'::regnamespace AND conname = ANY (%s)",
            [
                [
                    "region_active_code_unique",
                    "subregion_active_code_unique",
                    "region_active_code_disjoint",
                    "subregion_active_code_disjoint",
                    "region_active_subregions",
                    "subregion_active_region",
                    "region_replacement_fk",
                    "subregion_replacement_fk",
                ]
            ],
        ).fetchall()
    )
    assert len(rows) == 8 and all(rows.values()), rows


@pytest.mark.parametrize("table", list(COLUMNS))
def test_every_required_column_rejects_null(base: psycopg.Connection, table: str) -> None:
    rows: dict[str, dict[str, Any]] = {
        "region_snapshot": region_snapshot_row(snapshot_version=2),
        "region": region_row(region_id=AMERICAS),
        "subregion": subregion_row(),
        "region_locale": {"region_id": AMERICAS, "locale_id": LOCALE_ID, "name": "x"},
        "subregion_locale": {"subregion_id": LATAM, "locale_id": LOCALE_ID, "name": "y"},
        "subregion_reclassification": {
            "subregion_id": LATAM,
            "snapshot_version": 1,
            "previous_region_id": AMERICAS,
            "new_region_id": AFRICA,
        },
        "region_recoding": {
            "region_id": AMERICAS,
            "snapshot_version": 1,
            "previous_code": "019",
            "new_code": "020",
            "provenance": "{}",
        },
        "subregion_recoding": {
            "subregion_id": LATAM,
            "snapshot_version": 1,
            "previous_code": "419",
            "new_code": "420",
            "provenance": "{}",
        },
    }
    for column in COLUMNS[table]:
        if column in NULLABLE or column == "incorporated_at":
            continue
        with base.transaction(), rejected(errors.NotNullViolation):
            insert(base, table, {**rows[table], column: None})


# --- códigos (RF-3, RF-4, RF-42) ----------------------------------------------------------------


@pytest.mark.parametrize("code", ["19", "0019", "abc", "", " 19", "01a"])
def test_code_must_have_three_digits(base: psycopg.Connection, code: str) -> None:
    with rejected(errors.CheckViolation, "region_code_format"):
        insert(base, "region", region_row(code=code))
    with rejected(errors.CheckViolation, "subregion_code_format"):
        insert(base, "region", region_row(region_id=AMERICAS, code="019"))
        insert(base, "subregion", subregion_row(code=code))


def test_code_is_optional_but_its_snapshot_goes_with_it(base: psycopg.Connection) -> None:
    insert(base, "region", region_row(code=None, code_snapshot_version=None))
    with rejected(errors.CheckViolation, "region_code_snapshot_consistent"):
        insert(base, "region", region_row(code=None, code_snapshot_version=1))
    with rejected(errors.CheckViolation, "region_code_snapshot_consistent"):
        insert(base, "region", region_row(code="002", code_snapshot_version=None))


def test_two_active_regions_cannot_share_a_code(catalog: psycopg.Connection) -> None:
    with rejected(errors.ExclusionViolation, "region_active_code_unique"):
        insert(catalog, "region", region_row(code="019"))
    with rejected(errors.ExclusionViolation, "subregion_active_code_unique"):
        insert(catalog, "subregion", subregion_row(code="419"))


def test_inactive_entities_may_keep_a_code_that_an_active_one_has(
    catalog: psycopg.Connection,
) -> None:
    insert(catalog, "region", region_row(code="019", status="inactive"))
    insert(catalog, "subregion", subregion_row(code="419", status="inactive"))


def test_an_active_region_and_an_active_subregion_cannot_share_a_code(
    catalog: psycopg.Connection,
) -> None:
    with pytest.raises(errors.ExclusionViolation) as error:
        insert(catalog, "region", region_row(code="419"))
    assert constraint_of(error) == "region_subregion_active_code_disjoint"
    with pytest.raises(errors.ExclusionViolation) as error:
        insert(catalog, "subregion", subregion_row(code="019"))
    assert constraint_of(error) == "region_subregion_active_code_disjoint"
    insert(catalog, "subregion", subregion_row(code="019", status="inactive"))


def test_swapping_codes_in_one_transaction_is_valid_on_the_final_state(
    catalog: psycopg.Connection,
) -> None:
    other = str(uuid.uuid4())
    insert(catalog, "subregion", subregion_row(subregion_id=other, code="021"))
    with catalog.transaction():
        catalog.execute(
            "UPDATE reference.subregion SET code = '021' WHERE subregion_id = %s", [LATAM]
        )
        catalog.execute(
            "UPDATE reference.subregion SET code = '419' WHERE subregion_id = %s", [other]
        )
    codes: dict[str, str] = dict(
        catalog.execute("SELECT subregion_id::text, code FROM reference.subregion")
    )
    assert codes == {LATAM: "021", other: "419"}


def test_a_collision_left_at_commit_is_rejected(catalog: psycopg.Connection) -> None:
    with pytest.raises(errors.ExclusionViolation), catalog.transaction():
        insert(catalog, "region", region_row(code="002"))


# --- jerarquía y ciclo de vida (RF-5, RF-7, RF-27, RF-36) ---------------------------------------


def test_a_subregion_needs_an_existing_region(base: psycopg.Connection) -> None:
    with rejected(errors.ForeignKeyViolation, "subregion_region_fk"):
        insert(base, "subregion", subregion_row(region_id=str(uuid.uuid4())))


def test_an_active_subregion_cannot_live_in_an_inactive_region(
    catalog: psycopg.Connection,
) -> None:
    with pytest.raises(errors.CheckViolation) as error:
        catalog.execute(
            "UPDATE reference.region SET status = 'inactive' WHERE region_id = %s", [AMERICAS]
        )
    assert constraint_of(error) == "subregion_active_requires_active_region"
    catalog.execute(
        "UPDATE reference.region SET status = 'inactive' WHERE region_id = %s", [AFRICA]
    )
    with pytest.raises(errors.CheckViolation) as error:
        insert(catalog, "subregion", subregion_row(region_id=AFRICA, code="014"))
    assert constraint_of(error) == "subregion_active_requires_active_region"
    insert(catalog, "subregion", subregion_row(region_id=AFRICA, code="014", status="inactive"))


def test_replacement_rules(catalog: psycopg.Connection) -> None:
    with rejected(errors.CheckViolation, "region_replacement_requires_inactive"):
        insert(catalog, "region", region_row(code="142", replacement_region_id=AMERICAS))
    own = str(uuid.uuid4())
    with rejected(errors.CheckViolation, "region_replacement_not_self"):
        insert(
            catalog,
            "region",
            region_row(
                region_id=own,
                code=None,
                code_snapshot_version=None,
                status="inactive",
                replacement_region_id=own,
            ),
        )
    with rejected(errors.ForeignKeyViolation, "region_replacement_fk"):
        insert(
            catalog,
            "region",
            region_row(code="142", status="inactive", replacement_region_id=str(uuid.uuid4())),
        )
    with rejected(errors.CheckViolation, "subregion_replacement_requires_inactive"):
        insert(catalog, "subregion", subregion_row(code="021", replacement_subregion_id=LATAM))
    with rejected(errors.ForeignKeyViolation, "subregion_replacement_fk"):
        insert(
            catalog,
            "subregion",
            subregion_row(code="021", status="inactive", replacement_subregion_id=AMERICAS),
        )
    insert(
        catalog,
        "subregion",
        subregion_row(code="021", status="inactive", replacement_subregion_id=LATAM),
    )


# --- localizaciones (RF-9–RF-12) -----------------------------------------------------------------


def test_localizations_need_an_existing_entity_and_locale(catalog: psycopg.Connection) -> None:
    with rejected(errors.ForeignKeyViolation, "region_locale_region_fk"):
        insert(
            catalog,
            "region_locale",
            {"region_id": str(uuid.uuid4()), "locale_id": LOCALE_ID, "name": "x"},
        )
    with rejected(errors.ForeignKeyViolation, "region_locale_locale_fk"):
        insert(
            catalog,
            "region_locale",
            {"region_id": AFRICA, "locale_id": str(uuid.uuid4()), "name": "x"},
        )
    with rejected(errors.ForeignKeyViolation, "subregion_locale_subregion_fk"):
        insert(
            catalog,
            "subregion_locale",
            {"subregion_id": str(uuid.uuid4()), "locale_id": LOCALE_ID, "name": "x"},
        )
    with rejected(errors.ForeignKeyViolation, "subregion_locale_locale_fk"):
        insert(
            catalog,
            "subregion_locale",
            {"subregion_id": LATAM, "locale_id": str(uuid.uuid4()), "name": "x"},
        )


def test_one_localization_per_entity_and_locale(catalog: psycopg.Connection) -> None:
    with rejected(errors.UniqueViolation, "region_locale_pkey"):
        insert(
            catalog,
            "region_locale",
            {"region_id": AMERICAS, "locale_id": LOCALE_ID, "name": "otro"},
        )
    with rejected(errors.UniqueViolation, "subregion_locale_pkey"):
        insert(
            catalog,
            "subregion_locale",
            {"subregion_id": LATAM, "locale_id": LOCALE_ID, "name": "otro"},
        )


@pytest.mark.parametrize("name", ["", " Americas", "Americas ", "\tAmericas", "Americas\n", " "])
def test_names_are_not_empty_nor_padded(catalog: psycopg.Connection, name: str) -> None:
    with rejected(errors.CheckViolation, "region_locale_name_trimmed"):
        insert(
            catalog, "region_locale", {"region_id": AFRICA, "locale_id": LOCALE_ID, "name": name}
        )
    with rejected(errors.CheckViolation, "subregion_locale_name_trimmed"):
        catalog.execute("UPDATE reference.subregion_locale SET name = %s", [name])


# --- RF-29, RF-35: FK compuesta desde otro catálogo ---------------------------------------------


@pytest.fixture
def dependent(catalog: psycopg.Connection) -> psycopg.Connection:
    """Un catálogo de prueba que referencia el par (region_id, subregion_id), como hará Country."""
    catalog.execute(
        "CREATE TABLE reference.test_dependent (id int PRIMARY KEY, region_id uuid NOT NULL, "
        "subregion_id uuid, CONSTRAINT test_dependent_pair_fk "
        "FOREIGN KEY (region_id, subregion_id) "
        "REFERENCES reference.subregion (region_id, subregion_id) DEFERRABLE INITIALLY DEFERRED)"
    )
    catalog.execute("INSERT INTO reference.test_dependent VALUES (1, %s, %s)", [AMERICAS, LATAM])
    return catalog


def test_an_incoherent_region_subregion_pair_is_rejected(dependent: psycopg.Connection) -> None:
    with rejected(errors.ForeignKeyViolation, "test_dependent_pair_fk"):
        dependent.execute(
            "INSERT INTO reference.test_dependent VALUES (2, %s, %s)", [AFRICA, LATAM]
        )


def test_a_reclassification_that_leaves_a_dependent_incoherent_is_rejected(
    dependent: psycopg.Connection,
) -> None:
    with rejected(errors.ForeignKeyViolation, "test_dependent_pair_fk"):
        dependent.execute(
            "UPDATE reference.subregion SET region_id = %s WHERE subregion_id = %s",
            [AFRICA, LATAM],
        )
    region = dependent.execute(
        "SELECT region_id::text FROM reference.subregion WHERE subregion_id = %s", [LATAM]
    ).fetchone()
    assert region == (AMERICAS,)


def test_a_reclassification_fixed_in_the_same_transaction_is_accepted(
    dependent: psycopg.Connection,
) -> None:
    with dependent.transaction():
        dependent.execute(
            "UPDATE reference.subregion SET region_id = %s WHERE subregion_id = %s",
            [AFRICA, LATAM],
        )
        dependent.execute("UPDATE reference.test_dependent SET region_id = %s", [AFRICA])
    pair = dependent.execute(
        "SELECT region_id::text, subregion_id::text FROM reference.test_dependent"
    ).fetchone()
    assert pair == (AFRICA, LATAM)


# --- inmutabilidad (RF-2, RF-22, RF-30, RNF-5) ---------------------------------------------------


@pytest.mark.parametrize("table", CATALOG)
def test_catalog_rows_are_never_deleted_nor_truncated(
    catalog: psycopg.Connection, table: str
) -> None:
    with rejected(errors.RestrictViolation):
        catalog.execute(sql.SQL("DELETE FROM reference.{}").format(sql.Identifier(table)))
    with pytest.raises(TRUNCATE_REJECTIONS):
        catalog.execute(sql.SQL("TRUNCATE reference.{}").format(sql.Identifier(table)))
    with rejected(errors.RestrictViolation):
        catalog.execute(sql.SQL("TRUNCATE reference.{} CASCADE").format(sql.Identifier(table)))
    count = catalog.execute(
        sql.SQL("SELECT count(*) FROM reference.{}").format(sql.Identifier(table))
    ).fetchone()
    assert count is not None and count[0] >= 1


@pytest.fixture
def history(catalog: psycopg.Connection) -> psycopg.Connection:
    insert(
        catalog,
        "subregion_reclassification",
        {
            "subregion_id": LATAM,
            "snapshot_version": 1,
            "previous_region_id": AFRICA,
            "new_region_id": AMERICAS,
        },
    )
    insert(
        catalog,
        "region_recoding",
        {
            "region_id": AMERICAS,
            "snapshot_version": 1,
            "previous_code": "018",
            "new_code": "019",
            "provenance": "{}",
        },
    )
    insert(
        catalog,
        "subregion_recoding",
        {
            "subregion_id": LATAM,
            "snapshot_version": 1,
            "previous_code": "418",
            "new_code": "419",
            "provenance": "{}",
        },
    )
    return catalog


@pytest.mark.parametrize("table", HISTORY)
def test_history_is_immutable(history: psycopg.Connection, table: str) -> None:
    identifier = sql.Identifier(table)
    column = "content_digest" if table == "region_snapshot" else "snapshot_version"
    value = "'x'" if table == "region_snapshot" else "1"
    with rejected(errors.RestrictViolation):
        history.execute(
            sql.SQL("UPDATE reference.{} SET {} = " + value).format(
                identifier, sql.Identifier(column)
            )
        )
    with rejected(errors.RestrictViolation):
        history.execute(sql.SQL("DELETE FROM reference.{}").format(identifier))
    with pytest.raises(TRUNCATE_REJECTIONS):
        history.execute(sql.SQL("TRUNCATE reference.{}").format(identifier))
    with rejected(errors.RestrictViolation):
        history.execute(sql.SQL("TRUNCATE reference.{} CASCADE").format(identifier))


def test_traces_need_a_real_change(catalog: psycopg.Connection) -> None:
    with rejected(errors.CheckViolation, "subregion_reclassification_changes_region"):
        insert(
            catalog,
            "subregion_reclassification",
            {
                "subregion_id": LATAM,
                "snapshot_version": 1,
                "previous_region_id": AMERICAS,
                "new_region_id": AMERICAS,
            },
        )
    with rejected(errors.CheckViolation, "region_recoding_changes_code"):
        insert(
            catalog,
            "region_recoding",
            {
                "region_id": AMERICAS,
                "snapshot_version": 1,
                "previous_code": "019",
                "new_code": "019",
                "provenance": "{}",
            },
        )
    with rejected(errors.CheckViolation, "subregion_recoding_code_format"):
        insert(
            catalog,
            "subregion_recoding",
            {
                "subregion_id": LATAM,
                "snapshot_version": 1,
                "previous_code": "19",
                "new_code": "419",
                "provenance": "{}",
            },
        )


@pytest.mark.parametrize(
    ("table", "column", "key"),
    [
        ("region", "region_id", "region_id"),
        ("region", "first_snapshot_version", "region_id"),
        ("subregion", "subregion_id", "subregion_id"),
        ("subregion", "first_snapshot_version", "subregion_id"),
        ("region_locale", "locale_id", "region_id"),
        ("region_locale", "region_id", "region_id"),
        ("subregion_locale", "locale_id", "subregion_id"),
        ("subregion_locale", "subregion_id", "subregion_id"),
    ],
)
def test_identity_columns_are_immutable(
    catalog: psycopg.Connection, table: str, column: str, key: str
) -> None:
    insert(catalog, "region_snapshot", region_snapshot_row(snapshot_version=2))
    other_locale = str(uuid.uuid4())
    insert(catalog, "locale", locale_row(locale_id=other_locale, code="es"))
    values = {
        "region_id": AFRICA,
        "subregion_id": str(uuid.uuid4()),
        "locale_id": other_locale,
        "first_snapshot_version": 2,
    }
    with rejected(errors.RestrictViolation):
        catalog.execute(
            sql.SQL("UPDATE reference.{} SET {} = %s").format(
                sql.Identifier(table), sql.Identifier(column)
            ),
            [values[column]],
        )


def test_classification_codes_status_replacement_and_names_are_mutable(
    catalog: psycopg.Connection,
) -> None:
    insert(catalog, "region_snapshot", region_snapshot_row(snapshot_version=2))
    with catalog.transaction():
        catalog.execute(
            "UPDATE reference.subregion SET region_id = %s, code = '420', "
            "code_snapshot_version = 2 WHERE subregion_id = %s",
            [AFRICA, LATAM],
        )
        catalog.execute(
            "UPDATE reference.region SET code = '020', code_snapshot_version = 2 "
            "WHERE region_id = %s",
            [AMERICAS],
        )
        catalog.execute("UPDATE reference.region_locale SET name = 'Las Américas'")
        catalog.execute(
            "UPDATE reference.region SET status = 'inactive', replacement_region_id = %s "
            "WHERE region_id = %s",
            [AFRICA, AMERICAS],
        )


# --- privilegios (RNF-4) ------------------------------------------------------------------------


def as_role(conn: psycopg.Connection, role: str) -> Iterator[None]:
    conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
    try:
        yield
    finally:
        conn.execute("RESET ROLE")


@pytest.mark.parametrize("role", ["anon", "authenticated", "public"])
def test_api_roles_and_public_have_no_privileges_on_the_new_tables(
    conn: psycopg.Connection, role: str
) -> None:
    for table in COLUMNS:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            granted = conn.execute(
                "SELECT has_table_privilege(%s, %s, %s)", [role, f"reference.{table}", privilege]
            ).fetchone()
            assert granted == (False,), (role, table, privilege)


def test_reader_can_select_but_not_write(catalog: psycopg.Connection) -> None:
    for _ in as_role(catalog, "reference_reader"):
        for table in COLUMNS:
            catalog.execute(sql.SQL("SELECT * FROM reference.{}").format(sql.Identifier(table)))
        with rejected(errors.InsufficientPrivilege):
            insert(catalog, "region", region_row(code="142"))
        with rejected(errors.InsufficientPrivilege):
            catalog.execute("UPDATE reference.region SET status = 'inactive'")
        with rejected(errors.InsufficientPrivilege):
            catalog.execute("UPDATE reference.region_locale SET name = 'z'")


def test_loader_can_load_but_not_alter_identity_or_history(base: psycopg.Connection) -> None:
    for _ in as_role(base, "reference_loader"):
        insert(base, "region_snapshot", region_snapshot_row(snapshot_version=2))
        insert(base, "region", region_row(region_id=AMERICAS))
        insert(base, "subregion", subregion_row(subregion_id=LATAM))
        insert(base, "region_locale", {"region_id": AMERICAS, "locale_id": LOCALE_ID, "name": "x"})
        base.execute("UPDATE reference.region SET code = '020', code_snapshot_version = 2")
        base.execute("UPDATE reference.subregion SET status = 'inactive'")
        base.execute("UPDATE reference.region_locale SET name = 'y'")
        insert(
            base,
            "subregion_recoding",
            {
                "subregion_id": LATAM,
                "snapshot_version": 2,
                "previous_code": "419",
                "new_code": "420",
                "provenance": "{}",
            },
        )
        with rejected(errors.InsufficientPrivilege):
            base.execute("UPDATE reference.region SET first_snapshot_version = 2")
        with rejected(errors.InsufficientPrivilege):
            base.execute("UPDATE reference.region_locale SET locale_id = %s", [LOCALE_ID])
        with rejected(errors.InsufficientPrivilege):
            base.execute("UPDATE reference.region_snapshot SET content_digest = 'x'")
        with rejected(errors.InsufficientPrivilege):
            base.execute("DELETE FROM reference.region_locale")
        with rejected(errors.InsufficientPrivilege):
            base.execute("TRUNCATE reference.subregion_recoding")


# --- downgrade ----------------------------------------------------------------------------------


def test_downgrade_to_0001_removes_only_the_regions_tables(database_url: str) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "0001")
    with psycopg.connect(database_url, autocommit=True) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'reference'"
            ).fetchall()
        }
        functions = conn.execute(
            "SELECT count(*) FROM pg_proc WHERE pronamespace = 'reference'::regnamespace "
            "AND proname LIKE '%%region%%'"
        ).fetchone()
    assert tables == {"locale", "locale_alias", "locale_snapshot", "alembic_version"}
    assert functions == (0,)
    command.upgrade(config, "head")
