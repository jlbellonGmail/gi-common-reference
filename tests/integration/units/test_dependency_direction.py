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
    UNITS,
    edges,
    targets,
)


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
