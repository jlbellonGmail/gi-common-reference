"""T7: incorporación transaccional contra Postgres real (RF-14, RF-17, RF-18, RF-20, RF-21,
RF-28, RNF-1, RNF-2, RNF-5)."""

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from gi_common_reference.bootstrap import postgres_repository, read_snapshot
from gi_common_reference.locales.application.incorporate import (
    IncorporationResult,
    Outcome,
    incorporate_snapshot,
)
from gi_common_reference.locales.domain.snapshot import content_digest_matches, iana_digest_matches
from gi_common_reference.locales.infrastructure.postgres_repository import (
    PostgresLocaleRepository,
)
from gi_common_reference.locales.interfaces.cli import main
from tests.conftest import NetworkGuard
from tests.fixtures.snapshots import build_snapshot, iw_scenario, locale, locale_id

ROOT = Path(__file__).resolve().parents[2]
WRITE_STEPS = ["insert_snapshot", "insert_locales", "update_metadata", "replace_aliases"]


def incorporate(url: str, document: dict[str, Any]) -> IncorporationResult:
    return incorporate_snapshot(document, postgres_repository(url))


def snapshot_rows(conn: psycopg.Connection[Any], *, with_timestamp: bool) -> list[tuple[Any, ...]]:
    columns = "snapshot_version, content_digest, iana_file_date, iana_digest, provenance, artifact"
    if with_timestamp:
        columns += ", incorporated_at"
    return conn.execute(
        f"SELECT {columns} FROM reference.locale_snapshot ORDER BY snapshot_version"
    ).fetchall()


def logical_state(url: str) -> dict[str, list[tuple[Any, ...]]]:
    with psycopg.connect(url) as conn:
        return {
            "locale": conn.execute(
                "SELECT locale_id::text, code, status, iana_deprecated, "
                "replacement_locale_id::text, first_snapshot_version "
                "FROM reference.locale ORDER BY code"
            ).fetchall(),
            "alias": conn.execute(
                "SELECT subtag, preferred_value FROM reference.locale_alias ORDER BY subtag"
            ).fetchall(),
            "snapshot": snapshot_rows(conn, with_timestamp=False),
        }


def full_dump(url: str) -> dict[str, list[tuple[Any, ...]]]:
    state = logical_state(url)
    with psycopg.connect(url) as conn:
        state["snapshot"] = snapshot_rows(conn, with_timestamp=True)
    return state


# --- flujo básico ------------------------------------------------------------------------------


def test_first_snapshot_is_incorporated_with_the_ids_it_brings(database_url: str) -> None:
    v1, _ = iw_scenario()
    result = incorporate(database_url, v1)
    assert result.outcome is Outcome.INCORPORATED and result.new_locales == 3
    state = logical_state(database_url)
    assert {row[0]: row[1] for row in state["locale"]} == {
        locale_id("es"): "es",
        locale_id("en"): "en",
        locale_id("iw"): "iw",
    }
    assert all(row[5] == 1 for row in state["locale"])
    assert state["alias"] == []
    (row,) = state["snapshot"]
    assert row[0] == 1 and row[1] == v1["content_digest"] and row[3] == v1["iana"]["digest"]


def test_later_snapshot_updates_iw_metadata_and_replaces_the_aliases(database_url: str) -> None:
    v1, v2 = iw_scenario()
    incorporate(database_url, v1)
    before = {row[0]: row for row in logical_state(database_url)["locale"]}

    result = incorporate(database_url, v2)

    assert result.outcome is Outcome.INCORPORATED
    assert (result.new_locales, result.updated_locales) == (1, 1)
    state = logical_state(database_url)
    rows = {row[1]: row for row in state["locale"]}
    iw = rows["iw"]
    # metadata actualizada y persistida
    assert (iw[2], iw[3], iw[4]) == ("inactive", True, locale_id("he"))
    # identidad intacta
    assert iw[0] == locale_id("iw") and iw[1] == "iw" == before[locale_id("iw")][1]
    assert iw[5] == 1
    # `he` es un locale nuevo con el id que trajo el snapshot
    assert rows["he"][0] == locale_id("he") and rows["he"][5] == 2
    assert (rows["he"][2], rows["he"][3], rows["he"][4]) == ("active", False, None)
    # los demás no cambian
    assert rows["es"] == before[locale_id("es")] and rows["en"] == before[locale_id("en")]
    # locale_alias refleja el artefacto vigente
    assert state["alias"] == [("iw", "he")]
    assert [row[0] for row in state["snapshot"]] == [1, 2]


def test_snapshot_one_is_kept_unchanged_after_the_later_one(database_url: str) -> None:
    v1, v2 = iw_scenario()
    incorporate(database_url, v1)
    first = logical_state(database_url)["snapshot"][0]
    incorporate(database_url, v2)
    assert logical_state(database_url)["snapshot"][0] == first


# --- idempotencia (RF-21) ----------------------------------------------------------------------


def test_resubmitting_n_after_n_plus_one_changes_nothing(database_url: str) -> None:
    v1, v2 = iw_scenario()
    incorporate(database_url, v1)
    incorporate(database_url, v2)
    before = full_dump(database_url)

    for document in (v1, v2, v1):
        assert incorporate(database_url, document).outcome is Outcome.NOOP

    assert full_dump(database_url) == before


# --- rechazos y atomicidad (RF-20) -------------------------------------------------------------


def test_snapshot_with_a_published_locale_as_ES_is_rejected_and_state_is_identical(
    database_url: str,
) -> None:
    v1, _ = iw_scenario()
    incorporate(database_url, v1)
    before = full_dump(database_url)
    bad = build_snapshot(2, locales=[locale("es", code="ES"), locale("en"), locale("iw")])

    result = incorporate(database_url, bad)

    assert result.outcome is Outcome.REJECTED
    assert {v.rule for v in result.violations} == {"RF-28"}
    assert full_dump(database_url) == before


def test_other_violations_also_leave_the_state_identical(database_url: str) -> None:
    v1, v2 = iw_scenario()
    incorporate(database_url, v1)
    incorporate(database_url, v2)
    before = full_dump(database_url)
    variants = [
        build_snapshot(2, codes=("es", "en")),  # misma versión, otro contenido (B)
        build_snapshot(1, codes=("es", "en")),  # versión ya incorporada, otro contenido (B)
        build_snapshot(3, file_date="2026-01-01", codes=("es", "en", "he", "iw")),  # RF-29
        build_snapshot(3, file_date="2026-11-01", codes=("es",)),  # omite locales (RF-15)
    ]
    for document in variants:
        assert incorporate(database_url, document).outcome is Outcome.REJECTED
    assert full_dump(database_url) == before


class FailingRepository(PostgresLocaleRepository):
    """Falla justo después de ejecutar `failing_step`, ya dentro de la transacción."""

    def __init__(self, url: str, failing_step: str) -> None:
        super().__init__(url)
        self.failing_step = failing_step

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with super().transaction() as tx:
            yield _Failing(tx, self.failing_step)


class _Failing:
    def __init__(self, inner: Any, failing_step: str) -> None:
        self._inner, self._failing_step = inner, failing_step

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if name != self._failing_step:
            return target

        def wrapper(*args: Any, **kwargs: Any) -> None:
            target(*args, **kwargs)
            raise RuntimeError(f"fallo inyectado después de {name}")

        return wrapper


@pytest.mark.parametrize("failing_step", WRITE_STEPS)
def test_failure_after_any_write_step_leaves_no_trace(database_url: str, failing_step: str) -> None:
    v1, v2 = iw_scenario()
    incorporate(database_url, v1)
    before = full_dump(database_url)

    with pytest.raises(RuntimeError, match=failing_step):
        incorporate_snapshot(v2, FailingRepository(database_url, failing_step))

    assert full_dump(database_url) == before


def test_failure_right_after_inserting_locale_snapshot_leaves_no_snapshot_row(
    database_url: str,
) -> None:
    v1, _ = iw_scenario()
    with pytest.raises(RuntimeError):
        incorporate_snapshot(v1, FailingRepository(database_url, "insert_snapshot"))
    with psycopg.connect(database_url) as conn:
        assert conn.execute("SELECT count(*) FROM reference.locale_snapshot").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM reference.locale").fetchone() == (0,)


class RecordingRepository(PostgresLocaleRepository):
    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.calls: list[str] = []

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with super().transaction() as tx:
            yield _Recording(tx, self.calls)


class _Recording:
    def __init__(self, inner: Any, calls: list[str]) -> None:
        self._inner, self._calls = inner, calls

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if name not in WRITE_STEPS:
            return target

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self._calls.append(name)
            return target(*args, **kwargs)

        return wrapper


def test_write_order_against_postgres(database_url: str) -> None:
    v1, v2 = iw_scenario()
    repo = RecordingRepository(database_url)
    incorporate_snapshot(v1, repo)
    incorporate_snapshot(v2, repo)
    assert repo.calls == WRITE_STEPS + WRITE_STEPS


# --- trazabilidad (RNF-5) ----------------------------------------------------------------------


def test_stored_artifact_recalculates_its_digests(database_url: str) -> None:
    v1, v2 = iw_scenario()
    incorporate(database_url, v1)
    incorporate(database_url, v2)
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            "SELECT snapshot_version, artifact, content_digest, iana_digest, provenance "
            "FROM reference.locale_snapshot ORDER BY snapshot_version"
        ).fetchall()
    for (version, artifact, declared, iana_declared, provenance), original in zip(
        rows, (v1, v2), strict=True
    ):
        assert artifact == original
        assert content_digest_matches(artifact) and iana_digest_matches(artifact)
        assert (
            declared == artifact["content_digest"] and iana_declared == artifact["iana"]["digest"]
        )
        assert provenance == original["provenance"] and version == original["snapshot_version"]


def test_history_cannot_be_modified_after_incorporating(database_url: str) -> None:
    v1, _ = iw_scenario()
    incorporate(database_url, v1)
    with psycopg.connect(database_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.RestrictViolation):
            conn.execute("UPDATE reference.locale_snapshot SET artifact = '{}'")


# --- determinismo (RNF-1) ----------------------------------------------------------------------


def test_two_fresh_databases_reach_the_same_state(
    database_factory: Callable[[], str],
) -> None:
    first, second = database_factory(), database_factory()
    v1, v2 = iw_scenario()
    for url in (first, second):
        incorporate(url, v1)
        incorporate(url, v2)
    assert logical_state(first) == logical_state(second)
    with psycopg.connect(first) as one, psycopg.connect(second) as two:
        assert snapshot_rows(one, with_timestamp=False) == snapshot_rows(two, with_timestamp=False)
        stamps = [
            conn.execute("SELECT incorporated_at FROM reference.locale_snapshot").fetchall()
            for conn in (one, two)
        ]
    assert all(row[0] is not None for rows in stamps for row in rows)


# --- concurrencia (D12) ------------------------------------------------------------------------


class SlowRepository(PostgresLocaleRepository):
    """Retiene la transacción (y su lock) un rato después de escribir, y avisa cuándo."""

    def __init__(self, url: str, inside: threading.Event, hold: float) -> None:
        super().__init__(url)
        self.inside, self.hold = inside, hold

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with super().transaction() as tx:
            yield _Slow(tx, self.inside, self.hold)


class _Slow:
    def __init__(self, inner: Any, inside: threading.Event, hold: float) -> None:
        self._inner, self._inside, self._hold = inner, inside, hold

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if name != "insert_locales":
            return target

        def wrapper(*args: Any, **kwargs: Any) -> None:
            target(*args, **kwargs)
            self._inside.set()
            time.sleep(self._hold)

        return wrapper


def advisory_locks(url: str) -> tuple[int, int]:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT count(*) FILTER (WHERE granted), count(*) FILTER (WHERE NOT granted) "
            "FROM pg_locks WHERE locktype = 'advisory'"
        ).fetchone()
    assert row is not None
    return row[0], row[1]


def test_concurrent_incorporations_are_serialized_by_an_advisory_lock(database_url: str) -> None:
    v1, _ = iw_scenario()
    outcomes: list[Outcome] = []
    errors: list[BaseException] = []
    inside = threading.Event()

    def first() -> None:
        try:
            outcomes.append(
                incorporate_snapshot(v1, SlowRepository(database_url, inside, hold=1.5)).outcome
            )
        except BaseException as error:
            errors.append(error)

    def second() -> None:
        try:
            outcomes.append(incorporate(database_url, v1).outcome)
        except BaseException as error:
            errors.append(error)

    one = threading.Thread(target=first)
    one.start()
    assert inside.wait(timeout=20)
    assert advisory_locks(database_url)[0] >= 1  # la primera transacción retiene el lock
    two = threading.Thread(target=second)
    two.start()
    deadline = time.monotonic() + 10
    while advisory_locks(database_url)[1] < 1 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert advisory_locks(database_url)[1] == 1  # la segunda espera, no avanza
    one.join(timeout=30)
    two.join(timeout=30)

    assert errors == []
    assert sorted(outcomes, key=str) == [Outcome.INCORPORATED, Outcome.NOOP]
    assert logical_state(database_url)["snapshot"][0][0] == 1


# --- roles y red -------------------------------------------------------------------------------


@pytest.fixture
def loader_url(database_url: str, postgres_with_roles: str) -> str:
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute("ALTER ROLE reference_loader WITH LOGIN PASSWORD 'loader'")
    return make_conninfo(database_url, user="reference_loader", password="loader")


def test_the_loader_role_is_enough_for_the_whole_flow(database_url: str, loader_url: str) -> None:
    v1, v2 = iw_scenario()
    assert incorporate(loader_url, v1).outcome is Outcome.INCORPORATED
    assert incorporate(loader_url, v2).outcome is Outcome.INCORPORATED
    assert incorporate(loader_url, v1).outcome is Outcome.NOOP
    assert logical_state(database_url)["alias"] == [("iw", "he")]
    with psycopg.connect(loader_url) as conn:
        assert conn.execute("SELECT current_user").fetchone() == ("reference_loader",)


def write_snapshot(tmp_path: Path, document: dict[str, Any], name: str) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_cli_completes_the_flow_with_a_network_guard_active(
    database_url: str,
    tmp_path: Path,
    network_guard: NetworkGuard,
    capsys: pytest.CaptureFixture[str],
) -> None:
    v1, v2 = iw_scenario()
    env = {"REFERENCE_DATABASE_URL": database_url}
    files = [write_snapshot(tmp_path, d, f"s{d['snapshot_version']}.json") for d in (v1, v2)]
    bad = write_snapshot(
        tmp_path,
        build_snapshot(3, locales=[locale("es", code="ES")], file_date="2026-11-01"),
        "bad.json",
    )

    def cli(path: Path) -> int:
        return main(
            ["incorporate", str(path)],
            environ=env,
            repository_factory=postgres_repository,
            snapshot_reader=read_snapshot,
        )

    with network_guard:
        first, second = cli(files[0]), cli(files[1])
        again, rejected = cli(files[0]), cli(bad)

    assert (first, second, again, rejected) == (0, 0, 0, 1)
    assert network_guard.blocked == []
    assert logical_state(database_url)["alias"] == [("iw", "he")]
    out = capsys.readouterr()
    assert "INCORPORADO" in out.out and "NO-OP" in out.out and "RF-28" in out.err


def test_the_iana_artifact_is_read_only_from_the_snapshot(
    database_url: str, network_guard: NetworkGuard
) -> None:
    v1, v2 = iw_scenario()
    with network_guard:
        incorporate(database_url, v1)
        incorporate(database_url, v2)
    assert network_guard.blocked == []


def test_cli_entry_point_runs_as_a_module(database_url: str, tmp_path: Path) -> None:
    v1, _ = iw_scenario()
    path = write_snapshot(tmp_path, v1, "s1.json")
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "REFERENCE_DATABASE_URL": database_url,
    }
    command = [
        sys.executable,
        "-m",
        "gi_common_reference.locales.interfaces.cli",
        "incorporate",
        str(path),
    ]
    done = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert "INCORPORADO" in done.stdout
    again = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert again.returncode == 0 and "NO-OP" in again.stdout

    bad = write_snapshot(tmp_path, build_snapshot(2, locales=[locale("es", code="ES")]), "bad.json")
    command[-1] = str(bad)
    rejected = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert rejected.returncode == 1 and "RF-28" in rejected.stderr
