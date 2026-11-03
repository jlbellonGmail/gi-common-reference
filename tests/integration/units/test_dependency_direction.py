"""005: dirección de las dependencias de Units, verificada en el esquema real (RNF-5).

Units depende de Locale por `locale_id` y `locale_snapshot` y de nadie más; ni Locale, Regions,
Countries ni Currency conocen a Units.
"""

import psycopg

from tests.integration.currencies.test_dependency_direction import (
    COUNTRIES,
    CURRENCIES,
    LOCALES,
    REGIONS,
    edges,
    targets,
)

UNITS = {
    "unit_snapshot",
    "quantity_kind",
    "unit",
    "quantity_kind_unit",
    "quantity_kind_locale",
    "unit_locale",
}


def test_every_table_belongs_to_exactly_one_catalog_at_head(conn: psycopg.Connection) -> None:
    """Partición completa del schema en `head` (0005); la de 004 valida `0004`."""
    found = {
        row[0]
        for row in conn.execute(
            "SELECT relname FROM pg_class WHERE relnamespace = 'reference'::regnamespace "
            "AND relkind IN ('r', 'p') AND relname <> 'alembic_version'"
        ).fetchall()
    }
    groups = (LOCALES, REGIONS, COUNTRIES, CURRENCIES, UNITS)
    assert all(not (a & b) for i, a in enumerate(groups) for b in groups[i + 1 :])
    assert found == LOCALES | REGIONS | COUNTRIES | CURRENCIES | UNITS


def test_units_depend_on_locale_and_units_only(conn: psycopg.Connection) -> None:
    assert targets(conn, UNITS) <= UNITS | LOCALES
    assert {"locale", "locale_snapshot"} <= targets(conn, UNITS)


def test_no_earlier_catalog_references_units(conn: psycopg.Connection) -> None:
    older = LOCALES | REGIONS | COUNTRIES | CURRENCIES
    assert not {s for s, t in edges(conn) if t in UNITS and s in older}


def test_no_trigger_or_view_of_earlier_catalogs_mentions_units(conn: psycopg.Connection) -> None:
    older = LOCALES | REGIONS | COUNTRIES | CURRENCIES
    triggers = conn.execute(
        "SELECT c.relname, pg_get_functiondef(t.tgfoid) FROM pg_trigger t "
        "JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE NOT t.tgisinternal AND c.relnamespace = 'reference'::regnamespace"
    ).fetchall()
    leaking = [
        t for t, body in triggers if t in older and ("quantity_kind" in body or "uom_" in body)
    ]
    assert leaking == []
    views = conn.execute(
        "SELECT viewname, definition FROM pg_views WHERE schemaname = 'reference'"
    ).fetchall()
    assert [
        name for name, body in views if "quantity_kind" in body or "reference.unit" in body
    ] == []
