"""T2: migración 0005 (Units: magnitudes, unidades, asociaciones), SQL directo (CA-9)."""

import uuid
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from psycopg import errors, sql

from tests.conftest import alembic_config
from tests.integration.test_migration_0001 import columns_of, insert, locale_row, rejected
from tests.integration.test_migration_0001 import snapshot_row as locale_snapshot_row
from tests.integration.test_migration_0002 import TRUNCATE_REJECTIONS, as_role

COLUMNS = {
    "unit_snapshot": [
        "snapshot_version",
        "content_digest",
        "locale_snapshot_version",
        "required_locales_version",
        "ucum_table_version",
        "provenance",
        "artifact",
        "incorporated_at",
    ],
    "quantity_kind": [
        "quantity_kind_id",
        "code",
        "conversion_type",
        "reference_unit_id",
        "status",
        "first_snapshot_version",
        "last_changed_snapshot_version",
    ],
    "unit": [
        "unit_id",
        "ucum_code",
        "unece_code",
        "symbol",
        "status",
        "first_snapshot_version",
        "last_changed_snapshot_version",
    ],
    "quantity_kind_unit": [
        "quantity_kind_id",
        "unit_id",
        "factor",
        "offset",
        "status",
        "first_snapshot_version",
        "last_changed_snapshot_version",
    ],
    "quantity_kind_locale": ["quantity_kind_id", "locale_id", "name"],
    "unit_locale": ["unit_id", "locale_id", "name", "plural"],
}
NULLABLE = {"ucum_code", "unece_code", "plural", "incorporated_at"}
HISTORY = ("unit_snapshot",)
CATALOG = ("quantity_kind", "unit", "quantity_kind_unit", "quantity_kind_locale", "unit_locale")

EN = str(uuid.uuid4())
ES = str(uuid.uuid4())
KIND_ASSOCIATION = "UPDATE reference.quantity_kind_unit SET status = 'inactive'"


class Ids:
    kg = str(uuid.uuid4())
    g = str(uuid.uuid4())
    kelvin = str(uuid.uuid4())
    celsius = str(uuid.uuid4())
    mass = str(uuid.uuid4())
    temperature = str(uuid.uuid4())
    temperature_difference = str(uuid.uuid4())


def snapshot_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "snapshot_version": 1,
        "content_digest": "sha256:" + "e" * 64,
        "locale_snapshot_version": 1,
        "required_locales_version": 1,
        "ucum_table_version": "2.2",
        "provenance": "{}",
        "artifact": "{}",
    }
    return {**row, **overrides}


def unit_row(unit_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "unit_id": unit_id,
        "ucum_code": None,
        "unece_code": None,
        "symbol": "u",
        "status": "active",
        "first_snapshot_version": 1,
        "last_changed_snapshot_version": 1,
    }
    return {**row, **overrides}


def kind_row(kind_id: str, reference_unit_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "quantity_kind_id": kind_id,
        "code": "mass",
        "conversion_type": "linear",
        "reference_unit_id": reference_unit_id,
        "status": "active",
        "first_snapshot_version": 1,
        "last_changed_snapshot_version": 1,
    }
    return {**row, **overrides}


def association_row(kind_id: str, unit_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "quantity_kind_id": kind_id,
        "unit_id": unit_id,
        "factor": "1",
        "offset": "0",
        "status": "active",
        "first_snapshot_version": 1,
        "last_changed_snapshot_version": 1,
    }
    return {**row, **overrides}


def kind_name(kind_id: str, locale_id: str, name: str) -> dict[str, Any]:
    return {"quantity_kind_id": kind_id, "locale_id": locale_id, "name": name}


def unit_name(unit_id: str, locale_id: str, name: str, plural: str | None = None) -> dict[str, Any]:
    return {"unit_id": unit_id, "locale_id": locale_id, "name": name, "plural": plural}


def new_kind(
    conn: psycopg.Connection,
    kind_id: str,
    reference_unit_id: str,
    *,
    kind: dict[str, Any] | None = None,
    reference: dict[str, Any] | None = None,
) -> None:
    """Magnitud y su asociación de referencia (la FK de referencia se evalúa al commit)."""
    insert(conn, "quantity_kind", kind_row(kind_id, reference_unit_id, **(kind or {})))
    insert(
        conn,
        "quantity_kind_unit",
        association_row(kind_id, reference_unit_id, **(reference or {})),
    )


@pytest.fixture
def base(conn: psycopg.Connection) -> psycopg.Connection:
    insert(conn, "locale_snapshot", locale_snapshot_row())
    insert(conn, "locale", locale_row(locale_id=EN, code="en"))
    insert(conn, "locale", locale_row(locale_id=ES, code="es"))
    insert(conn, "unit_snapshot", snapshot_row())
    insert(conn, "unit_snapshot", snapshot_row(snapshot_version=2))
    return conn


@pytest.fixture
def catalog(base: psycopg.Connection) -> psycopg.Connection:
    """mass (linear), temperature (affine) y temperature_difference (linear)."""
    with base.transaction():
        insert(base, "unit", unit_row(Ids.kg, ucum_code="kg", unece_code="KGM", symbol="kg"))
        insert(base, "unit", unit_row(Ids.g, ucum_code="g", unece_code="GRM", symbol="g"))
        insert(base, "unit", unit_row(Ids.kelvin, ucum_code="K", unece_code="KEL", symbol="K"))
        insert(base, "unit", unit_row(Ids.celsius, ucum_code="Cel", unece_code="CEL", symbol="°C"))
        new_kind(base, Ids.mass, Ids.kg)
        insert(base, "quantity_kind_unit", association_row(Ids.mass, Ids.g, factor="0.001"))
        affine = {"code": "temperature", "conversion_type": "affine"}
        new_kind(base, Ids.temperature, Ids.kelvin, kind=affine)
        insert(
            base,
            "quantity_kind_unit",
            association_row(Ids.temperature, Ids.celsius, offset="273.15"),
        )
        difference = {"code": "temperature_difference"}
        new_kind(base, Ids.temperature_difference, Ids.kelvin, kind=difference)
        insert(base, "quantity_kind_unit", association_row(Ids.temperature_difference, Ids.celsius))
    return base


def count(conn: psycopg.Connection, table: str) -> int:
    row = conn.execute(
        sql.SQL("SELECT count(*) FROM reference.{}").format(sql.Identifier(table))
    ).fetchone()
    assert row is not None
    return int(row[0])


def update(
    conn: psycopg.Connection, table: str, column: str, value: Any, key: str, key_value: Any
) -> None:
    conn.execute(
        sql.SQL("UPDATE reference.{} SET {} = %s WHERE {} = %s").format(
            sql.Identifier(table), sql.Identifier(column), sql.Identifier(key)
        ),
        [value, key_value],
    )


def scalar(
    conn: psycopg.Connection, query: str | sql.SQL | sql.Composed, params: list[Any] | None = None
) -> Any:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


# --- estructura -------------------------------------------------------------------------------


def test_tables_have_exactly_the_planned_columns(conn: psycopg.Connection) -> None:
    for table, columns in COLUMNS.items():
        assert columns_of(conn, table) == columns, table


def test_no_tenant_and_no_legacy_state_columns(conn: psycopg.Connection) -> None:
    """RF-1, RF-9, CA-9: ni tenant, ni textos fuera de las localizaciones, ni otro estado."""
    forbidden = {
        "tenant_id",
        "organization_id",
        "name",
        "display_name",
        "description",
        "label",
        "plural",
        "is_active",
        "enabled",
        "state",
        "is_reference",
        "ratio",
    }
    for table in COLUMNS:
        columns = set(columns_of(conn, table))
        allowed = {"name", "plural"} if table in ("quantity_kind_locale", "unit_locale") else set()
        assert not (forbidden - allowed) & columns, table


def test_foreign_keys_point_only_to_units_tables_and_locale(conn: psycopg.Connection) -> None:
    """RNF-5: Units depende de Locale por identidades y de nadie más."""
    rows = conn.execute(
        "SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint "
        "WHERE contype = 'f' AND connamespace = 'reference'::regnamespace"
    ).fetchall()
    targets = {t for s, t in rows if s.removeprefix("reference.") in COLUMNS}
    assert targets == {
        "reference.unit_snapshot",
        "reference.quantity_kind",
        "reference.quantity_kind_unit",
        "reference.unit",
        "reference.locale",
        "reference.locale_snapshot",
    }


def test_earlier_catalogs_do_not_depend_on_units(conn: psycopg.Connection) -> None:
    """RNF-5: ninguna FK, trigger ni columna de 001-004 conoce a Units."""
    fks = conn.execute(
        "SELECT conrelid::regclass::text FROM pg_constraint "
        "WHERE contype = 'f' AND connamespace = 'reference'::regnamespace "
        "AND confrelid::regclass::text = ANY (%s)",
        [[f"reference.{table}" for table in COLUMNS]],
    ).fetchall()
    assert {s.removeprefix("reference.") for (s,) in fks} <= set(COLUMNS)
    dependent = conn.execute(
        "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE NOT t.tgisinternal AND c.relnamespace = 'reference'::regnamespace "
        "AND c.relname <> ALL (%s) AND pg_get_functiondef(t.tgfoid) ~* 'quantity_kind|uom_'",
        [list(COLUMNS)],
    ).fetchone()
    assert dependent == (0,)
    column_refs = conn.execute(
        "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'reference' "
        "AND table_name <> ALL (%s) AND column_name ~* 'quantity_kind|unit_id'",
        [list(COLUMNS)],
    ).fetchone()
    assert column_refs == (0,)


def test_reference_fk_and_kind_check_are_deferred_to_the_commit(conn: psycopg.Connection) -> None:
    fk = conn.execute(
        "SELECT condeferrable AND condeferred, confrelid::regclass::text FROM pg_constraint "
        "WHERE conrelid = 'reference.quantity_kind'::regclass AND contype = 'f' "
        "AND confrelid = 'reference.quantity_kind_unit'::regclass"
    ).fetchall()
    assert fk == [(True, "reference.quantity_kind_unit")]
    triggers = conn.execute(
        "SELECT tgrelid::regclass::text, tgdeferrable AND tginitdeferred FROM pg_trigger "
        "WHERE NOT tgisinternal AND tgname = 'uom_check_kind'"
    ).fetchall()
    assert {t for t, _ in triggers} == {
        "reference.quantity_kind",
        "reference.quantity_kind_unit",
        "reference.unit",
    }
    assert all(deferred for _, deferred in triggers)


def test_canonical_form_functions_exist_and_answer_directly(conn: psycopg.Connection) -> None:
    def decimal(value: str | None) -> bool:
        return bool(scalar(conn, "SELECT reference.uom_is_canonical_decimal(%s)", [value]))

    def factor(value: str | None) -> bool:
        return bool(scalar(conn, "SELECT reference.uom_is_canonical_factor(%s)", [value]))

    assert decimal("273.15") and decimal("0") and decimal("-1") and not decimal("-0")
    assert factor("5/9") and factor("0.45359237") and not factor("0") and not factor("1/2")
    assert not decimal(None) and not factor(None)


@pytest.mark.parametrize("table", list(COLUMNS))
def test_every_required_column_rejects_null(catalog: psycopg.Connection, table: str) -> None:
    rows: dict[str, dict[str, Any]] = {
        "unit_snapshot": snapshot_row(snapshot_version=9),
        "quantity_kind": kind_row(str(uuid.uuid4()), Ids.kg, code="length"),
        "unit": unit_row(str(uuid.uuid4())),
        "quantity_kind_unit": association_row(Ids.mass, Ids.celsius),
        "quantity_kind_locale": kind_name(Ids.mass, EN, "Mass"),
        "unit_locale": unit_name(Ids.kg, EN, "kilogram"),
    }
    for column in COLUMNS[table]:
        if column in NULLABLE:
            continue
        with catalog.transaction(), rejected(errors.NotNullViolation):
            insert(catalog, table, {**rows[table], column: None})


# --- códigos (RF-3, RF-4, RF-5) -----------------------------------------------------------------


def test_quantity_kind_code_is_unique_across_the_whole_catalog_including_inactive(
    catalog: psycopg.Connection,
) -> None:
    with catalog.transaction():
        catalog.execute(f"{KIND_ASSOCIATION} WHERE quantity_kind_id = %s", [Ids.mass])
        catalog.execute(
            "UPDATE reference.quantity_kind SET status = 'inactive' WHERE code = 'mass'"
        )
    with rejected(errors.UniqueViolation, "quantity_kind_code_unique"), catalog.transaction():
        new_kind(catalog, str(uuid.uuid4()), Ids.g, kind={"code": "mass"})


@pytest.mark.parametrize(
    "code", ["Mass", "1mass", "m", "a-b", "x" * 65, " mass", "mass ", "mäss", "", "a b"]
)
def test_quantity_kind_code_outside_format_is_rejected(
    catalog: psycopg.Connection, code: str
) -> None:
    with rejected(errors.CheckViolation, "quantity_kind_code_format"), catalog.transaction():
        new_kind(catalog, str(uuid.uuid4()), Ids.g, kind={"code": code})


@pytest.mark.parametrize("code", ["ab", "mass_per_area", "a" + "b" * 63, "x1_y2"])
def test_quantity_kind_code_inside_format_is_accepted(
    catalog: psycopg.Connection, code: str
) -> None:
    with catalog.transaction():
        new_kind(catalog, str(uuid.uuid4()), Ids.g, kind={"code": code})


@pytest.mark.parametrize("column", ["ucum_code", "unece_code"])
def test_unit_codes_are_unique_including_inactive(catalog: psycopg.Connection, column: str) -> None:
    catalog.execute(
        "UPDATE reference.unit SET status = 'inactive' WHERE unit_id = %s", [Ids.celsius]
    )
    active, inactive = ("kg", "Cel") if column == "ucum_code" else ("KGM", "CEL")
    with rejected(errors.UniqueViolation, f"unit_{column}_unique"):
        insert(catalog, "unit", unit_row(str(uuid.uuid4()), **{column: active}))
    with rejected(errors.UniqueViolation, f"unit_{column}_unique"):
        insert(catalog, "unit", unit_row(str(uuid.uuid4()), **{column: inactive}))


def test_many_units_may_have_no_codes(catalog: psycopg.Connection) -> None:
    for _ in range(3):
        insert(catalog, "unit", unit_row(str(uuid.uuid4())))


@pytest.mark.parametrize(
    "code", ["kg", "K", "KGMX", "K G", "KGÑ", "", "kgm", "A_B", " KG", "KG ", "K-1"]
)
def test_unece_code_outside_format_is_rejected(catalog: psycopg.Connection, code: str) -> None:
    with rejected(errors.CheckViolation, "unit_unece_code_format"):
        insert(catalog, "unit", unit_row(str(uuid.uuid4()), unece_code=code))


@pytest.mark.parametrize("code", ["ABC", "23", "H87", "NX", "M1", "B35", "P1"])
def test_unece_code_inside_format_is_accepted(catalog: psycopg.Connection, code: str) -> None:
    insert(catalog, "unit", unit_row(str(uuid.uuid4()), unece_code=code))


@pytest.mark.parametrize("code", ["", " kg", "kg ", "k g"])
def test_malformed_ucum_codes_are_rejected(catalog: psycopg.Connection, code: str) -> None:
    with rejected(errors.CheckViolation, "unit_ucum_code_format"):
        insert(catalog, "unit", unit_row(str(uuid.uuid4()), ucum_code=code))


@pytest.mark.parametrize(
    ("column", "first", "second"),
    [("ucum_code", "ha", "har"), ("unece_code", "HAR", "HA2")],
)
def test_a_null_code_can_be_completed_once_and_then_never_changes(
    catalog: psycopg.Connection, column: str, first: str, second: str
) -> None:
    unit_id = str(uuid.uuid4())
    insert(catalog, "unit", unit_row(unit_id))
    update(catalog, "unit", column, first, "unit_id", unit_id)
    with rejected(errors.RestrictViolation):
        update(catalog, "unit", column, second, "unit_id", unit_id)
    with rejected(errors.RestrictViolation):
        update(catalog, "unit", column, None, "unit_id", unit_id)
    update(catalog, "unit", column, first, "unit_id", unit_id)  # reescribir el mismo valor: no-op
    stored = scalar(
        catalog,
        sql.SQL("SELECT {} FROM reference.unit WHERE unit_id = %s").format(sql.Identifier(column)),
        [unit_id],
    )
    assert stored == first


# --- magnitud y referencia (RF-8) ---------------------------------------------------------------


def test_a_quantity_kind_without_a_reference_association_is_rejected_at_the_commit(
    catalog: psycopg.Connection,
) -> None:
    with rejected(errors.ForeignKeyViolation, "quantity_kind_reference_fk"), catalog.transaction():
        insert(catalog, "quantity_kind", kind_row(str(uuid.uuid4()), Ids.g, code="length"))


def test_the_reference_must_be_an_association_of_the_same_quantity_kind(
    catalog: psycopg.Connection,
) -> None:
    other_kind = str(uuid.uuid4())
    with rejected(errors.ForeignKeyViolation, "quantity_kind_reference_fk"), catalog.transaction():
        insert(catalog, "quantity_kind", kind_row(other_kind, Ids.kg, code="length"))
        insert(catalog, "quantity_kind_unit", association_row(other_kind, Ids.g))


def test_a_reference_unit_may_be_shared_by_several_quantity_kinds(
    catalog: psycopg.Connection,
) -> None:
    with catalog.transaction():
        new_kind(catalog, str(uuid.uuid4()), Ids.kg, kind={"code": "weight"})
    assert count(catalog, "quantity_kind") == 4


@pytest.mark.parametrize(
    ("factor", "offset"),
    [("2", "0"), ("1", "273.15"), ("0.5", "1"), ("5/9", "0"), ("1000", "0")],
)
def test_the_reference_association_must_have_factor_one_and_offset_zero(
    catalog: psycopg.Connection, factor: str, offset: str
) -> None:
    kind = {"code": "length", "conversion_type": "affine"}
    reference = {"factor": factor, "offset": offset}
    with rejected(errors.CheckViolation, "quantity_kind_reference_neutral"), catalog.transaction():
        new_kind(catalog, str(uuid.uuid4()), Ids.g, kind=kind, reference=reference)


def test_changing_the_reference_factor_or_offset_later_is_rejected(
    catalog: psycopg.Connection,
) -> None:
    with rejected(errors.CheckViolation, "quantity_kind_reference_neutral"):
        catalog.execute(
            "UPDATE reference.quantity_kind_unit SET factor = '2' "
            "WHERE quantity_kind_id = %s AND unit_id = %s",
            [Ids.mass, Ids.kg],
        )
    with rejected(errors.CheckViolation, "quantity_kind_reference_neutral"):
        catalog.execute(
            "UPDATE reference.quantity_kind_unit SET \"offset\" = '1' "
            "WHERE quantity_kind_id = %s AND unit_id = %s",
            [Ids.temperature, Ids.kelvin],
        )


@pytest.mark.parametrize("where", ["association", "unit"])
def test_an_active_quantity_kind_needs_an_active_reference_association_and_unit(
    catalog: psycopg.Connection, where: str
) -> None:
    with rejected(errors.CheckViolation, "quantity_kind_active_requires_active_reference"):
        if where == "association":
            catalog.execute(
                f"{KIND_ASSOCIATION} WHERE quantity_kind_id = %s AND unit_id = %s",
                [Ids.mass, Ids.kg],
            )
        else:
            catalog.execute(
                "UPDATE reference.unit SET status = 'inactive' WHERE unit_id = %s", [Ids.kg]
            )
    stored = scalar(catalog, "SELECT status FROM reference.unit WHERE unit_id = %s", [Ids.kg])
    assert stored == "active"


def test_a_new_active_quantity_kind_with_an_inactive_reference_is_rejected(
    catalog: psycopg.Connection,
) -> None:
    with rejected(errors.CheckViolation, "quantity_kind_active_requires_active_reference"):
        with catalog.transaction():
            new_kind(
                catalog,
                str(uuid.uuid4()),
                Ids.g,
                kind={"code": "length"},
                reference={"status": "inactive"},
            )


def test_an_inactive_quantity_kind_may_keep_an_inactive_reference(
    catalog: psycopg.Connection,
) -> None:
    with catalog.transaction():
        new_kind(
            catalog,
            str(uuid.uuid4()),
            Ids.g,
            kind={"code": "length", "status": "inactive"},
            reference={"status": "inactive"},
        )
    catalog.execute("UPDATE reference.unit SET status = 'inactive' WHERE unit_id = %s", [Ids.g])


def test_retiring_a_quantity_kind_and_its_reference_in_one_transaction_is_accepted(
    catalog: psycopg.Connection,
) -> None:
    with catalog.transaction():
        catalog.execute(f"{KIND_ASSOCIATION} WHERE quantity_kind_id = %s", [Ids.mass])
        catalog.execute(
            "UPDATE reference.unit SET status = 'inactive' WHERE unit_id = %s", [Ids.kg]
        )
        catalog.execute(
            "UPDATE reference.quantity_kind SET status = 'inactive' WHERE quantity_kind_id = %s",
            [Ids.mass],
        )
    stored = scalar(
        catalog,
        "SELECT status FROM reference.quantity_kind WHERE quantity_kind_id = %s",
        [Ids.mass],
    )
    assert stored == "inactive"


def test_reactivating_a_kind_needs_an_active_reference(catalog: psycopg.Connection) -> None:
    with catalog.transaction():
        catalog.execute(f"{KIND_ASSOCIATION} WHERE quantity_kind_id = %s", [Ids.mass])
        catalog.execute(
            "UPDATE reference.quantity_kind SET status = 'inactive' WHERE quantity_kind_id = %s",
            [Ids.mass],
        )
    with rejected(errors.CheckViolation, "quantity_kind_active_requires_active_reference"):
        update(catalog, "quantity_kind", "status", "active", "quantity_kind_id", Ids.mass)


# --- linear / affine (RF-12) --------------------------------------------------------------------


@pytest.mark.parametrize("offset", ["1", "273.15", "-1", "0.5"])
def test_a_linear_quantity_kind_rejects_a_non_zero_offset(
    catalog: psycopg.Connection, offset: str
) -> None:
    with rejected(errors.CheckViolation, "quantity_kind_unit_linear_offset"):
        insert(catalog, "quantity_kind_unit", association_row(Ids.mass, Ids.celsius, offset=offset))
    with rejected(errors.CheckViolation, "quantity_kind_unit_linear_offset"):
        update(catalog, "quantity_kind_unit", "offset", offset, "unit_id", Ids.g)


def test_an_affine_quantity_kind_accepts_a_non_zero_offset(catalog: psycopg.Connection) -> None:
    stored = scalar(
        catalog,
        'SELECT "offset" FROM reference.quantity_kind_unit '
        "WHERE quantity_kind_id = %s AND unit_id = %s",
        [Ids.temperature, Ids.celsius],
    )
    assert stored == "273.15"
    catalog.execute(
        "UPDATE reference.quantity_kind_unit SET \"offset\" = '459.67', factor = '5/9' "
        "WHERE quantity_kind_id = %s AND unit_id = %s",
        [Ids.temperature, Ids.celsius],
    )


def test_conversion_type_must_be_linear_or_affine(catalog: psycopg.Connection) -> None:
    kind = {"code": "length", "conversion_type": "logarithmic"}
    with rejected(errors.CheckViolation, "quantity_kind_conversion_type_valid"):
        with catalog.transaction():
            new_kind(catalog, str(uuid.uuid4()), Ids.g, kind=kind)


def test_the_same_unit_can_have_different_offsets_in_different_quantity_kinds(
    catalog: psycopg.Connection,
) -> None:
    """D-8: °C es afín en temperature (desplazamiento 273.15) y lineal en el intervalo."""
    rows: dict[str, str] = dict(
        catalog.execute(
            'SELECT quantity_kind_id::text, "offset" FROM reference.quantity_kind_unit '
            "WHERE unit_id = %s",
            [Ids.celsius],
        ).fetchall()
    )
    assert rows == {Ids.temperature: "273.15", Ids.temperature_difference: "0"}


# --- factores y desplazamientos canónicos (RF-13) ------------------------------------------------


@pytest.mark.parametrize(
    "factor",
    [
        "1.0",
        "01",
        "+1",
        "2/4",
        "1/2",
        "1/1",
        "0",
        "-1",
        "1e3",
        "",
        " 1",
        "1 ",
        "1/0",
        "0/5",
        "5/9 ",
        "1,5",
        ".5",
        "1.",
        "0.0",
        "-0.5",
        "3/1",
        "10/4",
        "1/20",
        "1/5",
        "9/6",
        "1/-3",
        "-1/3",
        "1/03",
        "0.50",
        "1/2/3",
    ],
)
def test_non_canonical_factors_are_rejected(catalog: psycopg.Connection, factor: str) -> None:
    row = association_row(Ids.temperature_difference, Ids.g, factor=factor)
    with rejected(errors.CheckViolation, "quantity_kind_unit_factor_canonical"):
        insert(catalog, "quantity_kind_unit", row)


@pytest.mark.parametrize(
    "factor",
    [
        "1",
        "0.45359237",
        "5/9",
        "5/18",
        "1000",
        "0.000001",
        "1/3",
        "7/12",
        "0.5",
        "123456789.123456",
    ],
)
def test_canonical_factors_are_accepted(catalog: psycopg.Connection, factor: str) -> None:
    insert(
        catalog,
        "quantity_kind_unit",
        association_row(Ids.temperature_difference, Ids.g, factor=factor),
    )
    stored = scalar(
        catalog,
        "SELECT factor FROM reference.quantity_kind_unit "
        "WHERE quantity_kind_id = %s AND unit_id = %s",
        [Ids.temperature_difference, Ids.g],
    )
    assert stored == factor


@pytest.mark.parametrize(
    "offset",
    ["-0", "0.0", "+1", "01", "1e3", "", "1.50", ".5", "273.150", " 0", "5/9", "1.", "--1", "- 1"],
)
def test_non_canonical_offsets_are_rejected(catalog: psycopg.Connection, offset: str) -> None:
    with rejected(errors.CheckViolation, "quantity_kind_unit_offset_canonical"):
        insert(
            catalog, "quantity_kind_unit", association_row(Ids.temperature, Ids.g, offset=offset)
        )


@pytest.mark.parametrize("offset", ["0", "273.15", "459.67", "-273.15", "-1", "10", "0.001"])
def test_canonical_offsets_are_accepted(catalog: psycopg.Connection, offset: str) -> None:
    insert(catalog, "quantity_kind_unit", association_row(Ids.temperature, Ids.g, offset=offset))


# --- estado, símbolo y nombres ------------------------------------------------------------------


def test_invalid_status_is_rejected(catalog: psycopg.Connection) -> None:
    with rejected(errors.CheckViolation, "unit_status_valid"):
        insert(catalog, "unit", unit_row(str(uuid.uuid4()), status="retired"))
    with rejected(errors.CheckViolation, "quantity_kind_unit_status_valid"):
        insert(
            catalog,
            "quantity_kind_unit",
            association_row(Ids.mass, Ids.celsius, status="INACTIVE"),
        )
    with rejected(errors.CheckViolation, "quantity_kind_status_valid"):
        update(catalog, "quantity_kind", "status", "deprecated", "quantity_kind_id", Ids.mass)


@pytest.mark.parametrize("symbol", ["", " ", " kg", "kg ", "\tkg", "kg\n"])
def test_untrimmed_or_empty_symbols_are_rejected(catalog: psycopg.Connection, symbol: str) -> None:
    with rejected(errors.CheckViolation, "unit_symbol_trimmed"):
        insert(catalog, "unit", unit_row(str(uuid.uuid4()), symbol=symbol))


@pytest.mark.parametrize("symbol", ["kg", "m²", "°C", "‰", "L/ha", "1", "k g"])
def test_symbols_are_stored_verbatim(catalog: psycopg.Connection, symbol: str) -> None:
    unit_id = str(uuid.uuid4())
    insert(catalog, "unit", unit_row(unit_id, symbol=symbol))
    stored = scalar(catalog, "SELECT symbol FROM reference.unit WHERE unit_id = %s", [unit_id])
    assert stored == symbol


def test_localizations_are_unique_per_pair_and_reference_their_owners(
    catalog: psycopg.Connection,
) -> None:
    other = str(uuid.uuid4())
    insert(catalog, "quantity_kind_locale", kind_name(Ids.mass, EN, "Mass"))
    insert(catalog, "quantity_kind_locale", kind_name(Ids.mass, ES, "Masa"))
    with rejected(errors.UniqueViolation, "quantity_kind_locale_pkey"):
        insert(catalog, "quantity_kind_locale", kind_name(Ids.mass, EN, "Weight"))
    with rejected(errors.ForeignKeyViolation, "quantity_kind_locale_quantity_kind_fk"):
        insert(catalog, "quantity_kind_locale", kind_name(other, EN, "x"))
    with rejected(errors.ForeignKeyViolation, "quantity_kind_locale_locale_fk"):
        insert(catalog, "quantity_kind_locale", kind_name(Ids.mass, other, "x"))
    insert(catalog, "unit_locale", unit_name(Ids.kg, EN, "kilogram", "kilograms"))
    insert(catalog, "unit_locale", unit_name(Ids.kg, ES, "kilogramo"))
    with rejected(errors.UniqueViolation, "unit_locale_pkey"):
        insert(catalog, "unit_locale", unit_name(Ids.kg, EN, "k"))
    with rejected(errors.ForeignKeyViolation, "unit_locale_unit_fk"):
        insert(catalog, "unit_locale", unit_name(other, EN, "k"))
    with rejected(errors.ForeignKeyViolation, "unit_locale_locale_fk"):
        insert(catalog, "unit_locale", unit_name(Ids.kg, other, "k"))


@pytest.mark.parametrize("name", ["", " x", "x ", "\tx", "x\n"])
def test_untrimmed_or_empty_names_and_plurals_are_rejected(
    catalog: psycopg.Connection, name: str
) -> None:
    with rejected(errors.CheckViolation, "quantity_kind_locale_name_trimmed"):
        insert(catalog, "quantity_kind_locale", kind_name(Ids.mass, EN, name))
    with rejected(errors.CheckViolation, "unit_locale_name_trimmed"):
        insert(catalog, "unit_locale", unit_name(Ids.kg, EN, name))
    with rejected(errors.CheckViolation, "unit_locale_plural_trimmed"):
        insert(catalog, "unit_locale", unit_name(Ids.kg, EN, "ok", name))


# --- identidad inmutable (RF-2, RF-5) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("quantity_kind_id", str(uuid.uuid4())),
        ("code", "mass2"),
        ("conversion_type", "affine"),
        ("reference_unit_id", Ids.g),
        ("first_snapshot_version", 2),
    ],
)
def test_quantity_kind_identity_code_type_and_reference_are_immutable(
    catalog: psycopg.Connection, column: str, value: Any
) -> None:
    with rejected(errors.RestrictViolation):
        update(catalog, "quantity_kind", column, value, "quantity_kind_id", Ids.mass)


@pytest.mark.parametrize(
    ("column", "value"), [("unit_id", str(uuid.uuid4())), ("first_snapshot_version", 2)]
)
def test_unit_identity_is_immutable(catalog: psycopg.Connection, column: str, value: Any) -> None:
    with rejected(errors.RestrictViolation):
        update(catalog, "unit", column, value, "unit_id", Ids.kg)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("quantity_kind_id", Ids.temperature),
        ("unit_id", Ids.celsius),
        ("first_snapshot_version", 2),
    ],
)
def test_association_pair_is_immutable(
    catalog: psycopg.Connection, column: str, value: Any
) -> None:
    with rejected(errors.RestrictViolation):
        update(catalog, "quantity_kind_unit", column, value, "unit_id", Ids.g)


def test_localization_pairs_are_immutable_but_texts_can_change(
    catalog: psycopg.Connection,
) -> None:
    insert(catalog, "quantity_kind_locale", kind_name(Ids.mass, EN, "Mass"))
    insert(catalog, "unit_locale", unit_name(Ids.kg, EN, "kilogram"))
    with rejected(errors.RestrictViolation):
        update(catalog, "quantity_kind_locale", "locale_id", ES, "quantity_kind_id", Ids.mass)
    with rejected(errors.RestrictViolation):
        update(
            catalog, "quantity_kind_locale", "quantity_kind_id", Ids.temperature, "locale_id", EN
        )
    with rejected(errors.RestrictViolation):
        update(catalog, "unit_locale", "locale_id", ES, "unit_id", Ids.kg)
    with rejected(errors.RestrictViolation):
        update(catalog, "unit_locale", "unit_id", Ids.g, "locale_id", EN)
    update(catalog, "quantity_kind_locale", "name", "Mass (SI)", "quantity_kind_id", Ids.mass)
    update(catalog, "unit_locale", "plural", "kilograms", "unit_id", Ids.kg)
    update(catalog, "unit_locale", "name", "kilo", "unit_id", Ids.kg)


def test_mutable_columns_can_change(catalog: psycopg.Connection) -> None:
    catalog.execute(
        "UPDATE reference.unit SET symbol = 'G', status = 'inactive', "
        "last_changed_snapshot_version = 2 WHERE unit_id = %s",
        [Ids.g],
    )
    catalog.execute(
        "UPDATE reference.quantity_kind_unit SET factor = '0.002', status = 'inactive', "
        "last_changed_snapshot_version = 2 WHERE unit_id = %s",
        [Ids.g],
    )
    catalog.execute(
        "UPDATE reference.quantity_kind SET last_changed_snapshot_version = 2 "
        "WHERE quantity_kind_id = %s",
        [Ids.mass],
    )


# --- sin borrado ni vaciado (RF-7) ---------------------------------------------------------------


@pytest.mark.parametrize("table", CATALOG)
def test_published_catalog_rows_are_never_deleted_or_truncated(
    catalog: psycopg.Connection, table: str
) -> None:
    insert(catalog, "quantity_kind_locale", kind_name(Ids.mass, EN, "Mass"))
    insert(catalog, "unit_locale", unit_name(Ids.kg, EN, "kilogram"))
    with rejected(errors.RestrictViolation):
        catalog.execute(sql.SQL("DELETE FROM reference.{}").format(sql.Identifier(table)))
    with pytest.raises(TRUNCATE_REJECTIONS):
        catalog.execute(sql.SQL("TRUNCATE reference.{}").format(sql.Identifier(table)))
    with rejected(errors.RestrictViolation):
        catalog.execute(sql.SQL("TRUNCATE reference.{} CASCADE").format(sql.Identifier(table)))
    assert count(catalog, table) >= 1


@pytest.mark.parametrize("table", HISTORY)
def test_snapshot_history_is_immutable(catalog: psycopg.Connection, table: str) -> None:
    with rejected(errors.RestrictViolation):
        catalog.execute(
            sql.SQL("UPDATE reference.{} SET content_digest = 'sha256:x'").format(
                sql.Identifier(table)
            )
        )
    with rejected(errors.RestrictViolation):
        catalog.execute(sql.SQL("DELETE FROM reference.{}").format(sql.Identifier(table)))
    with pytest.raises(TRUNCATE_REJECTIONS):
        catalog.execute(sql.SQL("TRUNCATE reference.{}").format(sql.Identifier(table)))


def test_snapshot_constraints(base: psycopg.Connection) -> None:
    with rejected(errors.CheckViolation, "unit_snapshot_version_positive"):
        insert(base, "unit_snapshot", snapshot_row(snapshot_version=0))
    with rejected(errors.CheckViolation, "unit_snapshot_required_locales_version_positive"):
        insert(base, "unit_snapshot", snapshot_row(snapshot_version=3, required_locales_version=0))
    with rejected(errors.ForeignKeyViolation, "unit_snapshot_locale_snapshot_fk"):
        insert(base, "unit_snapshot", snapshot_row(snapshot_version=3, locale_snapshot_version=9))
    with rejected(errors.UniqueViolation, "unit_snapshot_pkey"):
        insert(base, "unit_snapshot", snapshot_row())
    with rejected(errors.ForeignKeyViolation):
        insert(base, "unit", unit_row(str(uuid.uuid4()), first_snapshot_version=99))


# --- privilegios (RNF-3) -------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["anon", "authenticated", "public"])
def test_api_roles_and_public_have_no_privileges_on_the_new_objects(
    conn: psycopg.Connection, role: str
) -> None:
    for table in COLUMNS:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            granted = conn.execute(
                "SELECT has_table_privilege(%s, %s, %s)", [role, f"reference.{table}", privilege]
            ).fetchone()
            assert granted == (False,), (role, table, privilege)


def test_reader_can_only_select(catalog: psycopg.Connection) -> None:
    for _ in as_role(catalog, "reference_reader"):
        for table in COLUMNS:
            catalog.execute(sql.SQL("SELECT 1 FROM reference.{}").format(sql.Identifier(table)))
        for statement in (
            "INSERT INTO reference.unit_locale (unit_id, locale_id, name) "
            "VALUES (gen_random_uuid(), gen_random_uuid(), 'x')",
            "UPDATE reference.unit SET status = 'inactive'",
            "DELETE FROM reference.quantity_kind_unit",
            "TRUNCATE reference.quantity_kind",
        ):
            with pytest.raises(errors.InsufficientPrivilege):
                catalog.execute(statement)


def test_loader_inserts_and_updates_only_the_mutable_columns(catalog: psycopg.Connection) -> None:
    unit_id = str(uuid.uuid4())
    for _ in as_role(catalog, "reference_loader"):
        insert(catalog, "unit", unit_row(unit_id))
        insert(catalog, "unit_locale", unit_name(Ids.kg, EN, "kilogram"))
        insert(catalog, "quantity_kind_locale", kind_name(Ids.mass, EN, "Mass"))
        catalog.execute("UPDATE reference.unit_locale SET name = 'kg', plural = 'kgs'")
        catalog.execute("UPDATE reference.quantity_kind_locale SET name = 'M'")
        catalog.execute(
            "UPDATE reference.unit SET symbol = 'x', status = 'inactive', ucum_code = 'xx', "
            "unece_code = 'XX', last_changed_snapshot_version = 2 WHERE unit_id = %s",
            [unit_id],
        )
        catalog.execute(
            "UPDATE reference.quantity_kind_unit SET factor = '0.002', \"offset\" = '0', "
            "status = 'inactive', last_changed_snapshot_version = 2 WHERE unit_id = %s",
            [Ids.g],
        )
        catalog.execute(
            "UPDATE reference.quantity_kind SET last_changed_snapshot_version = 2, status = status"
        )
        for statement in (
            "UPDATE reference.quantity_kind SET code = 'x'",
            "UPDATE reference.quantity_kind SET conversion_type = 'affine'",
            "UPDATE reference.quantity_kind SET reference_unit_id = reference_unit_id",
            "UPDATE reference.unit SET unit_id = unit_id",
            "UPDATE reference.quantity_kind_unit SET unit_id = unit_id",
            "UPDATE reference.quantity_kind_unit SET quantity_kind_id = quantity_kind_id",
            "UPDATE reference.unit SET first_snapshot_version = 1",
            "UPDATE reference.unit_snapshot SET content_digest = 'x'",
            "DELETE FROM reference.unit",
            "TRUNCATE reference.unit",
        ):
            with pytest.raises(errors.InsufficientPrivilege):
                catalog.execute(statement)


# --- upgrade / downgrade ------------------------------------------------------------------------


def earlier_objects(conn: psycopg.Connection) -> dict[str, Any]:
    """Todo lo que no es de Units: columnas, funciones, constraints y triggers."""
    return {
        "columns": conn.execute(
            "SELECT table_name, array_agg(column_name::text ORDER BY ordinal_position) "
            "FROM information_schema.columns WHERE table_schema = 'reference' "
            "AND table_name !~ '^(unit|quantity_kind)' GROUP BY table_name ORDER BY table_name"
        ).fetchall(),
        "functions": conn.execute(
            "SELECT proname FROM pg_proc WHERE pronamespace = 'reference'::regnamespace "
            "AND proname !~ '^uom_' ORDER BY proname"
        ).fetchall(),
        "constraints": conn.execute(
            "SELECT conname FROM pg_constraint WHERE connamespace = 'reference'::regnamespace "
            "AND conrelid::regclass::text !~ 'unit|quantity_kind' ORDER BY conname"
        ).fetchall(),
        "triggers": conn.execute(
            "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT tgisinternal AND c.relnamespace = 'reference'::regnamespace "
            "AND c.relname !~ 'unit|quantity_kind' ORDER BY tgname"
        ).fetchall(),
    }


def test_downgrade_to_0004_removes_only_the_units_objects(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        before = earlier_objects(conn)
    config = alembic_config(database_url)
    command.downgrade(config, "0004")
    with psycopg.connect(database_url, autocommit=True) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'reference'"
            ).fetchall()
        }
        leftovers = conn.execute(
            "SELECT count(*) FROM pg_proc WHERE pronamespace = 'reference'::regnamespace "
            "AND proname ~ '^uom_'"
        ).fetchone()
        after = earlier_objects(conn)
    assert tables.isdisjoint(COLUMNS)
    assert {"locale", "region", "country", "currency", "country_currency"} <= tables
    assert leftovers == (0,)
    assert after == before  # 0001–0004 intactos
    command.upgrade(config, "head")
    with psycopg.connect(database_url, autocommit=True) as conn:
        assert columns_of(conn, "quantity_kind_unit") == COLUMNS["quantity_kind_unit"]
        assert earlier_objects(conn) == before


def test_migration_0005_follows_0004() -> None:
    script = ScriptDirectory.from_config(alembic_config("postgresql://x/y"))
    revision = script.get_revision("0005")
    assert revision is not None and revision.down_revision == "0004"
