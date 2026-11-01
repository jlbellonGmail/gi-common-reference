"""T10: lo que `docs/operacion.md` documenta para Countries existe y se ejecuta de verdad
(RF-16, RF-30, RF-46, RF-47, RNF-2, RNF-10)."""

import uuid
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from gi_common_reference.bootstrap import (
    postgres_country_repository,
    postgres_region_repository,
    postgres_repository,
    required_locales,
)
from gi_common_reference.countries.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.countries.infrastructure.flag_store import DirectoryFlagStore
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.regions.application.incorporate import (
    incorporate_snapshot as incorporate_regions,
)
from tests.fixtures.countries import (
    FLAGS_DIR,
    POLICY,
    build_snapshot,
    country,
    country_id,
    flag,
    flag_exception,
    names,
    recoding,
    regions_snapshot,
)
from tests.fixtures.regions import locale_snapshot
from tests.integration.test_runbook import BLOCK, RUNBOOK, runbook_sql

ROOT = Path(__file__).resolve().parents[2]
DEVELOPMENT = (ROOT / "docs" / "desarrollo.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
BASE = ("AR", "NA", "AQ", "TW", "US", "CA", "PR", "BV")


@pytest.fixture
def traced(database_factory: Callable[[], str]) -> str:
    """Locale 1, Regions 1 y 2, Countries 1 (declara Regions 1) y 2 (recodifica TP → TL)."""
    url = database_factory()
    incorporate_locales(locale_snapshot(1), postgres_repository(url))
    for version in (1, 2):
        incorporate_regions(
            regions_snapshot(version), postgres_region_repository(url), required_locales()
        )
    second = build_snapshot(
        2,
        countries=[*(country(k) for k in BASE), country("TL", identity="TP")],
        country_names=[*(n for k in BASE for n in names(k)), *names("TP")],
        flags=[*(flag(k) for k in BASE if k not in ("AQ", "BV")), flag("TP")],
        flag_exceptions=[flag_exception("AQ"), flag_exception("BV")],
        recodings=[recoding("TP", ("TP", "TMP", "626"), ("TL", "TLS", "626"))],
        region_snapshot_version=2,
    )
    store = DirectoryFlagStore(FLAGS_DIR)
    for document in (build_snapshot(1, keys=(*BASE, "TP")), second):
        result = incorporate_snapshot(document, postgres_country_repository(url), POLICY, store)
        assert result.outcome is Outcome.INCORPORATED, result.violations
    return url


def rows(url: str, block: str) -> list[tuple[object, ...]]:
    """Filas del bloque documentado, con los UUID como texto para compararlos."""
    with psycopg.connect(url) as conn:
        found = conn.execute(runbook_sql(block)).fetchall()
    return [tuple(str(v) if isinstance(v, uuid.UUID) else v for v in row) for row in found]


def test_the_runbook_has_the_countries_blocks() -> None:
    names_ = {name for name, _ in BLOCK.findall(RUNBOOK)}
    assert {"countries_snapshots", "countries_recodings", "countries_versions"} <= names_


def test_the_documented_snapshot_trace_shows_the_locale_and_regions_versions_used(
    traced: str,
) -> None:
    snapshots = rows(traced, "countries_snapshots")
    # (versión, Locale, Regions declarada, Regions vigente al incorporar, política)
    assert [(r[0], r[2], r[3], r[4], r[5]) for r in snapshots] == [(1, 1, 1, 2, 1), (2, 1, 2, 2, 1)]


def test_the_documented_recoding_trace_returns_what_was_incorporated(traced: str) -> None:
    ((cid, version, *codes, provenance),) = rows(traced, "countries_recodings")
    assert (cid, version) == (country_id("TP"), 2)
    assert codes == ["TP", "TMP", "626", "TL", "TLS", "626"]
    assert isinstance(provenance, dict) and provenance["source"]


def test_the_documented_version_query_tracks_each_country(traced: str) -> None:
    by_code = {row[1]: row for row in rows(traced, "countries_versions")}
    assert by_code["TL"][3:6] == (1, 2, 2)  # introducido en 1, códigos de 2, último cambio 2
    assert by_code["AR"][3:6] == (1, 1, 1)
    assert "TP" not in by_code  # el código histórico ya no es el vigente


def test_the_documented_commands_target_a_runnable_module() -> None:
    assert "python -m gi_common_reference.countries.interfaces.cli incorporate" in RUNBOOK
    assert "python -m gi_common_reference.countries.interfaces.cli diff" in RUNBOOK
    module = ROOT / "src" / "gi_common_reference" / "countries" / "interfaces" / "cli.py"
    assert 'if __name__ == "__main__":' in module.read_text(encoding="utf-8")


def test_the_runbook_documents_the_countries_api_migration_assets_and_contracts() -> None:
    for text in (
        "GET /v1/countries",
        "GET /v1/countries/{country_id}",
        "GET /v1/countries/by-alpha2/{code}",
        "GET /v1/countries/by-alpha3/{code}",
        "GET /v1/countries/by-numeric/{code}",
        "GET /v1/countries/{country_id}/flag",
        "contracts/countries-api.v1.openapi.json",
        "/v1/openapi/countries.json",
        "contracts/country-snapshot.v1.schema.json",
        "alembic downgrade 0002",
        "src/gi_common_reference/countries/assets/flags/",
        "image/svg+xml",
        "sha256",
        "migración 0003",
        "gi_common_reference.countries.interfaces.http",
    ):
        assert text in RUNBOOK, text
    for path in (
        "contracts/countries-api.v1.openapi.json",
        "contracts/country-snapshot.v1.schema.json",
        "contracts/country-snapshot.v1.example.json",
    ):
        assert (ROOT / path).is_file(), path


def test_the_development_guide_and_readme_mention_the_countries_catalog() -> None:
    assert "country-snapshot.v1.schema.json" in DEVELOPMENT
    assert "sdd validate 003-countries" in DEVELOPMENT
    assert "python -m gi_common_reference.app countries" in DEVELOPMENT
    assert "/v1/countries" in README and "specs/003-countries" in README
    assert "country_id" in README
