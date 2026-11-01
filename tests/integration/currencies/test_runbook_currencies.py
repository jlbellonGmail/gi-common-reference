"""T10: lo que `docs/operacion.md` documenta para Currency existe y se ejecuta de verdad
(RF-32, RF-41, RF-49, RNF-2, CA-14, CA-24)."""

import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path

import psycopg
import pytest

from gi_common_reference.bootstrap import (
    currency_required_locales,
    postgres_currency_repository,
    postgres_region_repository,
    postgres_repository,
    required_locales,
)
from gi_common_reference.currencies.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.regions.application.incorporate import (
    incorporate_snapshot as incorporate_regions,
)
from tests.fixtures.countries import regions_snapshot
from tests.fixtures.currencies import build_snapshot, currency_id, transition_snapshot
from tests.fixtures.regions import locale_snapshot
from tests.integration.currencies.test_incorporation import seed_countries
from tests.integration.test_runbook import BLOCK, RUNBOOK, runbook_sql

ROOT = Path(__file__).resolve().parents[3]
DEVELOPMENT = (ROOT / "docs" / "desarrollo.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
BLOCKS = {
    "currencies_snapshots",
    "currencies_versions",
    "currencies_history",
    "currencies_integrity",
}


@pytest.fixture
def traced(database_factory: Callable[[], str]) -> str:
    """Locale, Regions, Countries sembrado y los snapshots 1 y 2 (transición HRK → EUR)."""
    url = database_factory()
    incorporate_locales(locale_snapshot(1), postgres_repository(url))
    incorporate_regions(regions_snapshot(1), postgres_region_repository(url), required_locales())
    seed_countries(url)
    for document in (build_snapshot(1), transition_snapshot(2)):
        result = incorporate_snapshot(
            document, postgres_currency_repository(url), currency_required_locales()
        )
        assert result.outcome is Outcome.INCORPORATED, result.violations
    return url


def rows(url: str, block: str) -> list[tuple[object, ...]]:
    with psycopg.connect(url) as conn:
        found = conn.execute(runbook_sql(block)).fetchall()
    return [tuple(str(v) if isinstance(v, uuid.UUID) else v for v in row) for row in found]


def test_the_runbook_has_the_currency_blocks() -> None:
    assert BLOCKS <= {name for name, _ in BLOCK.findall(RUNBOOK)}


def test_the_documented_snapshot_trace_shows_the_locale_and_countries_versions_used(
    traced: str,
) -> None:
    snapshots = rows(traced, "currencies_snapshots")
    # (versión, Locale, Countries declarada, Countries vigente al incorporar, política)
    assert [(r[0], r[2], r[3], r[4], r[5]) for r in snapshots] == [(1, 1, 1, 1, 1), (2, 1, 1, 1, 1)]


def test_the_documented_version_query_tracks_each_currency(traced: str) -> None:
    by_code = {row[1]: row for row in rows(traced, "currencies_versions")}
    assert by_code["HRK"][2:5] == ("inactive", 1, 2)  # introducida en 1, último cambio en 2
    assert by_code["ARS"][2:5] == ("active", 1, 1)
    assert by_code["HRK"][0] == currency_id("HRK")


def test_the_documented_history_query_returns_the_closed_and_the_open_period(traced: str) -> None:
    assert [(r[0], r[1], r[2], r[3], r[4]) for r in rows(traced, "currencies_history")] == [
        ("HRK", "active", date(1994, 5, 30), date(2023, 1, 1), 1),
        ("EUR", "active", date(2023, 1, 1), None, 2),
    ]


def test_the_documented_integrity_query_is_empty_and_detects_drift(traced: str) -> None:
    assert rows(traced, "currencies_integrity") == []
    with psycopg.connect(traced, autocommit=True) as conn:
        conn.execute("UPDATE reference.country SET status = 'inactive' WHERE alpha2 = 'AR'")
    found = rows(traced, "currencies_integrity")
    assert len(found) == 1 and found[0][3:] == (True, False)


def test_the_documented_commands_target_a_runnable_module() -> None:
    for command in ("incorporate", "diff", "check-integrity"):
        assert f"python -m gi_common_reference.currencies.interfaces.cli {command}" in RUNBOOK
    module = ROOT / "src" / "gi_common_reference" / "currencies" / "interfaces" / "cli.py"
    assert 'if __name__ == "__main__":' in module.read_text(encoding="utf-8")


def test_the_runbook_documents_the_currency_api_migration_and_contracts() -> None:
    for text in (
        "GET /v1/currencies",
        "GET /v1/currencies/{currency_id}",
        "GET /v1/currencies/by-code/{code}",
        "GET /v1/currencies/by-country/{country_id}",
        "/validation",
        "/countries/history",
        "contracts/currencies-api.v1.openapi.json",
        "/v1/openapi/currencies.json",
        "contracts/currency-snapshot.v1.schema.json",
        "alembic downgrade 0003",
        "migración 0004",
        "btree_gist",
        "check-integrity",
        "gi_common_reference.currencies.interfaces.http",
        "`status` y vigencia son independientes",
        "La historia no se reescribe",
    ):
        assert text in RUNBOOK, text
    for path in (
        "contracts/currencies-api.v1.openapi.json",
        "contracts/currency-snapshot.v1.schema.json",
        "contracts/currency-snapshot.v1.example.json",
    ):
        assert (ROOT / path).is_file(), path


def test_the_runbook_does_not_put_exchange_rates_or_markets_in_scope() -> None:
    section = RUNBOOK[RUNBOOK.index("## 9. Incorporar un snapshot de monedas") :]
    assert "tipos de cambio" not in section.lower() and "cotizacion" not in section.lower()


def test_the_development_guide_and_readme_mention_the_currency_catalog() -> None:
    assert "currency-snapshot.v1.schema.json" in DEVELOPMENT
    assert "sdd validate 004-currency" in DEVELOPMENT
    assert "python -m gi_common_reference.app currencies" in DEVELOPMENT
    assert "tools/acceptance/currency_acceptance.py" in DEVELOPMENT
    assert "/v1/currencies" in README and "specs/004-currency" in README
    assert "currency_id" in README and "vigencia" in README
