"""T9: lo que `docs/operacion.md` documenta para Regions existe y se ejecuta de verdad
(RF-20, RF-34, RF-38, RNF-5, RNF-7)."""

import uuid
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from gi_common_reference.bootstrap import (
    postgres_region_repository,
    postgres_repository,
    required_locales,
)
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.regions.application.incorporate import Outcome, incorporate_snapshot
from tests.fixtures.regions import (
    build_snapshot,
    locale_snapshot,
    recoding,
    region_id,
    subregion,
    subregion_id,
)
from tests.integration.test_runbook import BLOCK, RUNBOOK, runbook_sql

ROOT = Path(__file__).resolve().parents[2]
DEVELOPMENT = (ROOT / "docs" / "desarrollo.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.fixture
def traced(database_factory: Callable[[], str]) -> str:
    """Dos snapshots: el segundo reclasifica 419 y recodifica 021 → 456."""
    url = database_factory()
    incorporate_locales(locale_snapshot(1), postgres_repository(url))
    second = build_snapshot(
        2,
        subregions=[
            subregion("015"),
            subregion("202"),
            subregion("419", region_id=region_id("002")),
            subregion("021", code="456"),
        ],
        recodings=[recoding("subregion", "021", "021", "456")],
    )
    for document in (build_snapshot(1), second):
        result = incorporate_snapshot(document, postgres_region_repository(url), required_locales())
        assert result.outcome is Outcome.INCORPORATED, result.violations
    return url


def rows(url: str, block: str) -> list[tuple[object, ...]]:
    """Filas del bloque documentado, con los UUID como texto para compararlos."""
    with psycopg.connect(url) as conn:
        found = conn.execute(runbook_sql(block)).fetchall()
    return [tuple(str(v) if isinstance(v, uuid.UUID) else v for v in row) for row in found]


def test_the_runbook_has_the_regions_blocks() -> None:
    names = {name for name, _ in BLOCK.findall(RUNBOOK)}
    assert {"regions_snapshots", "regions_reclassifications", "regions_recodings"} <= names


def test_the_documented_trace_queries_return_what_was_incorporated(traced: str) -> None:
    snapshots = rows(traced, "regions_snapshots")
    assert [(row[0], row[2], row[3]) for row in snapshots] == [(1, 1, 1), (2, 1, 1)]
    assert rows(traced, "regions_reclassifications") == [
        (subregion_id("419"), region_id("019"), region_id("002"), 2)
    ]
    ((kind, entity_id, previous, new, version, provenance),) = rows(traced, "regions_recodings")
    assert (kind, entity_id, previous, new, version) == (
        "subregion",
        subregion_id("021"),
        "021",
        "456",
        2,
    )
    assert isinstance(provenance, dict) and provenance["source"]


def test_the_documented_regions_command_targets_a_runnable_module() -> None:
    assert "python -m gi_common_reference.regions.interfaces.cli incorporate" in RUNBOOK
    module = ROOT / "src" / "gi_common_reference" / "regions" / "interfaces" / "cli.py"
    assert 'if __name__ == "__main__":' in module.read_text(encoding="utf-8")


def test_the_runbook_documents_the_regions_api_and_contracts() -> None:
    for path in (
        "GET /v1/regions",
        "GET /v1/regions/{region_id}",
        "GET /v1/regions/by-code/{code}",
        "GET /v1/subregions",
        "GET /v1/subregions/{subregion_id}",
        "GET /v1/subregions/by-code/{code}",
        "contracts/regions-api.v1.openapi.json",
        "/v1/openapi/regions.json",
        "contracts/region-snapshot.v1.schema.json",
        "alembic downgrade 0001",
    ):
        assert path in RUNBOOK, path
    for path in (
        "contracts/regions-api.v1.openapi.json",
        "contracts/region-snapshot.v1.schema.json",
        "contracts/region-snapshot.v1.example.json",
    ):
        assert (ROOT / path).is_file(), path


def test_the_development_guide_and_readme_mention_the_regions_catalog() -> None:
    assert "region-snapshot.v1.schema.json" in DEVELOPMENT
    assert "sdd validate 002-regions-subregions" in DEVELOPMENT
    assert "python -m gi_common_reference.app regions" in DEVELOPMENT
    assert "/v1/regions" in README and "specs/002-regions-subregions" in README
