"""T8: incorporación de Countries contra Postgres real.

RF-6, RF-20–RF-25, RF-30, RF-41, RF-44, RF-46–RF-48, RF-51, RNF-1, RNF-2, RNF-5, RNF-8.
"""

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
    country_flag_store,
    country_required_locales,
    postgres_country_repository,
    postgres_region_repository,
    postgres_repository,
    read_country_snapshot,
    required_locales,
)
from gi_common_reference.countries.application.incorporate import (
    IncorporationResult,
    Outcome,
    incorporate_snapshot,
)
from gi_common_reference.countries.domain.digest import content_digest_matches
from gi_common_reference.countries.infrastructure.flag_store import DirectoryFlagStore
from gi_common_reference.countries.interfaces.cli import main
from gi_common_reference.locales.application.incorporate import Outcome as LocaleOutcome
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.regions.application.incorporate import Outcome as RegionOutcome
from gi_common_reference.regions.application.incorporate import (
    incorporate_snapshot as incorporate_regions,
)
from tests.conftest import NetworkGuard
from tests.fixtures.countries import (
    FLAGS_DIR,
    build_snapshot,
    country,
    country_id,
    flag,
    flag_exception,
    names,
    reassignment,
    recoding,
    regions_snapshot,
    seal,
)
from tests.fixtures.regions import (
    locale_snapshot,
    region_id,
    subregion,
    subregion_id,
)
from tests.fixtures.regions import seal as seal_regions

ROOT = Path(__file__).resolve().parents[2]
BASE = ("AR", "NA", "AQ", "TW", "US", "CA", "PR", "BV")
TABLES = {
    "country_snapshot": "snapshot_version, content_digest, locale_snapshot_version, "
    "region_snapshot_version, region_current_snapshot_version, required_locales_version, "
    "provenance, artifact",
    "country": "country_id::text, alpha2, alpha3, numeric_code, region_id::text, "
    "subregion_id::text, calling_code, status, replacement_country_ids::text[], "
    "first_snapshot_version, codes_snapshot_version, last_changed_snapshot_version",
    "country_locale": "country_id::text, locale_id::text, name, official_name",
    "country_flag": "country_id::text, asset_path, sha256, exception_reason, snapshot_version",
    "country_recoding": "country_id::text, snapshot_version, previous_alpha2, previous_alpha3, "
    "previous_numeric_code, new_alpha2, new_alpha3, new_numeric_code, provenance",
}


def incorporate(url: str, document: dict[str, Any]) -> IncorporationResult:
    return incorporate_snapshot(
        document,
        postgres_country_repository(url),
        country_required_locales(),
        country_flag_store_dir(),
    )


def country_flag_store_dir() -> DirectoryFlagStore:
    return DirectoryFlagStore(FLAGS_DIR)


def logical_state(url: str) -> dict[str, list[tuple[Any, ...]]]:
    with psycopg.connect(url) as conn:
        return {
            table: conn.execute(f"SELECT {columns} FROM reference.{table} ORDER BY 1, 2").fetchall()
            for table, columns in TABLES.items()
        }


def row_of(state: dict[str, list[tuple[Any, ...]]], key: str) -> tuple[Any, ...]:
    return next(row for row in state["country"] if row[0] == country_id(key))


@pytest.fixture
def ready(database_factory: Callable[[], str]) -> Callable[[], str]:
    """Bases nuevas con Locale (en, es, fr) y Regions (002, 019, 142) ya incorporados."""

    def create() -> str:
        url = database_factory()
        assert (
            incorporate_locales(locale_snapshot(1), postgres_repository(url)).outcome
            is LocaleOutcome.INCORPORATED
        )
        result = incorporate_regions(
            regions_snapshot(1), postgres_region_repository(url), required_locales()
        )
        assert result.outcome is RegionOutcome.INCORPORATED, result.violations
        return url

    return create


@pytest.fixture
def url(ready: Callable[[], str]) -> str:
    return ready()


# --- flujo básico ------------------------------------------------------------------------------


def test_the_first_snapshot_registers_every_version_in_force(url: str) -> None:
    incorporate_regions(regions_snapshot(2), postgres_region_repository(url), required_locales())
    result = incorporate(url, build_snapshot(1, region_snapshot_version=1))
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.new_countries, result.locale_snapshot_version) == (8, 1)
    assert result.region_snapshot_version == 2
    state = logical_state(url)
    (snapshot,) = state["country_snapshot"]
    # (versión, digest, Locale, Regions declarada, Regions vigente, política)
    assert snapshot[:6] == (1, build_snapshot(1)["content_digest"], 1, 1, 2, 1)
    assert len(state["country"]) == 8 and len(state["country_locale"]) == 16
    assert len(state["country_flag"]) == 8 and state["country_recoding"] == []
    assert {row[1] for row in state["country"]} == set(BASE)
    assert all(row[9:12] == (1, 1, 1) for row in state["country"])


def test_na_and_leading_zero_codes_survive_end_to_end(url: str) -> None:
    keys = (*BASE, "AF")
    result = incorporate(url, build_snapshot(1, keys=keys))
    assert result.outcome is Outcome.INCORPORATED, result.violations
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT alpha2, alpha2 IS NULL, numeric_code FROM reference.country "
            "WHERE alpha2 IN ('NA', 'AF') ORDER BY alpha2"
        ).fetchall()
    assert rows == [("AF", False, "004"), ("NA", False, "516")]
    with psycopg.connect(url) as conn:
        row = conn.execute("SELECT artifact FROM reference.country_snapshot").fetchone()
    assert row is not None
    assert {c["numeric_code"] for c in row[0]["countries"]} >= {"004", "516"}


def test_the_stored_artifact_recalculates_its_digest(url: str) -> None:
    incorporate(url, build_snapshot(1))
    with psycopg.connect(url) as conn:
        row = conn.execute("SELECT artifact FROM reference.country_snapshot").fetchone()
    assert row is not None and content_digest_matches(row[0])


def test_resending_a_snapshot_is_a_noop(url: str) -> None:
    incorporate(url, build_snapshot(1))
    incorporate(url, build_snapshot(2, keys=(*BASE, "AF")))
    before = logical_state(url)
    assert incorporate(url, build_snapshot(1)).outcome is Outcome.NOOP
    assert incorporate(url, build_snapshot(2, keys=(*BASE, "AF"))).outcome is Outcome.NOOP
    assert logical_state(url) == before


def test_a_rejected_snapshot_leaves_the_catalog_identical(url: str) -> None:
    incorporate(url, build_snapshot(1))
    before = logical_state(url)
    omitted = incorporate(url, build_snapshot(2, keys=BASE[:-1]))
    assert omitted.outcome is Outcome.REJECTED
    assert {v.rule for v in omitted.violations} == {"RF-21"}
    silent_recode = incorporate(
        url,
        build_snapshot(
            2,
            countries=[country("AR", alpha2="AX"), *(country(k) for k in BASE if k != "AR")],
        ),
    )
    assert {v.rule for v in silent_recode.violations} == {"RF-42"}
    assert logical_state(url) == before


def test_a_snapshot_with_a_missing_flag_asset_is_rejected_atomically(url: str) -> None:
    incorporate(url, build_snapshot(1))
    before = logical_state(url)
    document = build_snapshot(2)
    document["flags"][0]["sha256"] = "sha256:" + "0" * 64
    result = incorporate(url, seal(document))
    assert result.outcome is Outcome.REJECTED and {v.rule for v in result.violations} == {"RF-49"}
    assert logical_state(url) == before


def test_the_locale_version_in_force_is_recorded(url: str) -> None:
    incorporate(url, build_snapshot(1))
    incorporate_locales(locale_snapshot(4), postgres_repository(url))
    assert incorporate(url, build_snapshot(2, keys=(*BASE, "AF"))).outcome is Outcome.INCORPORATED
    assert [row[2] for row in logical_state(url)["country_snapshot"]] == [1, 4]


# --- identidad, recodificación, intercambio, división y fusión ----------------------------------


def test_names_and_classification_change_without_changing_the_id(url: str) -> None:
    incorporate(url, build_snapshot(1))
    before = row_of(logical_state(url), "AR")
    renamed = names("AR")
    renamed[1] = {**renamed[1], "name": "La Argentina"}
    document = build_snapshot(
        2,
        countries=[
            country("AR", region_id=region_id("142"), subregion_id=subregion_id("035")),
            *(country(k) for k in BASE if k != "AR"),
        ],
        country_names=[*renamed, *(n for k in BASE if k != "AR" for n in names(k))],
    )
    result = incorporate(url, document)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    state = logical_state(url)
    after = row_of(state, "AR")
    assert after[0] == before[0] and after[1:4] == before[1:4]  # id y códigos
    assert after[5] == subregion_id("035") and after[9:12] == (1, 1, 2)
    assert "La Argentina" in {row[2] for row in state["country_locale"]}


def timor_v1() -> dict[str, Any]:
    return build_snapshot(1, keys=(*BASE, "TP"))


def timor_v2() -> dict[str, Any]:
    return build_snapshot(
        2,
        countries=[*(country(k) for k in BASE), country("TL", identity="TP")],
        country_names=[*(n for k in BASE for n in names(k)), *names("TP")],
        flags=[*(flag(k) for k in BASE if k not in ("AQ", "BV")), flag("TP")],
        flag_exceptions=[flag_exception("AQ"), flag_exception("BV")],
        recodings=[recoding("TP", ("TP", "TMP", "626"), ("TL", "TLS", "626"))],
    )


def test_a_recoding_keeps_id_status_and_names_and_is_traced(url: str) -> None:
    incorporate(url, timor_v1())
    before = logical_state(url)
    result = incorporate(url, timor_v2())
    assert result.outcome is Outcome.INCORPORATED, result.violations
    state = logical_state(url)
    old, new = row_of(before, "TP"), row_of(state, "TP")
    assert new[0] == old[0] and new[1:4] == ("TL", "TLS", "626")
    assert new[7] == old[7] == "active" and new[9:12] == (1, 2, 2)
    assert state["country_locale"] == before["country_locale"]
    ((cid, version, *codes, provenance),) = state["country_recoding"]
    assert (cid, version) == (country_id("TP"), 2)
    assert codes == ["TP", "TMP", "626", "TL", "TLS", "626"]
    assert provenance["source"] == "ISO 3166 Maintenance Agency"


def test_a_declared_swap_of_alpha2_is_incorporated_on_the_final_state(url: str) -> None:
    incorporate(url, build_snapshot(1))
    document = build_snapshot(
        2,
        countries=[
            country("AR", alpha2="NA"),
            country("NA", alpha2="AR"),
            *(country(k) for k in BASE if k not in ("AR", "NA")),
        ],
        recodings=[
            recoding("AR", ("AR", "ARG", "032"), ("NA", "ARG", "032")),
            recoding("NA", ("NA", "NAM", "516"), ("AR", "NAM", "516")),
        ],
        code_reassignments=[
            reassignment("AR", "alpha2", "NA"),
            reassignment("NA", "alpha2", "AR"),
        ],
    )
    result = incorporate(url, document)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    state = logical_state(url)
    assert row_of(state, "AR")[1] == "NA" and row_of(state, "NA")[1] == "AR"
    assert len(state["country_recoding"]) == 2


def test_the_database_enforces_the_trace_even_if_the_application_were_bypassed(url: str) -> None:
    incorporate(url, build_snapshot(1))
    with psycopg.connect(url, autocommit=True) as conn, pytest.raises(psycopg.Error):
        conn.execute("UPDATE reference.country SET alpha2 = 'XX', codes_snapshot_version = 1")


def successors_snapshot(version: int, successors: list[str]) -> dict[str, Any]:
    """AN `inactive` con los sucesores indicados (claves de país); CW, SX y BQ existen."""
    keys = (*BASE, "CW", "SX", "BQ")
    an = country(
        "AN", status="inactive", replacement_country_ids=[country_id(k) for k in successors]
    )
    return build_snapshot(
        version,
        countries=[*(country(k) for k in keys), an],
        country_names=[*(n for k in keys for n in names(k)), *names("AN")],
        flags=[*(flag(k) for k in keys if k not in ("AQ", "BV")), flag("AN")],
        flag_exceptions=[flag_exception("AQ"), flag_exception("BV")],
    )


def test_a_split_creates_new_ids_and_records_every_successor(url: str) -> None:
    """CL-12, CA-21: AN → CW, SX y BQ."""
    incorporate(url, build_snapshot(1, keys=(*BASE, "AN")))
    result = incorporate(url, successors_snapshot(2, ["SX", "CW", "BQ"]))
    assert result.outcome is Outcome.INCORPORATED, result.violations
    state = logical_state(url)
    an = row_of(state, "AN")
    assert (an[7], an[1]) == ("inactive", "AN")  # retirado: conserva id y códigos
    assert an[8] == sorted(country_id(k) for k in ("CW", "SX", "BQ"))
    assert {row_of(state, k)[1] for k in ("CW", "SX", "BQ")} == {"CW", "SX", "BQ"}
    assert len({row_of(state, k)[0] for k in ("CW", "SX", "BQ", "AN")}) == 4
    assert row_of(state, "AR")[8] == []


def test_a_merge_records_one_successor_and_a_retirement_none(url: str) -> None:
    incorporate(url, build_snapshot(1, keys=(*BASE, "AN")))
    assert incorporate(url, successors_snapshot(2, [])).outcome is Outcome.INCORPORATED
    assert row_of(logical_state(url), "AN")[8] == []
    result = incorporate(url, successors_snapshot(3, ["CW"]))
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert row_of(logical_state(url), "AN")[8] == [country_id("CW")]


def test_the_same_successors_in_another_order_are_a_noop_of_content(url: str) -> None:
    incorporate(url, build_snapshot(1, keys=(*BASE, "AN")))
    incorporate(url, successors_snapshot(2, ["SX", "CW", "BQ"]))
    before = logical_state(url)
    result = incorporate(url, successors_snapshot(3, ["BQ", "CW", "SX"]))
    assert result.outcome is Outcome.INCORPORATED and result.updated == 0
    after = logical_state(url)
    assert row_of(after, "AN")[8] == row_of(before, "AN")[8]
    assert row_of(after, "AN")[9:12] == row_of(before, "AN")[9:12]  # sin cambio de contenido


def test_changing_the_successors_updates_the_last_change_only(url: str) -> None:
    incorporate(url, build_snapshot(1, keys=(*BASE, "AN")))
    incorporate(url, successors_snapshot(2, ["CW"]))
    incorporate(url, successors_snapshot(3, ["CW", "SX"]))
    an = row_of(logical_state(url), "AN")
    assert an[8] == sorted([country_id("CW"), country_id("SX")])
    assert an[9:12] == (1, 1, 3)


def test_invalid_successors_are_rejected_leaving_the_catalog_identical(url: str) -> None:
    incorporate(url, build_snapshot(1, keys=(*BASE, "AN")))
    before = logical_state(url)
    duplicate = incorporate(url, successors_snapshot(2, ["CW", "CW"]))
    assert {v.rule for v in duplicate.violations} == {"RF-40"}
    ghost = successors_snapshot(2, ["CW"])
    an = next(c for c in ghost["countries"] if c["alpha2"] == "AN")
    an["replacement_country_ids"] = ["00000000-0000-4000-8000-000000000000"]
    assert {v.rule for v in incorporate(url, seal(ghost)).violations} == {"RF-40"}
    cycle = successors_snapshot(2, ["CW"])
    for item in cycle["countries"]:
        if item["alpha2"] == "CW":
            item.update(status="inactive", replacement_country_ids=[country_id("AN")])
    assert {v.rule for v in incorporate(url, seal(cycle)).violations} == {"RF-40"}
    assert logical_state(url) == before


def test_reactivating_a_retired_country_clears_its_successors(url: str) -> None:
    incorporate(url, build_snapshot(1, keys=(*BASE, "AN")))
    incorporate(url, successors_snapshot(2, ["CW", "SX", "BQ"]))
    keys = (*BASE, "CW", "SX", "BQ")
    back = build_snapshot(
        3,
        countries=[*(country(k) for k in keys), country("AN")],
        country_names=[*(n for k in keys for n in names(k)), *names("AN")],
        flags=[*(flag(k) for k in keys if k not in ("AQ", "BV")), flag("AN")],
        flag_exceptions=[flag_exception("AQ"), flag_exception("BV")],
    )
    result = incorporate(url, back)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    an = row_of(logical_state(url), "AN")
    assert (an[7], an[8]) == ("active", [])


# --- clasificación (RF-48) y coordinación con Regions (RF-35 de 002) ----------------------------


def test_an_active_country_on_an_inactive_subregion_is_rejected(url: str) -> None:
    subregions = [
        subregion("202"),
        subregion("419", status="inactive"),
        subregion("021"),
        subregion("035", "142"),
    ]
    regions = regions_snapshot(2, subregions=subregions)
    assert (
        incorporate_regions(regions, postgres_region_repository(url), required_locales()).outcome
        is RegionOutcome.INCORPORATED
    )
    result = incorporate(url, build_snapshot(1, region_snapshot_version=2))
    assert result.outcome is Outcome.REJECTED and {v.rule for v in result.violations} == {"RF-48"}
    assert logical_state(url)["country"] == []


def test_a_subregion_deactivated_later_blocks_the_next_snapshot_until_corrected(url: str) -> None:
    incorporate(url, build_snapshot(1))
    inactive = regions_snapshot(
        2,
        subregions=[
            subregion("202"),
            subregion("419", status="inactive"),
            subregion("021"),
            subregion("035", "142"),
        ],
    )
    incorporate_regions(inactive, postgres_region_repository(url), required_locales())
    blocked = incorporate(url, build_snapshot(2, region_snapshot_version=2))
    assert blocked.outcome is Outcome.REJECTED
    assert {v.rule for v in blocked.violations} == {"RF-48"}

    fixed = build_snapshot(
        2,
        region_snapshot_version=2,
        countries=[
            country(k, subregion_id=subregion_id("021")) if k in ("AR", "PR", "BV") else country(k)
            for k in BASE
        ],
    )
    result = incorporate(url, fixed)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert row_of(logical_state(url), "AR")[5] == subregion_id("021")


def reclassify_419(version: int) -> dict[str, Any]:
    return regions_snapshot(
        version,
        subregions=[
            subregion("202"),
            subregion("419", region_id=region_id("142")),
            subregion("021"),
            subregion("035", "142"),
        ],
    )


def test_a_regions_reclassification_that_breaks_a_country_is_rejected_by_regions(url: str) -> None:
    """RF-35 de 002: Countries aporta la FK compuesta que lo hace detectable."""
    incorporate(url, build_snapshot(1))
    before = logical_state(url)
    result = incorporate_regions(
        reclassify_419(2), postgres_region_repository(url), required_locales()
    )
    assert result.outcome is RegionOutcome.REJECTED
    (violation,) = result.violations
    assert violation.rule == "RF-35" and "country_classification_fk" in violation.message
    assert logical_state(url) == before


def test_the_same_reclassification_is_accepted_if_one_transaction_corrects_the_country(
    url: str,
) -> None:
    """La incorporación conjunta que cubre una feature posterior (S-8): aquí, SQL en una sola
    transacción, que es lo que las FK diferidas permiten."""
    incorporate(url, build_snapshot(1))
    with psycopg.connect(url) as conn:
        conn.execute(
            "UPDATE reference.subregion SET region_id = %s WHERE subregion_id = %s",
            [region_id("142"), subregion_id("419")],
        )
        conn.execute(
            "UPDATE reference.country SET region_id = %s WHERE subregion_id = %s",
            [region_id("142"), subregion_id("419")],
        )
    state = logical_state(url)
    assert row_of(state, "AR")[4] == region_id("142") and row_of(state, "AR")[5] == subregion_id(
        "419"
    )


def test_countries_does_not_block_unrelated_changes_of_regions(url: str) -> None:
    incorporate(url, build_snapshot(1))
    renamed = regions_snapshot(2)
    renamed["region_names"][0]["name"] = "África (renombrada)"
    result = incorporate_regions(
        seal_regions(renamed), postgres_region_repository(url), required_locales()
    )
    assert result.outcome is RegionOutcome.INCORPORATED, result.violations


# --- determinismo, red y CLI -------------------------------------------------------------------


def test_two_new_databases_reach_the_same_logical_state(ready: Callable[[], str]) -> None:
    first, second = ready(), ready()
    for document in (timor_v1(), timor_v2()):
        incorporate(first, document)
        incorporate(second, document)
    assert logical_state(first) == logical_state(second)


def test_the_cli_incorporates_and_diffs_without_network(
    url: str, tmp_path: Path, network_guard: NetworkGuard, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "countries.json"
    path.write_text(json.dumps(build_snapshot(1), ensure_ascii=False), encoding="utf-8")
    environ = {"REFERENCE_DATABASE_URL": url}

    def run(command: str) -> int:
        return main(
            [command, str(path)],
            environ=environ,
            repository_factory=postgres_country_repository,
            snapshot_reader=read_country_snapshot,
            policy_loader=country_required_locales,
            flag_store=country_flag_store_dir(),
        )

    with network_guard:
        empty = logical_state(url)
        assert run("diff") == 0
        assert "DIFF snapshot_version=1" in capsys.readouterr().out
        assert logical_state(url) == empty  # el diff no escribe
        assert run("incorporate") == 0
        assert "INCORPORADO snapshot_version=1" in capsys.readouterr().out
        assert run("diff") == 0
        assert "NO-OP" in capsys.readouterr().out
    assert network_guard.blocked == []


def test_the_cli_module_runs_as_documented_with_the_loader_role(url: str, tmp_path: Path) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("ALTER ROLE reference_loader LOGIN PASSWORD 'loader-pw'")
    loader = make_conninfo(url, user="reference_loader", password="loader-pw")
    command = [sys.executable, "-m", "gi_common_reference.countries.interfaces.cli"]
    env = {**os.environ, "REFERENCE_DATABASE_URL": loader}

    # El paquete instalado trae assets de bandera vacíos (el dataset real llega con PREP, S-7):
    # un snapshot sin banderas, solo con excepciones declaradas, se incorpora de punta a punta.
    keys = ("AQ", "BV")
    document = build_snapshot(
        1, keys=keys, flags=[], flag_exceptions=[flag_exception(k) for k in keys]
    )
    document["provenance"]["sources"] = [
        s for s in document["provenance"]["sources"] if s["role"] != "flags"
    ]
    path = tmp_path / "countries.json"
    path.write_text(json.dumps(seal(document), ensure_ascii=False), encoding="utf-8")

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*command, *args, str(path)],
            env=env,
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )

    done = run("incorporate")
    assert done.returncode == 0, done.stderr
    assert "INCORPORADO snapshot_version=1" in done.stdout
    again = run("incorporate")
    assert again.returncode == 0 and "NO-OP" in again.stdout
    assert run("diff").returncode == 0


class _FailingAfterSnapshot:
    """Repositorio real cuya transacción falla justo después de escribir `country_snapshot`."""

    def __init__(self, url: str) -> None:
        self._inner = postgres_country_repository(url)

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with self._inner.transaction() as tx:

            def fail(*args: Any) -> None:
                raise RuntimeError("fallo inyectado")

            tx.insert_countries = fail  # type: ignore[method-assign,assignment]
            yield tx


def test_a_failure_after_writing_the_snapshot_row_leaves_nothing(url: str) -> None:
    with pytest.raises(RuntimeError):
        incorporate_snapshot(
            build_snapshot(1),
            _FailingAfterSnapshot(url),  # type: ignore[arg-type]
            country_required_locales(),
            country_flag_store_dir(),
        )
    assert all(rows == [] for rows in logical_state(url).values())


def test_the_packaged_flag_store_is_the_one_used_in_production() -> None:
    assert country_flag_store().read("missing.svg") is None


def test_diff_does_not_take_the_exclusive_incorporation_lock(url: str) -> None:
    """D18: con el lock de incorporación tomado por otra sesión, el diff igual responde."""
    from concurrent.futures import ThreadPoolExecutor

    from gi_common_reference.countries.application.diff import preview_snapshot

    holder = psycopg.connect(url, autocommit=True)
    try:
        holder.execute(
            "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
            ["gi-common-reference.countries.incorporation"],
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                preview_snapshot,
                build_snapshot(1),
                postgres_country_repository(url),
                country_required_locales(),
            )
            preview = future.result(timeout=30)
        assert preview.outcome is Outcome.INCORPORATED and preview.diff is not None
    finally:
        holder.close()


def test_a_constraint_rejected_by_the_database_is_a_rejection_with_exit_code_1(
    url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D17: el dominio acepta el snapshot; una constraint más estricta de la base lo rechaza."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "ALTER TABLE reference.country ADD CONSTRAINT test_no_shared_calling_code "
            "CHECK (calling_code IS DISTINCT FROM '1')"
        )
    before = logical_state(url)
    path = tmp_path / "countries.json"
    path.write_text(json.dumps(build_snapshot(1), ensure_ascii=False), encoding="utf-8")
    code = main(
        ["incorporate", str(path)],
        environ={"REFERENCE_DATABASE_URL": url},
        repository_factory=postgres_country_repository,
        snapshot_reader=read_country_snapshot,
        policy_loader=country_required_locales,
        flag_store=country_flag_store_dir(),
    )
    err = capsys.readouterr().err
    assert code == 1 and "RNF-5" in err and "test_no_shared_calling_code" in err
    assert logical_state(url) == before
