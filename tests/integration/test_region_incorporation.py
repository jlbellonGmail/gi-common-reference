"""T7: incorporación de Regions contra Postgres real (RF-6, RF-21, RF-24–RF-26, RF-34, RF-35,
RF-37–RF-39, RNF-1, RNF-2, RNF-5)."""

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from gi_common_reference.bootstrap import (
    postgres_region_repository,
    postgres_repository,
    read_region_snapshot,
    required_locales,
)
from gi_common_reference.locales.application.incorporate import (
    Outcome as LocaleOutcome,
)
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.regions.application.incorporate import (
    IncorporationResult,
    Outcome,
    incorporate_snapshot,
)
from gi_common_reference.regions.domain.digest import content_digest_matches
from gi_common_reference.regions.interfaces.cli import main
from tests.conftest import NetworkGuard
from tests.fixtures.regions import (
    FR,
    build_snapshot,
    locale_snapshot,
    reassignment,
    recoding,
    region,
    region_id,
    seal,
    subregion,
    subregion_id,
)

ROOT = Path(__file__).resolve().parents[2]
TABLES = {
    "region_snapshot": "snapshot_version, content_digest, locale_snapshot_version, "
    "required_locales_version, provenance, artifact",
    "region": "region_id::text, code, code_snapshot_version, status, "
    "replacement_region_id::text, first_snapshot_version",
    "subregion": "subregion_id::text, region_id::text, code, code_snapshot_version, status, "
    "replacement_subregion_id::text, first_snapshot_version",
    "region_locale": "region_id::text, locale_id::text, name",
    "subregion_locale": "subregion_id::text, locale_id::text, name",
    "subregion_reclassification": "subregion_id::text, snapshot_version, "
    "previous_region_id::text, new_region_id::text",
    "region_recoding": "region_id::text, snapshot_version, previous_code, new_code, provenance",
    "subregion_recoding": "subregion_id::text, snapshot_version, previous_code, new_code, "
    "provenance",
}


def subregions(**changes: dict[str, Any]) -> list[dict[str, Any]]:
    return [subregion(key, **changes.get(f"s{key}", {})) for key in ("015", "202", "419", "021")]


def incorporate(url: str, document: dict[str, Any]) -> IncorporationResult:
    return incorporate_snapshot(document, postgres_region_repository(url), required_locales())


def logical_state(url: str) -> dict[str, list[tuple[Any, ...]]]:
    with psycopg.connect(url) as conn:
        return {
            table: conn.execute(f"SELECT {columns} FROM reference.{table} ORDER BY 1, 2").fetchall()
            for table, columns in TABLES.items()
        }


@pytest.fixture
def ready(database_factory: Callable[[], str]) -> Callable[[], str]:
    """Bases nuevas con Locale ya incorporado (en, es, fr con los ids de la política)."""

    def create() -> str:
        url = database_factory()
        result = incorporate_locales(locale_snapshot(1), postgres_repository(url))
        assert result.outcome is LocaleOutcome.INCORPORATED
        return url

    return create


@pytest.fixture
def url(ready: Callable[[], str]) -> str:
    return ready()


# --- flujo básico ------------------------------------------------------------------------------


def test_the_first_snapshot_is_incorporated_with_its_ids_and_versions(url: str) -> None:
    result = incorporate(url, build_snapshot(1))
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.new_regions, result.new_subregions, result.locale_snapshot_version) == (2, 4, 1)
    state = logical_state(url)
    (snapshot,) = state["region_snapshot"]
    assert snapshot[:4] == (1, build_snapshot(1)["content_digest"], 1, 1)
    assert {row[0]: row[1] for row in state["region"]} == {
        region_id("002"): "002",
        region_id("019"): "019",
    }
    assert all(row[2] == 1 and row[5] == 1 for row in state["region"])
    assert len(state["region_locale"]) == 4 and len(state["subregion_locale"]) == 8


def test_the_stored_artifact_recalculates_its_digest(url: str) -> None:
    incorporate(url, build_snapshot(1))
    with psycopg.connect(url) as conn:
        row = conn.execute("SELECT artifact FROM reference.region_snapshot").fetchone()
    assert row is not None and content_digest_matches(row[0])


def test_resending_a_snapshot_is_a_noop(url: str) -> None:
    incorporate(url, build_snapshot(1))
    incorporate(url, build_snapshot(2, regions=[region("002"), region("019"), region("142")]))
    before = logical_state(url)
    assert incorporate(url, build_snapshot(1)).outcome is Outcome.NOOP
    assert logical_state(url) == before


def test_a_rejected_snapshot_leaves_the_catalog_identical(url: str) -> None:
    incorporate(url, build_snapshot(1))
    before = logical_state(url)
    result = incorporate(url, build_snapshot(2, subregions=subregions(s419={"code": "420"})))
    assert result.outcome is Outcome.REJECTED and {v.rule for v in result.violations} == {"RF-22"}
    assert logical_state(url) == before


def test_the_locale_version_in_force_is_recorded(url: str) -> None:
    incorporate(url, build_snapshot(1))
    incorporate_locales(locale_snapshot(4), postgres_repository(url))
    result = incorporate(
        url, build_snapshot(2, regions=[region("002"), region("019"), region("142")])
    )
    assert result.outcome is Outcome.INCORPORATED
    versions = [row[2] for row in logical_state(url)["region_snapshot"]]
    assert versions == [1, 4]


# --- reclasificación, recodificación, intercambio ---------------------------------------------


def test_a_reclassification_keeps_id_and_code_and_is_traced(url: str) -> None:
    incorporate(url, build_snapshot(1))
    result = incorporate(
        url, build_snapshot(2, subregions=subregions(s419={"region_id": region_id("002")}))
    )
    assert result.outcome is Outcome.INCORPORATED, result.violations
    state = logical_state(url)
    latam = next(row for row in state["subregion"] if row[0] == subregion_id("419"))
    assert (latam[1], latam[2], latam[3], latam[6]) == (region_id("002"), "419", 1, 1)
    assert state["subregion_reclassification"] == [
        (subregion_id("419"), 2, region_id("019"), region_id("002"))
    ]


def test_a_recoding_keeps_status_names_and_parent_and_is_traced(url: str) -> None:
    incorporate(url, build_snapshot(1))
    before = logical_state(url)
    declaration = recoding("subregion", "021", "021", "456")
    result = incorporate(
        url, build_snapshot(2, subregions=subregions(s021={"code": "456"}), recodings=[declaration])
    )
    assert result.outcome is Outcome.INCORPORATED, result.violations
    state = logical_state(url)
    row = next(r for r in state["subregion"] if r[0] == subregion_id("021"))
    old = next(r for r in before["subregion"] if r[0] == subregion_id("021"))
    assert (row[2], row[3]) == ("456", 2)
    assert (row[1], row[4], row[5], row[6]) == (old[1], old[4], old[5], old[6])
    assert state["subregion_locale"] == before["subregion_locale"]
    assert state["subregion_recoding"] == [
        (subregion_id("021"), 2, "021", "456", declaration["provenance"])
    ]


def test_a_declared_swap_of_codes_is_incorporated(url: str) -> None:
    incorporate(url, build_snapshot(1))
    document = build_snapshot(
        2,
        subregions=subregions(s419={"code": "021"}, s021={"code": "419"}),
        recodings=[
            recoding("subregion", "419", "419", "021"),
            recoding("subregion", "021", "021", "419"),
        ],
        code_reassignments=[
            reassignment("subregion", "419", "021"),
            reassignment("subregion", "021", "419"),
        ],
    )
    result = incorporate(url, document)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    codes = {row[0]: row[2] for row in logical_state(url)["subregion"]}
    assert codes[subregion_id("419")] == "021" and codes[subregion_id("021")] == "419"


def test_a_new_name_with_a_locale_that_became_inactive_is_rejected(url: str) -> None:
    incorporate(url, build_snapshot(1))
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE reference.locale SET status = 'inactive' WHERE locale_id = %s", [FR])
    document = build_snapshot(2)
    document["region_names"].append(
        {"region_id": region_id("019"), "locale_id": FR, "name": "Amériques"}
    )
    result = incorporate(url, seal(document))
    assert {v.rule for v in result.violations} == {"RF-33"}


# --- RF-35: catálogo dependiente --------------------------------------------------------------


def add_dependent(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE reference.test_country (id int PRIMARY KEY, region_id uuid NOT NULL, "
            "subregion_id uuid, CONSTRAINT test_country_pair_fk "
            "FOREIGN KEY (region_id, subregion_id) "
            "REFERENCES reference.subregion (region_id, subregion_id) "
            "DEFERRABLE INITIALLY DEFERRED)"
        )
        conn.execute(
            "INSERT INTO reference.test_country VALUES (1, %s, %s)",
            [region_id("019"), subregion_id("419")],
        )


def test_a_reclassification_that_leaves_a_dependent_incoherent_is_rejected(url: str) -> None:
    incorporate(url, build_snapshot(1))
    add_dependent(url)
    before = logical_state(url)
    result = incorporate(
        url, build_snapshot(2, subregions=subregions(s419={"region_id": region_id("002")}))
    )
    assert result.outcome is Outcome.REJECTED
    (violation,) = result.violations
    assert violation.rule == "RF-35" and "test_country_pair_fk" in violation.message
    assert logical_state(url) == before


# --- determinismo, red y CLI -------------------------------------------------------------------


def test_two_new_databases_reach_the_same_logical_state(ready: Callable[[], str]) -> None:
    first, second = ready(), ready()
    for document in (
        build_snapshot(1),
        build_snapshot(2, subregions=subregions(s419={"region_id": region_id("002")})),
    ):
        incorporate(first, document)
        incorporate(second, document)
    assert logical_state(first) == logical_state(second)


def test_the_cli_incorporates_without_network(
    url: str, tmp_path: Path, network_guard: NetworkGuard, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "regions.json"
    path.write_text(json.dumps(build_snapshot(1), ensure_ascii=False), encoding="utf-8")
    with network_guard:
        code = main(
            ["incorporate", str(path)],
            environ={"REFERENCE_DATABASE_URL": url},
            repository_factory=postgres_region_repository,
            snapshot_reader=read_region_snapshot,
            policy_loader=required_locales,
        )
    assert code == 0, capsys.readouterr().err
    assert "INCORPORADO snapshot_version=1" in capsys.readouterr().out
    assert network_guard.blocked == []


def test_the_cli_module_runs_as_documented_with_the_loader_role(url: str, tmp_path: Path) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("ALTER ROLE reference_loader LOGIN PASSWORD 'loader-pw'")
    loader = make_conninfo(url, user="reference_loader", password="loader-pw")
    path = tmp_path / "regions.json"
    path.write_text(json.dumps(build_snapshot(1), ensure_ascii=False), encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "gi_common_reference.regions.interfaces.cli",
        "incorporate",
        str(path),
    ]
    env = {**os.environ, "REFERENCE_DATABASE_URL": loader}
    done = subprocess.run(command, env=env, capture_output=True, text=True, cwd=ROOT, check=False)
    assert done.returncode == 0, done.stderr
    assert "INCORPORADO snapshot_version=1" in done.stdout
    again = subprocess.run(command, env=env, capture_output=True, text=True, cwd=ROOT, check=False)
    assert again.returncode == 0 and "NO-OP" in again.stdout


class _FailingAfterSnapshot:
    """Repositorio real cuya transacción falla justo después de escribir `region_snapshot`."""

    def __init__(self, url: str) -> None:
        self._inner = postgres_region_repository(url)

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with self._inner.transaction() as tx:

            def fail(*args: Any) -> None:
                raise RuntimeError("fallo inyectado")

            tx.insert_regions = fail  # type: ignore[method-assign,assignment]
            yield tx


def test_a_failure_after_writing_the_snapshot_row_leaves_nothing(url: str) -> None:
    with pytest.raises(RuntimeError):
        incorporate_snapshot(build_snapshot(1), _FailingAfterSnapshot(url), required_locales())
    assert all(rows == [] for rows in logical_state(url).values())
