"""T2: migración 0004 (Currency y CountryCurrency temporal), probada con SQL directo."""

import threading
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

import psycopg
import pytest
from alembic import command
from psycopg import errors, sql

from tests.conftest import alembic_config
from tests.integration.test_migration_0001 import columns_of, insert, locale_row, rejected
from tests.integration.test_migration_0001 import snapshot_row as locale_snapshot_row
from tests.integration.test_migration_0002 import (
    TRUNCATE_REJECTIONS,
    as_role,
    region_snapshot_row,
)
from tests.integration.test_migration_0003 import country_row, country_snapshot_row

COLUMNS = {
    "currency_snapshot": [
        "snapshot_version",
        "content_digest",
        "locale_snapshot_version",
        "country_snapshot_version",
        "country_current_snapshot_version",
        "required_locales_version",
        "provenance",
        "artifact",
        "incorporated_at",
    ],
    "currency": [
        "currency_id",
        "alphabetic_code",
        "numeric_code",
        "minor_units",
        "fund_code",
        "status",
        "replacement_currency_ids",
        "first_snapshot_version",
        "last_changed_snapshot_version",
    ],
    "currency_locale": ["currency_id", "locale_id", "name"],
    "country_currency": [
        "country_currency_id",
        "country_id",
        "currency_id",
        "status",
        "valid_from",
        "valid_to",
        "validity",
        "first_snapshot_version",
        "last_changed_snapshot_version",
    ],
}
NULLABLE = {"minor_units", "valid_from", "valid_to", "incorporated_at"}
GENERATED = {"validity"}
HISTORY = ("currency_snapshot",)
CATALOG = ("currency", "currency_locale", "country_currency")

EN = str(uuid.uuid4())
ES = str(uuid.uuid4())
HR = str(uuid.uuid4())
PA = str(uuid.uuid4())
AQ = str(uuid.uuid4())
D = date


def currency_snapshot_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "snapshot_version": 1,
        "content_digest": "sha256:" + "d" * 64,
        "locale_snapshot_version": 1,
        "country_snapshot_version": 1,
        "country_current_snapshot_version": 1,
        "required_locales_version": 1,
        "provenance": "{}",
        "artifact": "{}",
    }
    return {**row, **overrides}


def currency_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "currency_id": str(uuid.uuid4()),
        "alphabetic_code": "ARS",
        "numeric_code": "032",
        "minor_units": 2,
        "fund_code": False,
        "status": "active",
        "replacement_currency_ids": [],
        "first_snapshot_version": 1,
        "last_changed_snapshot_version": 1,
    }
    return {**row, **overrides}


def association_row(country_id: str, currency_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "country_currency_id": str(uuid.uuid4()),
        "country_id": country_id,
        "currency_id": currency_id,
        "status": "active",
        "valid_from": None,
        "valid_to": None,
        "first_snapshot_version": 1,
        "last_changed_snapshot_version": 1,
    }
    return {**row, **overrides}


def ascending(*ids: str) -> list[str]:
    return sorted(ids)


@pytest.fixture
def base(conn: psycopg.Connection) -> psycopg.Connection:
    """Locale (en, es), Countries (HR, PA, AQ) y el primer snapshot de Currency."""
    insert(conn, "locale_snapshot", locale_snapshot_row())
    insert(conn, "locale", locale_row(locale_id=EN, code="en"))
    insert(conn, "locale", locale_row(locale_id=ES, code="es"))
    insert(conn, "region_snapshot", region_snapshot_row())
    insert(conn, "country_snapshot", country_snapshot_row())
    no_class: dict[str, Any] = {"region_id": None, "subregion_id": None, "calling_code": None}
    insert(
        conn,
        "country",
        country_row(country_id=HR, alpha2="HR", alpha3="HRV", numeric_code="191", **no_class),
    )
    insert(
        conn,
        "country",
        country_row(country_id=PA, alpha2="PA", alpha3="PAN", numeric_code="591", **no_class),
    )
    insert(
        conn,
        "country",
        country_row(country_id=AQ, alpha2="AQ", alpha3="ATA", numeric_code="010", **no_class),
    )
    insert(conn, "currency_snapshot", currency_snapshot_row())
    return conn


@pytest.fixture
def catalog(base: psycopg.Connection) -> psycopg.Connection:
    """ARS, USD, HRK (inactive), EUR; nombres de ARS; asociaciones de HR y PA."""
    insert(base, "currency_snapshot", currency_snapshot_row(snapshot_version=2))
    return base


class Ids:
    ars = str(uuid.uuid4())
    usd = str(uuid.uuid4())
    eur = str(uuid.uuid4())
    hrk = str(uuid.uuid4())
    pab = str(uuid.uuid4())


@pytest.fixture
def money(catalog: psycopg.Connection) -> psycopg.Connection:
    insert(catalog, "currency", currency_row(currency_id=Ids.ars))
    insert(
        catalog,
        "currency",
        currency_row(currency_id=Ids.usd, alphabetic_code="USD", numeric_code="840"),
    )
    insert(
        catalog,
        "currency",
        currency_row(currency_id=Ids.eur, alphabetic_code="EUR", numeric_code="978"),
    )
    insert(
        catalog,
        "currency",
        currency_row(currency_id=Ids.pab, alphabetic_code="PAB", numeric_code="590"),
    )
    insert(
        catalog,
        "currency",
        currency_row(
            currency_id=Ids.hrk,
            alphabetic_code="HRK",
            numeric_code="191",
            status="inactive",
            replacement_currency_ids=[Ids.eur],
        ),
    )
    return catalog


def count(conn: psycopg.Connection, table: str) -> int:
    row = conn.execute(
        sql.SQL("SELECT count(*) FROM reference.{}").format(sql.Identifier(table))
    ).fetchone()
    assert row is not None
    return int(row[0])


# --- estructura -------------------------------------------------------------------------------


def test_tables_have_exactly_the_planned_columns(conn: psycopg.Connection) -> None:
    for table, columns in COLUMNS.items():
        assert columns_of(conn, table) == columns, table


def test_no_tenant_no_text_in_currency_and_no_legacy_state_columns(
    conn: psycopg.Connection,
) -> None:
    """RF-1, RF-9, D-4, D-11, CA-2: ni tenant, ni textos, ni símbolos, ni variantes de `status`."""
    forbidden = {
        "tenant_id",
        "organization_id",
        "name",
        "display_name",
        "description",
        "label",
        "symbol",
        "narrow_symbol",
        "mask",
        "separator",
        "plural",
        "is_active",
        "enabled",
        "state",
        "vigente",
        "is_current",
        "rate",
        "exchange_rate",
        "price",
        "balance",
    }
    for table in COLUMNS:
        columns = set(columns_of(conn, table))
        if table == "currency_locale":
            assert not (forbidden - {"name"}) & columns, table
        else:
            assert not forbidden & columns, table


def test_foreign_keys_point_only_to_locale_and_countries(conn: psycopg.Connection) -> None:
    """RNF-6: Currency depende de Locale y de Countries por identidades."""
    rows = conn.execute(
        "SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint "
        "WHERE contype = 'f' AND connamespace = 'reference'::regnamespace"
    ).fetchall()
    targets = {t for s, t in rows if s.removeprefix("reference.") in COLUMNS}
    assert targets == {
        "reference.currency",
        "reference.currency_snapshot",
        "reference.country",
        "reference.country_snapshot",
        "reference.locale",
        "reference.locale_snapshot",
    }


def test_earlier_catalogs_do_not_depend_on_currency(conn: psycopg.Connection) -> None:
    """RNF-6, CA-24: ninguna FK, trigger ni función de 001-003 conoce a Currency."""
    fks = conn.execute(
        "SELECT conrelid::regclass::text FROM pg_constraint "
        "WHERE contype = 'f' AND connamespace = 'reference'::regnamespace "
        "AND confrelid::regclass::text ~ '^reference\\.(currency|country_currency)'"
    ).fetchall()
    assert {s.removeprefix("reference.") for (s,) in fks} <= set(COLUMNS)
    dependent = conn.execute(
        "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE NOT t.tgisinternal AND c.relnamespace = 'reference'::regnamespace "
        "AND c.relname !~ '^(currency|country_currency)' AND c.relname NOT LIKE 'test_%%' "
        "AND pg_get_functiondef(t.tgfoid) ~* 'currency'"
    ).fetchone()
    assert dependent == (0,)
    column_refs = conn.execute(
        "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'reference' "
        "AND table_name !~ '^(currency|country_currency)' AND column_name ~* 'currenc'"
    ).fetchone()
    assert column_refs == (0,)


def test_deferred_constraints_are_evaluated_at_the_commit(conn: psycopg.Connection) -> None:
    names = [
        "currency_numeric_code_active_unique",
        "country_currency_active_no_overlap",
        "currency_replacement_exists",
        "currency_replacement_acyclic",
        "currency_inactive_has_no_open_associations",
        "country_currency_open_requires_active_targets",
    ]
    rows: dict[str, bool] = dict(
        conn.execute(
            "SELECT conname, condeferrable AND condeferred FROM pg_constraint "
            "WHERE connamespace = 'reference'::regnamespace AND conname = ANY (%s)",
            [names],
        ).fetchall()
    )
    triggers: dict[str, bool] = dict(
        conn.execute(
            "SELECT tgname, tgdeferrable AND tginitdeferred FROM pg_trigger "
            "WHERE NOT tgisinternal AND tgname = ANY (%s)",
            [names],
        ).fetchall()
    )
    assert {**rows, **triggers}.keys() == set(names)
    assert all({**rows, **triggers}.values()), (rows, triggers)


@pytest.mark.parametrize("table", list(COLUMNS))
def test_every_required_column_rejects_null(money: psycopg.Connection, table: str) -> None:
    rows: dict[str, dict[str, Any]] = {
        "currency_snapshot": currency_snapshot_row(snapshot_version=9),
        "currency": currency_row(alphabetic_code="BRL", numeric_code="986"),
        "currency_locale": {"currency_id": Ids.ars, "locale_id": EN, "name": "Argentine Peso"},
        "country_currency": association_row(HR, Ids.eur),
    }
    for column in COLUMNS[table]:
        if column in NULLABLE or column in GENERATED:
            continue
        with money.transaction(), rejected(errors.NotNullViolation):
            insert(money, table, {**rows[table], column: None})


def test_minor_units_not_applicable_is_distinct_from_zero(money: psycopg.Connection) -> None:
    """CL-1, CL-2: NULL es «no aplicable»; 0, 2, 3 y 4 se representan tal cual."""
    for code, num, units in (("JPY", "392", 0), ("KWD", "414", 3), ("CLF", "990", 4)):
        insert(
            money,
            "currency",
            currency_row(alphabetic_code=code, numeric_code=num, minor_units=units),
        )
    insert(
        money,
        "currency",
        currency_row(alphabetic_code="XAU", numeric_code="959", minor_units=None),
    )
    got: dict[str, Any] = dict(
        money.execute(
            "SELECT alphabetic_code, minor_units FROM reference.currency "
            "WHERE alphabetic_code IN ('JPY','KWD','CLF','XAU')"
        ).fetchall()
    )
    assert got == {"JPY": 0, "KWD": 3, "CLF": 4, "XAU": None}


def test_negative_minor_units_are_rejected(money: psycopg.Connection) -> None:
    with rejected(errors.CheckViolation, "currency_minor_units_valid"):
        insert(
            money,
            "currency",
            currency_row(alphabetic_code="BRL", numeric_code="986", minor_units=-1),
        )


@pytest.mark.parametrize("code", ["ars", "AR", "ARSS", "AR1", " AR", "ÁRS", ""])
def test_alphabetic_code_outside_format_is_rejected(money: psycopg.Connection, code: str) -> None:
    with rejected(errors.CheckViolation, "currency_alphabetic_code_format"):
        insert(money, "currency", currency_row(alphabetic_code=code, numeric_code="986"))


@pytest.mark.parametrize("code", ["32", "0320", "03a", "+32", " 32", ""])
def test_numeric_code_outside_format_is_rejected(money: psycopg.Connection, code: str) -> None:
    with rejected(errors.CheckViolation, "currency_numeric_code_format"):
        insert(money, "currency", currency_row(alphabetic_code="BRL", numeric_code=code))


def test_numeric_codes_keep_their_leading_zeros(money: psycopg.Connection) -> None:
    """CL-3."""
    assert money.execute(
        "SELECT numeric_code FROM reference.currency WHERE currency_id = %s", [Ids.ars]
    ).fetchone() == ("032",)


def test_invalid_status_is_rejected(money: psycopg.Connection) -> None:
    for table, row in (
        ("currency", currency_row(alphabetic_code="BRL", numeric_code="986", status="retired")),
        ("country_currency", association_row(HR, Ids.eur, status="not_found")),
    ):
        with rejected(errors.CheckViolation, f"{table}_status_valid"):
            insert(money, table, row)


# --- unicidad de códigos (D-15, RF-3) ---------------------------------------------------------


def test_alphabetic_code_is_unique_across_the_whole_catalog_including_inactive(
    money: psycopg.Connection,
) -> None:
    with rejected(errors.UniqueViolation, "currency_alphabetic_code_unique"):
        insert(money, "currency", currency_row(alphabetic_code="ARS", numeric_code="986"))
    with rejected(errors.UniqueViolation, "currency_alphabetic_code_unique"):
        insert(
            money,
            "currency",
            currency_row(alphabetic_code="HRK", numeric_code="986", status="inactive"),
        )


def test_numeric_code_is_unique_only_among_active(money: psycopg.Connection) -> None:
    with rejected(errors.ExclusionViolation, "currency_numeric_code_active_unique"):
        insert(money, "currency", currency_row(alphabetic_code="BRL", numeric_code="032"))
    # HRK es `inactive` con 191: una `active` puede usarlo (CL-11, precedente 891 YUM → CSD).
    insert(money, "currency", currency_row(alphabetic_code="HRX", numeric_code="191"))
    # y una segunda `inactive` con el mismo numérico también es válida.
    insert(
        money,
        "currency",
        currency_row(alphabetic_code="HRY", numeric_code="191", status="inactive"),
    )


def test_numeric_code_reuse_is_evaluated_on_the_final_state_of_the_transaction(
    money: psycopg.Connection,
) -> None:
    """RF-3, CL-11 (891: YUM → CSD): el numérico pasa de una moneda a otra en una transacción."""
    for code in ("YUM", "CSD"):
        insert(
            money,
            "currency",
            currency_row(alphabetic_code=code, numeric_code="891", status="inactive"),
        )
    money.execute("UPDATE reference.currency SET status = 'active' WHERE alphabetic_code = 'YUM'")
    with rejected(errors.ExclusionViolation, "currency_numeric_code_active_unique"):
        money.execute(
            "UPDATE reference.currency SET status = 'active' WHERE alphabetic_code = 'CSD'"
        )
    with money.transaction():
        money.execute(
            "UPDATE reference.currency SET status = 'active' WHERE alphabetic_code = 'CSD'"
        )
        money.execute(
            "UPDATE reference.currency SET status = 'inactive' WHERE alphabetic_code = 'YUM'"
        )
    assert money.execute(
        "SELECT alphabetic_code FROM reference.currency WHERE numeric_code = '891' "
        "AND status = 'active'"
    ).fetchall() == [("CSD",)]


# --- identidad inmutable (RF-2, RF-5) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("currency_id", str(uuid.uuid4())),
        ("alphabetic_code", "ARX"),
        ("numeric_code", "999"),
        ("first_snapshot_version", 2),
    ],
)
def test_currency_identity_and_codes_are_immutable(
    catalog: psycopg.Connection, column: str, value: Any
) -> None:
    insert(catalog, "currency", currency_row(currency_id=Ids.ars))
    with rejected(errors.RestrictViolation):
        catalog.execute(
            sql.SQL("UPDATE reference.currency SET {} = %s WHERE currency_id = %s").format(
                sql.Identifier(column)
            ),
            [value, Ids.ars],
        )


def test_mutable_currency_columns_can_change(money: psycopg.Connection) -> None:
    money.execute(
        "UPDATE reference.currency SET minor_units = NULL, fund_code = true, "
        "last_changed_snapshot_version = 2 WHERE currency_id = %s",
        [Ids.ars],
    )
    assert money.execute(
        "SELECT minor_units, fund_code, last_changed_snapshot_version FROM reference.currency "
        "WHERE currency_id = %s",
        [Ids.ars],
    ).fetchone() == (None, True, 2)


# --- reemplazo 0..N (RF-6, D-17) --------------------------------------------------------------


def test_replacement_accepts_zero_one_and_many_successors(money: psycopg.Connection) -> None:
    insert(
        money,
        "currency",
        currency_row(
            alphabetic_code="CSK",
            numeric_code="203",
            status="inactive",
            replacement_currency_ids=ascending(Ids.ars, Ids.usd),
        ),
    )
    assert money.execute(
        "SELECT cardinality(replacement_currency_ids) FROM reference.currency "
        "WHERE alphabetic_code IN ('CSK', 'HRK') ORDER BY alphabetic_code"
    ).fetchall() == [(2,), (1,)]
    assert money.execute(
        "SELECT cardinality(replacement_currency_ids) FROM reference.currency "
        "WHERE alphabetic_code = 'ARS'"
    ).fetchone() == (0,)


@pytest.mark.parametrize(
    ("successors", "constraint"),
    [
        (lambda me: [me], "currency_replacement_not_self"),
        (lambda me: [Ids.eur, Ids.eur], "currency_replacement_ascending_unique"),
        (
            lambda me: sorted([Ids.eur, Ids.ars], reverse=True),
            "currency_replacement_ascending_unique",
        ),
        (lambda me: [Ids.eur, None], "currency_replacement_no_nulls"),
    ],
)
def test_invalid_replacement_sets_are_rejected(
    money: psycopg.Connection,
    successors: Callable[[str], list[str | None]],
    constraint: str,
) -> None:
    me = str(uuid.uuid4())
    with rejected(errors.CheckViolation, constraint):
        insert(
            money,
            "currency",
            currency_row(
                currency_id=me,
                alphabetic_code="CSK",
                numeric_code="203",
                status="inactive",
                replacement_currency_ids=successors(me),
            ),
        )


def test_replacement_on_an_active_currency_is_rejected(money: psycopg.Connection) -> None:
    with rejected(errors.CheckViolation, "currency_replacement_requires_inactive"):
        insert(
            money,
            "currency",
            currency_row(
                alphabetic_code="CSK", numeric_code="203", replacement_currency_ids=[Ids.eur]
            ),
        )


def test_replacement_to_a_missing_currency_is_rejected_at_the_commit(
    money: psycopg.Connection,
) -> None:
    with rejected(errors.CheckViolation, "currency_replacement_exists"):
        insert(
            money,
            "currency",
            currency_row(
                alphabetic_code="CSK",
                numeric_code="203",
                status="inactive",
                replacement_currency_ids=[str(uuid.uuid4())],
            ),
        )


def test_successor_may_be_created_in_the_same_transaction(money: psycopg.Connection) -> None:
    new_id = str(uuid.uuid4())
    with money.transaction():
        insert(
            money,
            "currency",
            currency_row(
                alphabetic_code="CSK",
                numeric_code="203",
                status="inactive",
                replacement_currency_ids=[new_id],
            ),
        )
        insert(
            money,
            "currency",
            currency_row(currency_id=new_id, alphabetic_code="CZK", numeric_code="203"),
        )
    assert count(money, "currency") == 7


def test_a_successor_may_itself_be_inactive_without_a_cycle(money: psycopg.Connection) -> None:
    """RF-6: HRK → EUR, y una moneda anterior → HRK es una cadena válida."""
    insert(
        money,
        "currency",
        currency_row(
            alphabetic_code="YUD",
            numeric_code="890",
            status="inactive",
            replacement_currency_ids=[Ids.hrk],
        ),
    )


def test_replacement_cycles_are_rejected_by_the_database(money: psycopg.Connection) -> None:
    """CA-3: ciclos de 2 y de 3 monedas fallan en la persistencia."""
    a, b, c = (str(uuid.uuid4()) for _ in range(3))
    for cid, code, num in ((a, "AAA", "901"), (b, "BBB", "902"), (c, "CCC", "903")):
        insert(
            money,
            "currency",
            currency_row(
                currency_id=cid, alphabetic_code=code, numeric_code=num, status="inactive"
            ),
        )
    with rejected(errors.CheckViolation, "currency_replacement_acyclic"), money.transaction():
        money.execute(
            "UPDATE reference.currency SET replacement_currency_ids = %s WHERE currency_id = %s",
            [[b], a],
        )
        money.execute(
            "UPDATE reference.currency SET replacement_currency_ids = %s WHERE currency_id = %s",
            [[a], b],
        )
    with rejected(errors.CheckViolation, "currency_replacement_acyclic"), money.transaction():
        for src, dst in ((a, b), (b, c), (c, a)):
            money.execute(
                "UPDATE reference.currency SET replacement_currency_ids = %s "
                "WHERE currency_id = %s",
                [[dst], src],
            )
    assert money.execute(
        "SELECT count(*) FROM reference.currency WHERE cardinality(replacement_currency_ids) > 0"
    ).fetchone() == (1,)  # solo HRK → EUR


def test_a_back_edge_into_an_existing_chain_is_rejected(money: psycopg.Connection) -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    insert(
        money,
        "currency",
        currency_row(currency_id=b, alphabetic_code="BBB", numeric_code="902", status="inactive"),
    )
    insert(
        money,
        "currency",
        currency_row(
            currency_id=a,
            alphabetic_code="AAA",
            numeric_code="901",
            status="inactive",
            replacement_currency_ids=[b],
        ),
    )
    with rejected(errors.CheckViolation, "currency_replacement_acyclic"):
        money.execute(
            "UPDATE reference.currency SET replacement_currency_ids = %s WHERE currency_id = %s",
            [[a], b],
        )


def test_reactivation_requires_clearing_the_replacements_in_the_same_update(
    money: psycopg.Connection,
) -> None:
    """RF-10, CL-19."""
    with rejected(errors.CheckViolation, "currency_replacement_requires_inactive"):
        money.execute(
            "UPDATE reference.currency SET status = 'active' WHERE currency_id = %s", [Ids.hrk]
        )
    # 191 está libre entre `active`: se reactiva y limpia el conjunto.
    money.execute(
        "UPDATE reference.currency SET status = 'active', replacement_currency_ids = '{}' "
        "WHERE currency_id = %s",
        [Ids.hrk],
    )
    assert money.execute(
        "SELECT status, replacement_currency_ids FROM reference.currency WHERE currency_id = %s",
        [Ids.hrk],
    ).fetchone() == ("active", [])


# --- localizaciones (RF-12, RF-16) ------------------------------------------------------------


def test_currency_locale_is_unique_per_pair_and_references_locale_and_currency(
    money: psycopg.Connection,
) -> None:
    insert(
        money,
        "currency_locale",
        {"currency_id": Ids.ars, "locale_id": EN, "name": "Argentine Peso"},
    )
    insert(
        money,
        "currency_locale",
        {"currency_id": Ids.ars, "locale_id": ES, "name": "peso argentino"},
    )
    with rejected(errors.UniqueViolation, "currency_locale_pkey"):
        insert(money, "currency_locale", {"currency_id": Ids.ars, "locale_id": EN, "name": "Otro"})
    with rejected(errors.ForeignKeyViolation, "currency_locale_locale_fk"):
        insert(
            money,
            "currency_locale",
            {"currency_id": Ids.usd, "locale_id": str(uuid.uuid4()), "name": "US Dollar"},
        )
    with rejected(errors.ForeignKeyViolation, "currency_locale_currency_fk"):
        insert(
            money,
            "currency_locale",
            {"currency_id": str(uuid.uuid4()), "locale_id": EN, "name": "Ghost"},
        )


@pytest.mark.parametrize("name", ["", " Peso", "Peso ", "\tPeso", "Peso\n"])
def test_untrimmed_or_empty_names_are_rejected(money: psycopg.Connection, name: str) -> None:
    with rejected(errors.CheckViolation, "currency_locale_name_trimmed"):
        insert(money, "currency_locale", {"currency_id": Ids.ars, "locale_id": EN, "name": name})


def test_currency_locale_pair_and_currency_are_immutable_but_the_name_can_change(
    money: psycopg.Connection,
) -> None:
    insert(
        money,
        "currency_locale",
        {"currency_id": Ids.ars, "locale_id": EN, "name": "Argentine Peso"},
    )
    with rejected(errors.RestrictViolation):
        money.execute(
            "UPDATE reference.currency_locale SET locale_id = %s WHERE currency_id = %s",
            [ES, Ids.ars],
        )
    money.execute(
        "UPDATE reference.currency_locale SET name = 'Peso' WHERE currency_id = %s", [Ids.ars]
    )


# --- CountryCurrency temporal (RF-17, RF-18, RF-44, RF-45) --------------------------------------


def test_validity_is_generated_as_a_half_open_daterange(money: psycopg.Connection) -> None:
    """RF-44: incluye el inicio, excluye el fin; NULL es no acotado."""
    insert(
        money,
        "country_currency",
        association_row(HR, Ids.hrk, valid_from=D(2000, 1, 1), valid_to=D(2023, 1, 1)),
    )
    insert(money, "country_currency", association_row(HR, Ids.eur, valid_from=D(2023, 1, 1)))
    insert(money, "country_currency", association_row(PA, Ids.usd))
    got: dict[str, Any] = dict(
        money.execute(
            "SELECT currency_id::text, validity::text FROM reference.country_currency"
        ).fetchall()
    )
    assert got[Ids.hrk] == "[2000-01-01,2023-01-01)"
    assert got[Ids.eur] == "[2023-01-01,)"
    assert got[Ids.usd] == "(,)"
    day = money.execute(
        "SELECT currency_id::text FROM reference.country_currency "
        "WHERE country_id = %s AND validity @> %s::date",
        [HR, D(2022, 12, 31)],
    ).fetchall()
    assert day == [(Ids.hrk,)]
    day = money.execute(
        "SELECT currency_id::text FROM reference.country_currency "
        "WHERE country_id = %s AND validity @> %s::date",
        [HR, D(2023, 1, 1)],
    ).fetchall()
    assert day == [(Ids.eur,)]


def test_validity_cannot_be_written_directly(money: psycopg.Connection) -> None:
    with pytest.raises(errors.GeneratedAlways):
        money.execute(
            "INSERT INTO reference.country_currency (country_currency_id, country_id, "
            "currency_id, status, validity, first_snapshot_version, last_changed_snapshot_version) "
            "VALUES (gen_random_uuid(), %s, %s, 'active', "
            "daterange('2000-01-01','2001-01-01'), 1, 1)",
            [HR, Ids.hrk],
        )


@pytest.mark.parametrize(
    ("start", "end"),
    [(D(2023, 1, 1), D(2023, 1, 1)), (D(2024, 1, 1), D(2023, 1, 1))],
)
def test_start_not_before_end_is_rejected(
    money: psycopg.Connection, start: date, end: date
) -> None:
    with rejected(errors.CheckViolation, "country_currency_validity_ordered"):
        insert(
            money, "country_currency", association_row(HR, Ids.hrk, valid_from=start, valid_to=end)
        )


def test_infinite_dates_are_rejected(money: psycopg.Connection) -> None:
    with rejected(errors.CheckViolation):
        money.execute(
            "INSERT INTO reference.country_currency (country_currency_id, country_id, "
            "currency_id, status, valid_from, first_snapshot_version, "
            "last_changed_snapshot_version) "
            "VALUES (gen_random_uuid(), %s, %s, 'active', 'infinity', 1, 1)",
            [HR, Ids.hrk],
        )


def test_associations_reference_existing_country_and_currency(money: psycopg.Connection) -> None:
    with rejected(errors.ForeignKeyViolation, "country_currency_country_fk"):
        insert(money, "country_currency", association_row(str(uuid.uuid4()), Ids.eur))
    with rejected(errors.ForeignKeyViolation, "country_currency_currency_fk"):
        insert(money, "country_currency", association_row(HR, str(uuid.uuid4())))


def test_overlapping_active_periods_of_the_same_pair_are_rejected(
    money: psycopg.Connection,
) -> None:
    """RF-45, CA-21."""
    insert(money, "country_currency", association_row(HR, Ids.eur, valid_from=D(2023, 1, 1)))
    with rejected(errors.ExclusionViolation, "country_currency_active_no_overlap"):
        insert(money, "country_currency", association_row(HR, Ids.eur, valid_from=D(2030, 1, 1)))
    with rejected(errors.ExclusionViolation, "country_currency_active_no_overlap"):
        insert(
            money,
            "country_currency",
            association_row(HR, Ids.eur, valid_from=D(2020, 1, 1), valid_to=D(2023, 1, 2)),
        )
    with rejected(errors.ExclusionViolation, "country_currency_active_no_overlap"):
        insert(money, "country_currency", association_row(HR, Ids.eur))  # (,) cubre todo


def test_adjacent_periods_of_the_same_pair_are_accepted(money: psycopg.Connection) -> None:
    """CL-20, CL-22: [a, b) y [b, c) no se solapan; la readopción es válida."""
    insert(money, "country_currency", association_row(HR, Ids.eur, valid_to=D(2010, 1, 1)))
    insert(
        money,
        "country_currency",
        association_row(HR, Ids.eur, valid_from=D(2010, 1, 1), valid_to=D(2015, 6, 1)),
    )
    insert(money, "country_currency", association_row(HR, Ids.eur, valid_from=D(2020, 1, 1)))
    assert count(money, "country_currency") == 3


def test_different_currencies_may_overlap_in_the_same_country(money: psycopg.Connection) -> None:
    """RF-18, CL-21: PAB y USD simultáneas en PA, sin moneda principal."""
    insert(money, "country_currency", association_row(PA, Ids.pab, valid_from=D(1904, 1, 1)))
    insert(money, "country_currency", association_row(PA, Ids.usd, valid_from=D(1904, 1, 1)))
    insert(money, "country_currency", association_row(PA, Ids.eur))
    assert count(money, "country_currency") == 3


def test_the_same_currency_may_belong_to_many_countries(money: psycopg.Connection) -> None:
    for country in (HR, PA):
        insert(money, "country_currency", association_row(country, Ids.eur))
    assert count(money, "country_currency") == 2


def test_a_country_without_currency_is_representable(money: psycopg.Connection) -> None:
    """CL-6: AQ sin filas."""
    assert money.execute(
        "SELECT count(*) FROM reference.country_currency WHERE country_id = %s", [AQ]
    ).fetchone() == (0,)


def test_inactive_records_do_not_take_part_in_the_overlap_rule(money: psycopg.Connection) -> None:
    """RF-47, CL-26: un registro retirado puede solaparse con su corrección."""
    wrong = association_row(HR, Ids.eur, valid_from=D(2023, 1, 1), valid_to=D(2024, 1, 1))
    insert(money, "country_currency", wrong)
    money.execute(
        "UPDATE reference.country_currency SET status = 'inactive' WHERE country_currency_id = %s",
        [wrong["country_currency_id"]],
    )
    insert(money, "country_currency", association_row(HR, Ids.eur, valid_from=D(2023, 1, 1)))
    insert(
        money,
        "country_currency",
        association_row(HR, Ids.eur, status="inactive", valid_from=D(2023, 6, 1)),
    )


def test_overlap_is_evaluated_at_the_commit_over_the_final_state(money: psycopg.Connection) -> None:
    """Un snapshot puede reordenar períodos dentro de una transacción."""
    first = association_row(HR, Ids.eur, valid_from=D(2023, 1, 1))
    insert(money, "country_currency", first)
    with money.transaction():
        insert(money, "country_currency", association_row(HR, Ids.eur, valid_from=D(2023, 1, 1)))
        money.execute(
            "UPDATE reference.country_currency SET status = 'inactive' "
            "WHERE country_currency_id = %s",
            [first["country_currency_id"]],
        )
    assert money.execute(
        "SELECT count(*) FROM reference.country_currency WHERE status = 'active'"
    ).fetchone() == (1,)


# --- historia inmutable (RF-46, RF-47, D11) -----------------------------------------------------


def test_a_missing_extreme_can_be_set_exactly_once_and_then_is_immutable(
    money: psycopg.Connection,
) -> None:
    """RF-46: cerrar una vigencia abierta; RF-47: luego no cambia."""
    row = association_row(HR, Ids.ars)
    insert(money, "country_currency", row)
    key = row["country_currency_id"]
    money.execute(
        "UPDATE reference.country_currency SET valid_from = %s WHERE country_currency_id = %s",
        [D(2000, 1, 1), key],
    )
    money.execute(
        "UPDATE reference.country_currency SET valid_to = %s WHERE country_currency_id = %s",
        [D(2023, 1, 1), key],
    )
    for column, value in (
        ("valid_to", D(2023, 6, 1)),
        ("valid_to", None),
        ("valid_from", D(1999, 1, 1)),
        ("valid_from", None),
    ):
        with rejected(errors.RestrictViolation):
            money.execute(
                sql.SQL(
                    "UPDATE reference.country_currency SET {} = %s WHERE country_currency_id = %s"
                ).format(sql.Identifier(column)),
                [value, key],
            )
    assert money.execute(
        "SELECT validity::text FROM reference.country_currency WHERE country_currency_id = %s",
        [key],
    ).fetchone() == ("[2000-01-01,2023-01-01)",)


def test_rewriting_the_same_extreme_value_is_a_noop_not_a_violation(
    money: psycopg.Connection,
) -> None:
    row = association_row(HR, Ids.hrk, valid_from=D(2000, 1, 1), valid_to=D(2023, 1, 1))
    insert(money, "country_currency", row)
    money.execute(
        "UPDATE reference.country_currency SET valid_from = valid_from, valid_to = valid_to, "
        "last_changed_snapshot_version = 2 WHERE country_currency_id = %s",
        [row["country_currency_id"]],
    )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("country_currency_id", str(uuid.uuid4())),
        ("country_id", PA),
        ("currency_id", "usd"),
        ("first_snapshot_version", 2),
    ],
)
def test_association_identity_is_immutable(
    money: psycopg.Connection, column: str, value: Any
) -> None:
    row = association_row(HR, Ids.eur)
    insert(money, "country_currency", row)
    if column == "currency_id":
        value = Ids.usd
    with rejected(errors.RestrictViolation):
        money.execute(
            sql.SQL(
                "UPDATE reference.country_currency SET {} = %s WHERE country_currency_id = %s"
            ).format(sql.Identifier(column)),
            [value, row["country_currency_id"]],
        )


def test_status_is_independent_from_validity(money: psycopg.Connection) -> None:
    """RF-51, CA-20: una asociación cerrada sigue `active`; el tiempo no cambia ninguna columna."""
    row = association_row(HR, Ids.hrk, valid_from=D(2000, 1, 1), valid_to=D(2001, 1, 1))
    insert(money, "country_currency", row)
    before = money.execute(
        "SELECT status, valid_from, valid_to FROM reference.country_currency"
    ).fetchall()
    assert before == [("active", D(2000, 1, 1), D(2001, 1, 1))]
    # una asociación cerrada sobre una moneda y un país distintos de `active` es historia válida
    money.execute("UPDATE reference.country SET status = 'inactive' WHERE country_id = %s", [HR])
    assert money.execute(
        "SELECT count(*) FROM reference.country_currency_integrity_violation"
    ).fetchone() == (0,)
    triggers = money.execute(
        "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE NOT t.tgisinternal AND c.relname = 'country_currency' "
        "AND pg_get_functiondef(t.tgfoid) ~* 'now\\(\\)|current_date|clock_timestamp'"
    ).fetchone()
    assert triggers == (0,)


# --- RF-19 sin dependencia Country → Currency (D12) ---------------------------------------------


def test_open_active_association_needs_active_country_and_currency(
    money: psycopg.Connection,
) -> None:
    money.execute("UPDATE reference.country SET status = 'inactive' WHERE country_id = %s", [AQ])
    with rejected(errors.CheckViolation, "country_currency_open_requires_active_targets"):
        insert(money, "country_currency", association_row(AQ, Ids.eur))
    with rejected(errors.CheckViolation, "country_currency_open_requires_active_targets"):
        insert(money, "country_currency", association_row(HR, Ids.hrk))  # moneda `inactive`


def test_closed_or_inactive_associations_may_reference_inactive_entities(
    money: psycopg.Connection,
) -> None:
    """CL-27: la historia no se bloquea."""
    insert(money, "country_currency", association_row(HR, Ids.hrk, valid_to=D(2023, 1, 1)))
    insert(money, "country_currency", association_row(HR, Ids.hrk, status="inactive"))


def test_a_currency_cannot_become_inactive_with_an_open_active_association(
    money: psycopg.Connection,
) -> None:
    insert(money, "country_currency", association_row(HR, Ids.eur))
    with rejected(errors.CheckViolation, "currency_inactive_has_open_associations"):
        money.execute(
            "UPDATE reference.currency SET status = 'inactive' WHERE currency_id = %s", [Ids.eur]
        )


def test_retiring_a_currency_closes_its_associations_in_the_same_transaction(
    money: psycopg.Connection,
) -> None:
    """RF-38, CL-8: HRK queda `inactive`; HR–HRK queda `active` y cerrada."""
    open_row = association_row(HR, Ids.ars, valid_from=D(1994, 5, 30))
    insert(money, "country_currency", open_row)
    with money.transaction():
        money.execute(
            "UPDATE reference.currency SET status = 'inactive' WHERE currency_id = %s", [Ids.ars]
        )
        money.execute(
            "UPDATE reference.country_currency SET valid_to = %s WHERE country_currency_id = %s",
            [D(2023, 1, 1), open_row["country_currency_id"]],
        )
        insert(money, "country_currency", association_row(HR, Ids.eur, valid_from=D(2023, 1, 1)))
    assert money.execute(
        "SELECT c.status, a.status, a.validity::text FROM reference.country_currency a "
        "JOIN reference.currency c USING (currency_id) WHERE a.country_currency_id = %s",
        [open_row["country_currency_id"]],
    ).fetchone() == ("inactive", "active", "[1994-05-30,2023-01-01)")


def test_the_integrity_view_reports_drift_caused_by_a_later_country_retirement(
    money: psycopg.Connection,
) -> None:
    """S-8: 003 puede retirar un país sin conocer Currency; la deriva queda visible."""
    row = association_row(HR, Ids.eur)
    insert(money, "country_currency", row)
    assert money.execute(
        "SELECT count(*) FROM reference.country_currency_integrity_violation"
    ).fetchone() == (0,)
    money.execute("UPDATE reference.country SET status = 'inactive' WHERE country_id = %s", [HR])
    assert money.execute(
        "SELECT country_currency_id::text, country_not_active, currency_not_active "
        "FROM reference.country_currency_integrity_violation"
    ).fetchall() == [(row["country_currency_id"], True, False)]


# --- inmutabilidad del catálogo e historial (RF-7, RF-37, RNF-2) --------------------------------


@pytest.mark.parametrize("table", CATALOG)
def test_published_catalog_rows_are_never_deleted_or_truncated(
    money: psycopg.Connection, table: str
) -> None:
    insert(
        money,
        "currency_locale",
        {"currency_id": Ids.ars, "locale_id": EN, "name": "Argentine Peso"},
    )
    insert(money, "country_currency", association_row(HR, Ids.eur))
    with rejected(errors.RestrictViolation):
        money.execute(sql.SQL("DELETE FROM reference.{}").format(sql.Identifier(table)))
    with pytest.raises(TRUNCATE_REJECTIONS):
        money.execute(sql.SQL("TRUNCATE reference.{}").format(sql.Identifier(table)))
    with rejected(errors.RestrictViolation):
        money.execute(sql.SQL("TRUNCATE reference.{} CASCADE").format(sql.Identifier(table)))
    assert count(money, table) >= 1


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


def test_snapshot_version_must_be_positive_and_country_versions_ordered(
    base: psycopg.Connection,
) -> None:
    with rejected(errors.CheckViolation, "currency_snapshot_version_positive"):
        insert(base, "currency_snapshot", currency_snapshot_row(snapshot_version=0))
    insert(base, "country_snapshot", country_snapshot_row(snapshot_version=2))
    with rejected(errors.CheckViolation, "currency_snapshot_country_versions_ordered"):
        insert(
            base,
            "currency_snapshot",
            currency_snapshot_row(
                snapshot_version=2, country_snapshot_version=2, country_current_snapshot_version=1
            ),
        )
    with rejected(errors.ForeignKeyViolation, "currency_snapshot_country_declared_fk"):
        insert(
            base,
            "currency_snapshot",
            currency_snapshot_row(
                snapshot_version=3, country_snapshot_version=9, country_current_snapshot_version=9
            ),
        )


# --- privilegios (RNF-3) ------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["anon", "authenticated", "public"])
def test_api_roles_and_public_have_no_privileges_on_the_new_objects(
    conn: psycopg.Connection, role: str
) -> None:
    objects = [*COLUMNS, "country_currency_integrity_violation"]
    for table in objects:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            granted = conn.execute(
                "SELECT has_table_privilege(%s, %s, %s)", [role, f"reference.{table}", privilege]
            ).fetchone()
            assert granted == (False,), (role, table, privilege)


def test_reader_can_only_select(money: psycopg.Connection) -> None:
    insert(money, "country_currency", association_row(HR, Ids.eur))
    for _ in as_role(money, "reference_reader"):
        for table in (*COLUMNS, "country_currency_integrity_violation"):
            money.execute(sql.SQL("SELECT 1 FROM reference.{}").format(sql.Identifier(table)))
        for statement in (
            "INSERT INTO reference.currency_locale (currency_id, locale_id, name) "
            "VALUES (gen_random_uuid(), gen_random_uuid(), 'x')",
            "UPDATE reference.currency SET status = 'inactive'",
            "DELETE FROM reference.country_currency",
            "TRUNCATE reference.currency",
        ):
            with pytest.raises(errors.InsufficientPrivilege):
                money.execute(statement)


def test_loader_inserts_and_updates_only_the_mutable_columns(money: psycopg.Connection) -> None:
    row = association_row(HR, Ids.ars)
    insert(money, "country_currency", row)
    key = row["country_currency_id"]
    for _ in as_role(money, "reference_loader"):
        insert(
            money,
            "currency_locale",
            {"currency_id": Ids.ars, "locale_id": EN, "name": "Argentine Peso"},
        )
        money.execute(
            "UPDATE reference.currency_locale SET name = 'Peso' WHERE currency_id = %s", [Ids.ars]
        )
        money.execute(
            "UPDATE reference.country_currency SET status = 'inactive', valid_to = %s, "
            "last_changed_snapshot_version = 2 WHERE country_currency_id = %s",
            [D(2023, 1, 1), key],
        )
        money.execute(
            "UPDATE reference.currency SET minor_units = 0, last_changed_snapshot_version = 2 "
            "WHERE currency_id = %s",
            [Ids.ars],
        )
        for statement in (
            "UPDATE reference.currency SET alphabetic_code = 'XXA'",
            "UPDATE reference.currency SET numeric_code = '999'",
            "UPDATE reference.country_currency SET country_id = country_id",
            "UPDATE reference.country_currency SET first_snapshot_version = 1",
            "UPDATE reference.currency_snapshot SET content_digest = 'x'",
            "DELETE FROM reference.currency",
        ):
            with pytest.raises(errors.InsufficientPrivilege):
                money.execute(statement)
        money.execute("SELECT 1 FROM reference.country")  # lectura de Countries para validar
        money.execute("SELECT 1 FROM reference.country_currency_integrity_violation")


# --- concurrencia (RF-45 bajo carrera) ----------------------------------------------------------


def test_concurrent_overlapping_inserts_cannot_both_commit(
    database_url: str, money: psycopg.Connection
) -> None:
    """La exclusión es correcta bajo concurrencia, no solo en una conexión."""
    db = money.info.dbname
    url = database_url
    assert db in url
    outcomes: list[str] = []
    gate = threading.Barrier(2)

    def writer() -> None:
        with psycopg.connect(url) as c:
            c.execute(
                "INSERT INTO reference.country_currency (country_currency_id, country_id, "
                "currency_id, status, valid_from, first_snapshot_version, "
                "last_changed_snapshot_version) VALUES (gen_random_uuid(), %s, %s, 'active', "
                "'2023-01-01', 1, 1)",
                [HR, Ids.eur],
            )
            gate.wait(timeout=20)
            try:
                c.commit()
                outcomes.append("committed")
            except (
                errors.ExclusionViolation,
                errors.DeadlockDetected,
                errors.SerializationFailure,
            ):
                c.rollback()
                outcomes.append("rejected")

    threads = [threading.Thread(target=writer) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(outcomes) == ["committed", "rejected"], outcomes
    assert money.execute(
        "SELECT count(*) FROM reference.country_currency WHERE country_id = %s", [HR]
    ).fetchone() == (1,)


# --- downgrade ---------------------------------------------------------------------------------


def test_downgrade_to_0003_removes_only_the_currency_objects(database_url: str) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "0003")
    with psycopg.connect(database_url, autocommit=True) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'reference'"
            ).fetchall()
        }
        views = conn.execute(
            "SELECT count(*) FROM pg_views WHERE schemaname = 'reference' "
            "AND viewname LIKE '%%currency%%'"
        ).fetchone()
        functions = conn.execute(
            "SELECT count(*) FROM pg_proc WHERE pronamespace = 'reference'::regnamespace "
            "AND proname ~ 'currency'"
        ).fetchone()
        strictly = conn.execute(
            "SELECT count(*) FROM pg_proc WHERE proname = 'is_strictly_ascending'"
        ).fetchone()
    assert tables.isdisjoint(COLUMNS)
    assert {"locale", "region", "subregion", "country", "country_snapshot"} <= tables
    assert views == (0,)
    assert functions == (0,)
    assert strictly == (1,)  # función de 0003, intacta
    command.upgrade(config, "head")
