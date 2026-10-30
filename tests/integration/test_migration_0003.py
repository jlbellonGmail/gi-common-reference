"""T2: migración 0003 (Countries), probada con SQL directo, sin la aplicación."""

import uuid
from typing import Any

import psycopg
import pytest
from alembic import command
from psycopg import errors, sql

from tests.conftest import alembic_config
from tests.integration.test_migration_0001 import columns_of, insert, locale_row, rejected
from tests.integration.test_migration_0001 import snapshot_row as locale_snapshot_row
from tests.integration.test_migration_0002 import (
    AFRICA,
    AMERICAS,
    LATAM,
    LOCALE_ID,
    TRUNCATE_REJECTIONS,
    as_role,
    region_row,
    region_snapshot_row,
    subregion_row,
)

COLUMNS = {
    "country_snapshot": [
        "snapshot_version",
        "content_digest",
        "locale_snapshot_version",
        "region_snapshot_version",
        "region_current_snapshot_version",
        "required_locales_version",
        "provenance",
        "artifact",
        "incorporated_at",
    ],
    "country": [
        "country_id",
        "alpha2",
        "alpha3",
        "numeric_code",
        "region_id",
        "subregion_id",
        "calling_code",
        "status",
        "replacement_country_id",
        "first_snapshot_version",
        "codes_snapshot_version",
        "last_changed_snapshot_version",
    ],
    "country_locale": ["country_id", "locale_id", "name", "official_name"],
    "country_flag": ["country_id", "asset_path", "sha256", "exception_reason", "snapshot_version"],
    "country_recoding": [
        "country_id",
        "snapshot_version",
        "previous_alpha2",
        "previous_alpha3",
        "previous_numeric_code",
        "new_alpha2",
        "new_alpha3",
        "new_numeric_code",
        "provenance",
    ],
}
NULLABLE = {
    "region_id",
    "subregion_id",
    "calling_code",
    "replacement_country_id",
    "official_name",
    "asset_path",
    "sha256",
    "exception_reason",
    "incorporated_at",
}
HISTORY = ("country_snapshot", "country_recoding")
CATALOG = ("country", "country_locale", "country_flag")

AR = str(uuid.uuid4())
NA = str(uuid.uuid4())
AQ = str(uuid.uuid4())
OTHER_LOCALE = str(uuid.uuid4())
SHA = "sha256:" + "e" * 64


def country_snapshot_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "snapshot_version": 1,
        "content_digest": "sha256:" + "d" * 64,
        "locale_snapshot_version": 1,
        "region_snapshot_version": 1,
        "region_current_snapshot_version": 1,
        "required_locales_version": 1,
        "provenance": "{}",
        "artifact": "{}",
    }
    return {**row, **overrides}


def country_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "country_id": str(uuid.uuid4()),
        "alpha2": "AR",
        "alpha3": "ARG",
        "numeric_code": "032",
        "region_id": AMERICAS,
        "subregion_id": LATAM,
        "calling_code": "54",
        "status": "active",
        "replacement_country_id": None,
        "first_snapshot_version": 1,
        "codes_snapshot_version": 1,
        "last_changed_snapshot_version": 1,
    }
    return {**row, **overrides}


def recoding_row(country_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "country_id": country_id,
        "snapshot_version": 2,
        "previous_alpha2": "AR",
        "previous_alpha3": "ARG",
        "previous_numeric_code": "032",
        "new_alpha2": "AX",
        "new_alpha3": "ARG",
        "new_numeric_code": "032",
        "provenance": '{"source": "ISO 3166-1"}',
    }
    return {**row, **overrides}


@pytest.fixture
def base(conn: psycopg.Connection) -> psycopg.Connection:
    """Locale, Regions (Americas > Latin America, Africa) y el primer snapshot de Countries."""
    insert(conn, "locale_snapshot", locale_snapshot_row())
    insert(conn, "locale", locale_row(locale_id=LOCALE_ID, code="en"))
    insert(conn, "locale", locale_row(locale_id=OTHER_LOCALE, code="es"))
    insert(conn, "region_snapshot", region_snapshot_row())
    insert(conn, "region", region_row(region_id=AMERICAS, code="019"))
    insert(conn, "region", region_row(region_id=AFRICA, code="002"))
    insert(conn, "subregion", subregion_row(subregion_id=LATAM, code="419"))
    insert(conn, "country_snapshot", country_snapshot_row())
    return conn


@pytest.fixture
def catalog(base: psycopg.Connection) -> psycopg.Connection:
    """Argentina (en Latin America), Namibia (solo Africa) y Antártida (sin clasificación)."""
    insert(base, "country", country_row(country_id=AR))
    insert(
        base,
        "country",
        country_row(
            country_id=NA,
            alpha2="NA",
            alpha3="NAM",
            numeric_code="516",
            region_id=AFRICA,
            subregion_id=None,
            calling_code="264",
        ),
    )
    insert(
        base,
        "country",
        country_row(
            country_id=AQ,
            alpha2="AQ",
            alpha3="ATA",
            numeric_code="010",
            region_id=None,
            subregion_id=None,
            calling_code=None,
        ),
    )
    insert(
        base,
        "country_locale",
        {"country_id": AR, "locale_id": LOCALE_ID, "name": "Argentina", "official_name": None},
    )
    insert(base, "country_snapshot", country_snapshot_row(snapshot_version=2))
    return base


# --- estructura -------------------------------------------------------------------------------


def test_tables_have_exactly_the_planned_columns(conn: psycopg.Connection) -> None:
    for table, columns in COLUMNS.items():
        assert columns_of(conn, table) == columns, table


def test_no_table_has_tenant_and_country_has_no_text_nor_legacy_columns(
    conn: psycopg.Connection,
) -> None:
    """RF-1, RF-34, RF-39, CA-1: ni tenant_id, ni textos, ni región/subregión como texto."""
    for table in COLUMNS:
        assert "tenant_id" not in columns_of(conn, table)
    forbidden = {
        "name",
        "official_name",
        "display_name",
        "localized_name",
        "description",
        "label",
        "language",
        "lang",
        "locale",
        "region_code",
        "region_name",
        "subregion_code",
        "subregion_name",
        "is_active",
        "enabled",
        "state",
        "deprecated",
        "country_code",
    }
    for table in ("country", "country_snapshot", "country_flag", "country_recoding"):
        assert not forbidden & set(columns_of(conn, table)), table


def test_foreign_keys_stay_inside_schema_reference_and_point_only_to_locale_and_regions(
    conn: psycopg.Connection,
) -> None:
    """RNF-7: Countries depende de Locale y de Regions por identidades; nada hacia Currency."""
    rows = conn.execute(
        "SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint "
        "WHERE contype = 'f' AND connamespace = 'reference'::regnamespace"
    ).fetchall()
    targets = {target for source, target in rows if source.removeprefix("reference.") in COLUMNS}
    assert targets == {
        "reference.country",
        "reference.country_snapshot",
        "reference.locale",
        "reference.locale_snapshot",
        "reference.region",
        "reference.region_snapshot",
        "reference.subregion",
    }


def test_locale_and_regions_do_not_depend_on_countries(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        "SELECT conrelid::regclass::text FROM pg_constraint "
        "WHERE connamespace = 'reference'::regnamespace AND contype = 'f' "
        "AND confrelid::regclass::text LIKE 'reference.country%%'"
    ).fetchall()
    sources = {source.removeprefix("reference.") for (source,) in rows}
    assert sources <= set(COLUMNS)
    dependent = conn.execute(
        "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE NOT t.tgisinternal AND c.relnamespace = 'reference'::regnamespace "
        "AND c.relname NOT LIKE 'country%%' AND c.relname NOT LIKE 'test_%%' "
        "AND pg_get_functiondef(t.tgfoid) ILIKE '%%reference.country%%'"
    ).fetchone()
    assert dependent == (0,)


def test_deferred_constraints_are_evaluated_at_the_commit(conn: psycopg.Connection) -> None:
    """RF-44: unicidad, reemplazo, clasificación y traza de recodificación sobre el estado final."""
    names = [
        "country_alpha2_active_unique",
        "country_alpha3_active_unique",
        "country_numeric_code_active_unique",
        "country_replacement_fk",
        "country_classification_fk",
        "country_codes_require_recoding",
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
def test_every_required_column_rejects_null(catalog: psycopg.Connection, table: str) -> None:
    rows: dict[str, dict[str, Any]] = {
        "country_snapshot": country_snapshot_row(snapshot_version=3),
        "country": country_row(alpha2="BR", alpha3="BRA", numeric_code="076", subregion_id=None),
        "country_locale": {
            "country_id": AR,
            "locale_id": OTHER_LOCALE,
            "name": "Argentina",
            "official_name": None,
        },
        "country_flag": {
            "country_id": AR,
            "asset_path": "ar.svg",
            "sha256": SHA,
            "exception_reason": None,
            "snapshot_version": 1,
        },
        "country_recoding": recoding_row(AR),
    }
    for column in COLUMNS[table]:
        if column in NULLABLE:
            continue
        with catalog.transaction(), rejected(errors.NotNullViolation):
            insert(catalog, table, {**rows[table], column: None})


def test_a_snapshot_cannot_declare_a_regions_version_later_than_the_current_one(
    base: psycopg.Connection,
) -> None:
    insert(base, "region_snapshot", region_snapshot_row(snapshot_version=2))
    insert(
        base,
        "country_snapshot",
        country_snapshot_row(
            snapshot_version=2, region_snapshot_version=1, region_current_snapshot_version=2
        ),
    )
    with rejected(errors.CheckViolation, "country_snapshot_region_versions_ordered"):
        insert(
            base,
            "country_snapshot",
            country_snapshot_row(
                snapshot_version=3, region_snapshot_version=2, region_current_snapshot_version=1
            ),
        )


def test_a_snapshot_needs_incorporated_locale_and_region_versions(base: psycopg.Connection) -> None:
    with rejected(errors.ForeignKeyViolation, "country_snapshot_locale_snapshot_fk"):
        insert(
            base,
            "country_snapshot",
            country_snapshot_row(snapshot_version=2, locale_snapshot_version=9),
        )
    with rejected(errors.ForeignKeyViolation, "country_snapshot_region_current_fk"):
        insert(
            base,
            "country_snapshot",
            country_snapshot_row(snapshot_version=2, region_current_snapshot_version=9),
        )
    with pytest.raises(errors.ForeignKeyViolation):
        insert(
            base,
            "country_snapshot",
            country_snapshot_row(
                snapshot_version=2, region_snapshot_version=9, region_current_snapshot_version=9
            ),
        )
    with rejected(errors.CheckViolation, "country_snapshot_version_positive"):
        insert(base, "country_snapshot", country_snapshot_row(snapshot_version=0))


# --- códigos (RF-3, RF-4, RF-5, RF-44) ----------------------------------------------------------


@pytest.mark.parametrize("code", ["ar", "A", "ARG", "A1", "", " A", "N A", "Ñ1", "A\n"])
def test_alpha2_must_be_two_uppercase_letters(base: psycopg.Connection, code: str) -> None:
    with rejected(errors.CheckViolation, "country_alpha2_format"):
        insert(base, "country", country_row(alpha2=code))


@pytest.mark.parametrize("code", ["arg", "AR", "ARGE", "AR1", "", " AR", "A-R"])
def test_alpha3_must_be_three_uppercase_letters(base: psycopg.Connection, code: str) -> None:
    with rejected(errors.CheckViolation, "country_alpha3_format"):
        insert(base, "country", country_row(alpha3=code))


@pytest.mark.parametrize("code", ["32", "4", "0032", "abc", "", "03a", " 32", "٣٢٠"])
def test_numeric_code_must_be_three_ascii_digits_kept_as_text(
    base: psycopg.Connection, code: str
) -> None:
    with rejected(errors.CheckViolation, "country_numeric_code_format"):
        insert(base, "country", country_row(numeric_code=code))


@pytest.mark.parametrize("code", ["+54", "054", "0", "5400", "", "5 4", "5a"])
def test_calling_code_is_one_to_three_digits_without_plus_nor_leading_zero(
    base: psycopg.Connection, code: str
) -> None:
    with rejected(errors.CheckViolation, "country_calling_code_format"):
        insert(base, "country", country_row(calling_code=code))


def test_codes_are_mandatory_but_calling_code_is_optional(base: psycopg.Connection) -> None:
    insert(base, "country", country_row(calling_code=None))


def test_na_and_leading_zeros_are_stored_and_read_without_alteration(
    base: psycopg.Connection,
) -> None:
    """CL-5, CL-6, CA-4: `NA` no es nulo y `004` no es 4."""
    insert(
        base,
        "country",
        country_row(alpha2="NA", alpha3="NAM", numeric_code="004", calling_code="264"),
    )
    row = base.execute(
        "SELECT alpha2, alpha2 IS NULL, numeric_code, pg_typeof(numeric_code)::text "
        "FROM reference.country"
    ).fetchone()
    assert row == ("NA", False, "004", "text")


def test_two_active_countries_cannot_share_any_code(catalog: psycopg.Connection) -> None:
    with rejected(errors.ExclusionViolation, "country_alpha2_active_unique"):
        insert(catalog, "country", country_row(alpha3="XXX", numeric_code="999"))
    with rejected(errors.ExclusionViolation, "country_alpha3_active_unique"):
        insert(catalog, "country", country_row(alpha2="XX", numeric_code="999"))
    with rejected(errors.ExclusionViolation, "country_numeric_code_active_unique"):
        insert(catalog, "country", country_row(alpha2="XX", alpha3="XXX"))


def test_inactive_countries_may_keep_a_code_that_an_active_one_has(
    catalog: psycopg.Connection,
) -> None:
    insert(catalog, "country", country_row(status="inactive", replacement_country_id=AR))


def test_a_collision_left_at_commit_is_rejected(catalog: psycopg.Connection) -> None:
    with pytest.raises(errors.ExclusionViolation), catalog.transaction():
        insert(catalog, "country", country_row())


def test_a_declared_swap_of_alpha2_inside_one_transaction_is_valid_on_the_final_state(
    catalog: psycopg.Connection,
) -> None:
    """RF-44, CL-13: sin colisiones intermedias; cada cambio lleva su recodificación trazada."""
    with catalog.transaction():
        catalog.execute(
            "UPDATE reference.country SET alpha2 = 'NA', codes_snapshot_version = 2 "
            "WHERE country_id = %s",
            [AR],
        )
        catalog.execute(
            "UPDATE reference.country SET alpha2 = 'AR', codes_snapshot_version = 2 "
            "WHERE country_id = %s",
            [NA],
        )
        insert(catalog, "country_recoding", recoding_row(AR, new_alpha2="NA"))
        insert(
            catalog,
            "country_recoding",
            recoding_row(
                NA,
                previous_alpha2="NA",
                previous_alpha3="NAM",
                previous_numeric_code="516",
                new_alpha2="AR",
                new_alpha3="NAM",
                new_numeric_code="516",
            ),
        )
    codes: dict[str, str] = dict(
        catalog.execute("SELECT country_id::text, alpha2 FROM reference.country")
    )
    assert codes[AR] == "NA" and codes[NA] == "AR"


# --- recodificación (RF-4, RF-41, RF-46) --------------------------------------------------------


def test_changing_the_code_triple_needs_the_recoding_trace_of_the_same_snapshot(
    catalog: psycopg.Connection,
) -> None:
    with rejected(errors.RestrictViolation, "country_codes_require_recoding"):
        catalog.execute(
            "UPDATE reference.country SET alpha2 = 'AX', codes_snapshot_version = 2 "
            "WHERE country_id = %s",
            [AR],
        )
    with (
        rejected(errors.RestrictViolation, "country_codes_require_recoding"),
        catalog.transaction(),
    ):
        catalog.execute(
            "UPDATE reference.country SET alpha2 = 'AX', codes_snapshot_version = 2 "
            "WHERE country_id = %s",
            [AR],
        )
        insert(catalog, "country_recoding", recoding_row(AR, snapshot_version=1))
    alpha2 = catalog.execute(
        "SELECT alpha2 FROM reference.country WHERE country_id = %s", [AR]
    ).fetchone()
    assert alpha2 == ("AR",)


def test_the_recoding_trace_must_describe_the_actual_change(catalog: psycopg.Connection) -> None:
    with (
        rejected(errors.RestrictViolation, "country_codes_require_recoding"),
        catalog.transaction(),
    ):
        catalog.execute(
            "UPDATE reference.country SET alpha2 = 'AX', codes_snapshot_version = 2 "
            "WHERE country_id = %s",
            [AR],
        )
        insert(catalog, "country_recoding", recoding_row(AR, new_alpha2="AY"))
    with (
        rejected(errors.RestrictViolation, "country_codes_require_recoding"),
        catalog.transaction(),
    ):
        catalog.execute(
            "UPDATE reference.country SET alpha2 = 'AX', codes_snapshot_version = 2 "
            "WHERE country_id = %s",
            [AR],
        )
        insert(catalog, "country_recoding", recoding_row(AR, previous_alpha3="ARX"))


def test_a_declared_recoding_keeps_the_identity_status_and_names(
    catalog: psycopg.Connection,
) -> None:
    with catalog.transaction():
        catalog.execute(
            "UPDATE reference.country SET alpha2 = 'AX', codes_snapshot_version = 2, "
            "last_changed_snapshot_version = 2 WHERE country_id = %s",
            [AR],
        )
        insert(catalog, "country_recoding", recoding_row(AR))
    row = catalog.execute(
        "SELECT alpha2, status, first_snapshot_version, codes_snapshot_version "
        "FROM reference.country WHERE country_id = %s",
        [AR],
    ).fetchone()
    assert row == ("AX", "active", 1, 2)
    names = catalog.execute("SELECT count(*) FROM reference.country_locale").fetchone()
    assert names == (1,)


def test_the_codes_snapshot_version_moves_only_with_the_code_triple(
    catalog: psycopg.Connection,
) -> None:
    with rejected(errors.RestrictViolation, "country_codes_snapshot_coupled"):
        catalog.execute(
            "UPDATE reference.country SET codes_snapshot_version = 2 WHERE country_id = %s", [AR]
        )
    with rejected(errors.RestrictViolation, "country_codes_snapshot_coupled"):
        catalog.execute("UPDATE reference.country SET alpha2 = 'AX' WHERE country_id = %s", [AR])


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("previous_alpha2", "ar", "country_recoding_code_format"),
        ("new_alpha3", "AR", "country_recoding_code_format"),
        ("previous_numeric_code", "32", "country_recoding_code_format"),
        ("new_numeric_code", "0032", "country_recoding_code_format"),
    ],
)
def test_recoding_triples_have_the_code_formats(
    catalog: psycopg.Connection, column: str, value: str, constraint: str
) -> None:
    with rejected(errors.CheckViolation, constraint):
        insert(catalog, "country_recoding", recoding_row(AR, **{column: value}))


def test_a_recoding_must_change_at_least_one_code(catalog: psycopg.Connection) -> None:
    with rejected(errors.CheckViolation, "country_recoding_changes_code"):
        insert(catalog, "country_recoding", recoding_row(AR, new_alpha2="AR"))
    insert(catalog, "country_recoding", recoding_row(AR, new_alpha2="AR", new_alpha3="ARX"))


def test_a_recoding_needs_an_existing_country_and_snapshot(catalog: psycopg.Connection) -> None:
    with rejected(errors.ForeignKeyViolation, "country_recoding_country_fk"):
        insert(catalog, "country_recoding", recoding_row(str(uuid.uuid4())))
    with rejected(errors.ForeignKeyViolation, "country_recoding_snapshot_fk"):
        insert(catalog, "country_recoding", recoding_row(AR, snapshot_version=9))


# --- clasificación (RF-6, RF-48, CL-17) ---------------------------------------------------------


def test_classification_is_optional_and_a_subregion_implies_its_region(
    base: psycopg.Connection,
) -> None:
    insert(
        base,
        "country",
        country_row(
            alpha2="AQ", alpha3="ATA", numeric_code="010", region_id=None, subregion_id=None
        ),
    )
    insert(
        base,
        "country",
        country_row(
            alpha2="NA", alpha3="NAM", numeric_code="516", region_id=AFRICA, subregion_id=None
        ),
    )
    with rejected(errors.CheckViolation, "country_subregion_requires_region"):
        insert(
            base,
            "country",
            country_row(
                alpha2="BR", alpha3="BRA", numeric_code="076", region_id=None, subregion_id=LATAM
            ),
        )


def test_the_region_and_the_pair_must_exist_and_be_coherent(base: psycopg.Connection) -> None:
    with rejected(errors.ForeignKeyViolation, "country_region_fk"):
        insert(base, "country", country_row(region_id=str(uuid.uuid4()), subregion_id=None))
    with rejected(errors.ForeignKeyViolation, "country_classification_fk"):
        insert(base, "country", country_row(region_id=AFRICA, subregion_id=LATAM))
    with rejected(errors.ForeignKeyViolation, "country_classification_fk"):
        insert(base, "country", country_row(region_id=AMERICAS, subregion_id=str(uuid.uuid4())))
    insert(base, "country", country_row())


def test_a_reclassification_that_leaves_a_country_incoherent_is_rejected(
    catalog: psycopg.Connection,
) -> None:
    with rejected(errors.ForeignKeyViolation, "country_classification_fk"):
        catalog.execute(
            "UPDATE reference.subregion SET region_id = %s WHERE subregion_id = %s",
            [AFRICA, LATAM],
        )
    region = catalog.execute(
        "SELECT region_id::text FROM reference.subregion WHERE subregion_id = %s", [LATAM]
    ).fetchone()
    assert region == (AMERICAS,)


def test_a_reclassification_fixed_in_the_same_transaction_is_accepted(
    catalog: psycopg.Connection,
) -> None:
    with catalog.transaction():
        catalog.execute(
            "UPDATE reference.subregion SET region_id = %s WHERE subregion_id = %s",
            [AFRICA, LATAM],
        )
        catalog.execute(
            "UPDATE reference.country SET region_id = %s WHERE country_id = %s", [AFRICA, AR]
        )
    pair = catalog.execute(
        "SELECT region_id::text, subregion_id::text FROM reference.country WHERE country_id = %s",
        [AR],
    ).fetchone()
    assert pair == (AFRICA, LATAM)


def test_unrelated_changes_of_regions_do_not_touch_countries(catalog: psycopg.Connection) -> None:
    catalog.execute(
        "UPDATE reference.region SET code = '020', code_snapshot_version = 1 WHERE region_id = %s",
        [AMERICAS],
    )
    catalog.execute("UPDATE reference.subregion SET status = 'inactive'")


# --- estado y reemplazo (RF-39, RF-40) ----------------------------------------------------------


def test_status_is_active_or_inactive_only(base: psycopg.Connection) -> None:
    for status in ("enabled", "ACTIVE", "", "deprecated"):
        with rejected(errors.CheckViolation, "country_status_valid"):
            insert(base, "country", country_row(status=status))


def test_replacement_rules(catalog: psycopg.Connection) -> None:
    with rejected(errors.CheckViolation, "country_replacement_requires_inactive"):
        insert(
            catalog,
            "country",
            country_row(alpha2="BR", alpha3="BRA", numeric_code="076", replacement_country_id=AR),
        )
    own = str(uuid.uuid4())
    with rejected(errors.CheckViolation, "country_replacement_not_self"):
        insert(
            catalog,
            "country",
            country_row(
                country_id=own,
                alpha2="BR",
                alpha3="BRA",
                numeric_code="076",
                status="inactive",
                replacement_country_id=own,
            ),
        )
    with rejected(errors.ForeignKeyViolation, "country_replacement_fk"):
        insert(
            catalog,
            "country",
            country_row(
                alpha2="BR",
                alpha3="BRA",
                numeric_code="076",
                status="inactive",
                replacement_country_id=str(uuid.uuid4()),
            ),
        )
    insert(
        catalog,
        "country",
        country_row(
            alpha2="BR",
            alpha3="BRA",
            numeric_code="076",
            status="inactive",
            replacement_country_id=AR,
        ),
    )


def test_every_version_column_of_a_country_needs_an_incorporated_snapshot(
    base: psycopg.Connection,
) -> None:
    for column, constraint in (
        ("first_snapshot_version", "country_first_snapshot_fk"),
        ("codes_snapshot_version", "country_codes_snapshot_fk"),
        ("last_changed_snapshot_version", "country_last_changed_snapshot_fk"),
    ):
        with rejected(errors.ForeignKeyViolation, constraint):
            insert(base, "country", country_row(**{column: 9}))


# --- localizaciones (RF-31–RF-34) ---------------------------------------------------------------


def test_localizations_need_an_existing_country_and_locale(catalog: psycopg.Connection) -> None:
    with rejected(errors.ForeignKeyViolation, "country_locale_country_fk"):
        insert(
            catalog,
            "country_locale",
            {
                "country_id": str(uuid.uuid4()),
                "locale_id": LOCALE_ID,
                "name": "x",
                "official_name": None,
            },
        )
    with rejected(errors.ForeignKeyViolation, "country_locale_locale_fk"):
        insert(
            catalog,
            "country_locale",
            {"country_id": NA, "locale_id": str(uuid.uuid4()), "name": "x", "official_name": None},
        )


def test_one_localization_per_country_and_locale(catalog: psycopg.Connection) -> None:
    with rejected(errors.UniqueViolation, "country_locale_pkey"):
        insert(
            catalog,
            "country_locale",
            {"country_id": AR, "locale_id": LOCALE_ID, "name": "otro", "official_name": None},
        )


@pytest.mark.parametrize(
    "name", ["", " Argentina", "Argentina ", "\tArgentina", "Argentina\n", " "]
)
def test_names_are_not_empty_nor_padded(catalog: psycopg.Connection, name: str) -> None:
    with rejected(errors.CheckViolation, "country_locale_name_trimmed"):
        insert(
            catalog,
            "country_locale",
            {"country_id": NA, "locale_id": LOCALE_ID, "name": name, "official_name": None},
        )
    with rejected(errors.CheckViolation, "country_locale_name_trimmed"):
        catalog.execute("UPDATE reference.country_locale SET name = %s", [name])
    with rejected(errors.CheckViolation, "country_locale_official_name_trimmed"):
        insert(
            catalog,
            "country_locale",
            {"country_id": NA, "locale_id": LOCALE_ID, "name": "Namibia", "official_name": name},
        )


def test_official_name_is_optional_and_a_name_with_inner_spaces_is_valid(
    catalog: psycopg.Connection,
) -> None:
    insert(
        catalog,
        "country_locale",
        {
            "country_id": NA,
            "locale_id": LOCALE_ID,
            "name": "Costa de Marfil",
            "official_name": "República de Côte d'Ivoire",
        },
    )
    insert(
        catalog,
        "country_locale",
        {"country_id": NA, "locale_id": OTHER_LOCALE, "name": "Namibia", "official_name": None},
    )


# --- banderas (RF-19) ---------------------------------------------------------------------------


def flag(country_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "country_id": country_id,
        "asset_path": "ar.svg",
        "sha256": SHA,
        "exception_reason": None,
        "snapshot_version": 1,
    }
    return {**row, **overrides}


def test_a_flag_is_either_an_asset_reference_or_a_declared_exception(
    catalog: psycopg.Connection,
) -> None:
    insert(catalog, "country_flag", flag(AR))
    insert(
        catalog,
        "country_flag",
        flag(NA, asset_path=None, sha256=None, exception_reason="sin bandera oficial"),
    )
    declarations = (
        flag(AQ, exception_reason="ambas"),
        flag(AQ, asset_path=None, sha256=None, exception_reason=None),
        flag(AQ, sha256=None),
        flag(AQ, asset_path=None),
        flag(AQ, asset_path=None, sha256=SHA, exception_reason="x"),
        flag(AQ, asset_path=None, sha256=None, exception_reason=""),
        flag(AQ, asset_path=None, sha256=None, exception_reason=" motivo"),
    )
    for row in declarations:
        with pytest.raises(errors.CheckViolation):
            insert(catalog, "country_flag", row)


@pytest.mark.parametrize(
    "path", ["../ar.svg", "/ar.svg", "a//b.svg", "ar.png", "ar", "a\\b.svg", "x/../y.svg", ".svg"]
)
def test_the_asset_path_is_relative_without_traversal(
    catalog: psycopg.Connection, path: str
) -> None:
    with rejected(errors.CheckViolation, "country_flag_asset_path_format"):
        insert(catalog, "country_flag", flag(AR, asset_path=path))
    insert(catalog, "country_flag", flag(AR, asset_path="4x3/ar.svg"))


@pytest.mark.parametrize("digest", ["abc", "sha256:" + "E" * 64, "sha256:" + "e" * 63, "e" * 64])
def test_the_checksum_is_a_lowercase_sha256_digest(
    catalog: psycopg.Connection, digest: str
) -> None:
    with rejected(errors.CheckViolation, "country_flag_sha256_format"):
        insert(catalog, "country_flag", flag(AR, sha256=digest))


def test_one_flag_declaration_per_country_and_it_needs_country_and_snapshot(
    catalog: psycopg.Connection,
) -> None:
    insert(catalog, "country_flag", flag(AR))
    with rejected(errors.UniqueViolation, "country_flag_pkey"):
        insert(catalog, "country_flag", flag(AR, asset_path="b.svg"))
    with rejected(errors.ForeignKeyViolation, "country_flag_country_fk"):
        insert(catalog, "country_flag", flag(str(uuid.uuid4())))
    with rejected(errors.ForeignKeyViolation, "country_flag_snapshot_fk"):
        insert(catalog, "country_flag", flag(NA, snapshot_version=9))


def test_a_flag_can_change_from_exception_to_asset_and_back(catalog: psycopg.Connection) -> None:
    insert(catalog, "country_flag", flag(AR, asset_path=None, sha256=None, exception_reason="x"))
    catalog.execute(
        "UPDATE reference.country_flag SET asset_path = 'ar.svg', sha256 = %s, "
        "exception_reason = NULL, snapshot_version = 2 WHERE country_id = %s",
        [SHA, AR],
    )
    catalog.execute(
        "UPDATE reference.country_flag SET asset_path = NULL, sha256 = NULL, "
        "exception_reason = 'otra', snapshot_version = 2 WHERE country_id = %s",
        [AR],
    )


# --- inmutabilidad (RF-2, RF-7, RF-21, RNF-5) ---------------------------------------------------


@pytest.fixture
def full(catalog: psycopg.Connection) -> psycopg.Connection:
    insert(catalog, "country_flag", flag(AR))
    with catalog.transaction():
        catalog.execute(
            "UPDATE reference.country SET alpha2 = 'AX', codes_snapshot_version = 2 "
            "WHERE country_id = %s",
            [AR],
        )
        insert(catalog, "country_recoding", recoding_row(AR))
    return catalog


@pytest.mark.parametrize("table", CATALOG)
def test_catalog_rows_are_never_deleted_nor_truncated(full: psycopg.Connection, table: str) -> None:
    with rejected(errors.RestrictViolation):
        full.execute(sql.SQL("DELETE FROM reference.{}").format(sql.Identifier(table)))
    with pytest.raises(TRUNCATE_REJECTIONS):
        full.execute(sql.SQL("TRUNCATE reference.{}").format(sql.Identifier(table)))
    with rejected(errors.RestrictViolation):
        full.execute(sql.SQL("TRUNCATE reference.{} CASCADE").format(sql.Identifier(table)))
    count = full.execute(
        sql.SQL("SELECT count(*) FROM reference.{}").format(sql.Identifier(table))
    ).fetchone()
    assert count is not None and count[0] >= 1


@pytest.mark.parametrize("table", HISTORY)
def test_history_is_immutable(full: psycopg.Connection, table: str) -> None:
    identifier = sql.Identifier(table)
    column = "content_digest" if table == "country_snapshot" else "snapshot_version"
    value = "'x'" if table == "country_snapshot" else "1"
    with rejected(errors.RestrictViolation):
        full.execute(
            sql.SQL("UPDATE reference.{} SET {} = " + value).format(
                identifier, sql.Identifier(column)
            )
        )
    with rejected(errors.RestrictViolation):
        full.execute(sql.SQL("DELETE FROM reference.{}").format(identifier))
    with pytest.raises(TRUNCATE_REJECTIONS):
        full.execute(sql.SQL("TRUNCATE reference.{}").format(identifier))
    with rejected(errors.RestrictViolation):
        full.execute(sql.SQL("TRUNCATE reference.{} CASCADE").format(identifier))


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("country", "country_id", str(uuid.uuid4())),
        ("country", "first_snapshot_version", 2),
        ("country_locale", "country_id", NA),
        ("country_locale", "locale_id", OTHER_LOCALE),
        ("country_flag", "country_id", NA),
    ],
)
def test_identity_columns_are_immutable(
    full: psycopg.Connection, table: str, column: str, value: Any
) -> None:
    with rejected(errors.RestrictViolation):
        full.execute(
            sql.SQL("UPDATE reference.{} SET {} = %s").format(
                sql.Identifier(table), sql.Identifier(column)
            ),
            [value],
        )


def test_status_replacement_classification_calling_code_names_and_flags_are_mutable(
    catalog: psycopg.Connection,
) -> None:
    insert(catalog, "country_flag", flag(AR))
    with catalog.transaction():
        catalog.execute(
            "UPDATE reference.country SET status = 'inactive', replacement_country_id = %s, "
            "region_id = NULL, subregion_id = NULL, calling_code = '55', "
            "last_changed_snapshot_version = 2 WHERE country_id = %s",
            [NA, AR],
        )
        catalog.execute(
            "UPDATE reference.country_locale SET name = 'República Argentina', "
            "official_name = 'La República Argentina'"
        )
        catalog.execute("UPDATE reference.country_flag SET snapshot_version = 2")
    catalog.execute(
        "UPDATE reference.country SET status = 'active', replacement_country_id = NULL, "
        "last_changed_snapshot_version = 2 WHERE country_id = %s",
        [AR],
    )


# --- privilegios (RNF-3) ------------------------------------------------------------------------


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


@pytest.mark.parametrize("role", ["anon", "authenticated", "public"])
def test_api_roles_and_public_have_no_usage_on_the_schema(
    conn: psycopg.Connection, role: str
) -> None:
    usage = conn.execute("SELECT has_schema_privilege(%s, 'reference', 'USAGE')", [role])
    assert usage.fetchone() == (False,)


def test_reader_can_select_but_not_write(full: psycopg.Connection) -> None:
    for _ in as_role(full, "reference_reader"):
        for table in COLUMNS:
            full.execute(sql.SQL("SELECT * FROM reference.{}").format(sql.Identifier(table)))
        with rejected(errors.InsufficientPrivilege):
            insert(full, "country", country_row(alpha2="BR", alpha3="BRA", numeric_code="076"))
        with rejected(errors.InsufficientPrivilege):
            full.execute("UPDATE reference.country SET status = 'inactive'")
        with rejected(errors.InsufficientPrivilege):
            full.execute("UPDATE reference.country_locale SET name = 'z'")
        with rejected(errors.InsufficientPrivilege):
            full.execute("DELETE FROM reference.country_flag")


def test_loader_can_load_but_not_alter_identity_history_or_delete(base: psycopg.Connection) -> None:
    for _ in as_role(base, "reference_loader"):
        insert(base, "country_snapshot", country_snapshot_row(snapshot_version=2))
        insert(base, "country", country_row(country_id=AR))
        insert(
            base,
            "country_locale",
            {"country_id": AR, "locale_id": LOCALE_ID, "name": "Argentina", "official_name": None},
        )
        insert(base, "country_flag", flag(AR))
        base.execute(
            "UPDATE reference.country SET status = 'inactive', calling_code = '55', "
            "last_changed_snapshot_version = 2"
        )
        base.execute("UPDATE reference.country_locale SET name = 'y', official_name = 'z'")
        base.execute("UPDATE reference.country_flag SET snapshot_version = 2")
        with rejected(errors.InsufficientPrivilege):
            base.execute("UPDATE reference.country SET first_snapshot_version = 2")
        with rejected(errors.InsufficientPrivilege):
            base.execute("UPDATE reference.country SET country_id = gen_random_uuid()")
        with rejected(errors.InsufficientPrivilege):
            base.execute("UPDATE reference.country_locale SET locale_id = %s", [OTHER_LOCALE])
        with rejected(errors.InsufficientPrivilege):
            base.execute("UPDATE reference.country_snapshot SET content_digest = 'x'")
        with rejected(errors.InsufficientPrivilege):
            base.execute("DELETE FROM reference.country_locale")
        with rejected(errors.InsufficientPrivilege):
            base.execute("TRUNCATE reference.country_recoding")


def test_loader_reads_what_the_incorporation_validates_against(base: psycopg.Connection) -> None:
    for _ in as_role(base, "reference_loader"):
        for table in ("locale", "locale_snapshot", "region", "subregion", "region_snapshot"):
            base.execute(sql.SQL("SELECT 1 FROM reference.{}").format(sql.Identifier(table)))


# --- downgrade ----------------------------------------------------------------------------------


def test_downgrade_to_0002_removes_only_the_countries_tables(database_url: str) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "0002")
    with psycopg.connect(database_url, autocommit=True) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'reference'"
            ).fetchall()
        }
        functions = conn.execute(
            "SELECT count(*) FROM pg_proc WHERE pronamespace = 'reference'::regnamespace "
            "AND proname LIKE '%%country%%'"
        ).fetchone()
    assert tables.isdisjoint(COLUMNS)
    assert {"locale", "locale_snapshot", "region", "subregion", "region_snapshot"} <= tables
    assert functions == (0,)
    command.upgrade(config, "head")
