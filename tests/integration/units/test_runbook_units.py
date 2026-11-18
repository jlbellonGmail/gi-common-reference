"""T10: los bloques SQL de `docs/operacion.md` para Units existen y se ejecutan (RF-46, RNF-2)."""

from collections.abc import Callable

import psycopg
import pytest

from gi_common_reference.bootstrap import (
    postgres_repository,
    postgres_units_repository,
    units_required_locales,
    units_ucum_table,
)
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.units.application.incorporate import Outcome, incorporate_snapshot
from tests.fixtures.regions import locale_snapshot
from tests.fixtures.units_variants import SACK_ID, sack_snapshot
from tests.integration.test_runbook import BLOCK, RUNBOOK, runbook_sql

BLOCKS = {"units_snapshots", "units_versions"}


@pytest.fixture
def traced(database_factory: Callable[[], str]) -> str:
    """Locale sembrado y dos versiones de Units: `sack` = 60 kg en la 1 y 50 kg en la 2."""
    url = database_factory()
    incorporate_locales(locale_snapshot(1), postgres_repository(url))
    for document in (sack_snapshot(1, factor="60"), sack_snapshot(2, factor="50")):
        result = incorporate_snapshot(
            document, postgres_units_repository(url), units_required_locales(), units_ucum_table()
        )
        assert result.outcome is Outcome.INCORPORATED, result.violations
    return url


def rows(url: str, block: str) -> list[tuple[object, ...]]:
    with psycopg.connect(url) as conn:
        return list(conn.execute(runbook_sql(block)).fetchall())


def test_the_runbook_has_the_units_blocks() -> None:
    assert BLOCKS <= {name for name, _ in BLOCK.findall(RUNBOOK)}


def test_the_documented_snapshot_trace_lists_every_version(traced: str) -> None:
    snapshots = rows(traced, "units_snapshots")
    # (versión, Locale, política, tabla UCUM)
    assert [(r[0], r[2], r[3], r[4]) for r in snapshots] == [(1, 1, 1, "2.2"), (2, 1, 1, "2.2")]
    assert all(str(r[1]).startswith("sha256:") for r in snapshots)


def test_the_documented_version_query_shows_the_changed_factor(traced: str) -> None:
    sack = [r for r in rows(traced, "units_versions") if str(r[0]) == SACK_ID]
    assert [(r[4], r[5], r[7], r[8], r[9]) for r in sack] == [("mass", "50", "active", 1, 2)]
