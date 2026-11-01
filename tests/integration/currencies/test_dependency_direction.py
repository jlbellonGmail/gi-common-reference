"""004: dirección de las dependencias entre catálogos, verificada en el esquema real (RNF-6, D-16).

Garantías: Locale no depende de Regions, Countries ni Currency; Regions no dependen de Countries ni
de Currency; Countries no depende de Currency; Currency y CountryCurrency sí consumen `country_id`
de Countries. Esta prueba pertenece a 004: no toca ni relaja ninguna prueba de 001–003.
"""

import re
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[3]
LOCALES = {"locale_snapshot", "locale", "locale_alias"}
REGIONS = {
    "region_snapshot",
    "region",
    "subregion",
    "region_locale",
    "subregion_locale",
    "subregion_reclassification",
    "region_recoding",
    "subregion_recoding",
}
COUNTRIES = {"country_snapshot", "country", "country_locale", "country_flag", "country_recoding"}
CURRENCIES = {"currency_snapshot", "currency", "currency_locale", "country_currency"}


def edges(conn: psycopg.Connection) -> set[tuple[str, str]]:
    rows = conn.execute(
        "SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint "
        "WHERE contype = 'f' AND connamespace = 'reference'::regnamespace"
    ).fetchall()
    return {(a.removeprefix("reference."), b.removeprefix("reference.")) for a, b in rows}


def targets(conn: psycopg.Connection, sources: set[str]) -> set[str]:
    return {target for source, target in edges(conn) if source in sources}


def test_every_table_belongs_to_exactly_one_catalog(conn: psycopg.Connection) -> None:
    found = {
        name
        for (name,) in conn.execute(
            "SELECT relname FROM pg_class WHERE relnamespace = 'reference'::regnamespace "
            "AND relkind IN ('r', 'p') AND relname <> 'alembic_version'"
        ).fetchall()
    }
    groups = (LOCALES, REGIONS, COUNTRIES, CURRENCIES)
    assert all(not (a & b) for i, a in enumerate(groups) for b in groups[i + 1 :])
    assert found == LOCALES | REGIONS | COUNTRIES | CURRENCIES


def test_004_owns_country_currency_and_currency_snapshot() -> None:
    created = {
        path.name: set(re.findall(r"CREATE TABLE reference\.(\w+)", path.read_text("utf-8")))
        for path in (ROOT / "migrations" / "versions").glob("000[1-4]_*.py")
    }
    owner = {table: name for name, tables in created.items() for table in tables}
    for table in CURRENCIES:
        assert owner[table].startswith("0004_"), table
    for table in LOCALES | REGIONS | COUNTRIES:
        assert not owner[table].startswith("0004_"), table


def test_locale_depends_on_nothing_but_locale(conn: psycopg.Connection) -> None:
    assert targets(conn, LOCALES) <= LOCALES


def test_regions_depend_on_locale_and_regions_only(conn: psycopg.Connection) -> None:
    assert targets(conn, REGIONS) <= LOCALES | REGIONS


def test_countries_do_not_depend_on_currency(conn: psycopg.Connection) -> None:
    assert targets(conn, COUNTRIES) <= LOCALES | REGIONS | COUNTRIES
    assert not targets(conn, COUNTRIES) & CURRENCIES


def test_nothing_from_001_to_003_references_currency_at_the_schema_level(
    conn: psycopg.Connection,
) -> None:
    """Ni FK, ni triggers, ni vistas, ni funciones de 001–003 mencionan Currency."""
    assert not {s for s, t in edges(conn) if t in CURRENCIES and s not in CURRENCIES}
    older = LOCALES | REGIONS | COUNTRIES
    functions = conn.execute(
        "SELECT c.relname, pg_get_functiondef(t.tgfoid) FROM pg_trigger t "
        "JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE NOT t.tgisinternal AND c.relnamespace = 'reference'::regnamespace"
    ).fetchall()
    leaking = [t for t, body in functions if t in older and "currenc" in body.lower()]
    assert leaking == []
    views = conn.execute(
        "SELECT viewname, definition FROM pg_views WHERE schemaname = 'reference'"
    ).fetchall()
    assert [name for name, _ in views] == ["country_currency_integrity_violation"]


def test_currency_consumes_country_id_from_countries(conn: psycopg.Connection) -> None:
    graph = edges(conn)
    assert ("country_currency", "country") in graph
    assert ("country_currency", "currency") in graph
    assert ("currency_snapshot", "country_snapshot") in graph
    assert ("currency_snapshot", "locale_snapshot") in graph
    assert targets(conn, CURRENCIES) <= CURRENCIES | COUNTRIES | LOCALES


def test_no_inverse_dependency_exists_in_the_sources() -> None:
    """Los módulos 001–003 no importan Currency (la arquitectura declarada lo prohíbe)."""
    package = ROOT / "src" / "gi_common_reference"
    for module in ("locales", "regions", "countries"):
        for path in (package / module).rglob("*.py"):
            text = path.read_text("utf-8")
            assert "gi_common_reference.currencies" not in text, path
            assert not re.search(r"^\s*(from|import)\s+.*\bcurrenc", text, re.MULTILINE), path
