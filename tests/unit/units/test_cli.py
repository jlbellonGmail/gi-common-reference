"""T6: CLI de Units: códigos de salida, `diff` sin escrituras y salida sin credenciales."""

import json
from pathlib import Path
from typing import Any

import pytest

from gi_common_reference.units.domain.errors import (
    InvalidConnectionString,
    PersistenceError,
    SchemaLoadError,
)
from gi_common_reference.units.domain.model import UcumTable
from gi_common_reference.units.domain.policy import RequiredLocales
from gi_common_reference.units.infrastructure.snapshot_reader import read_snapshot_document
from gi_common_reference.units.interfaces.cli import DATABASE_URL, main
from tests.fixtures.units import build_snapshot
from tests.fixtures.units_fakes import FakeUnitsRepository
from tests.unit.units.helpers import POLICY, ucum_table

SECRET = "postgresql://loader:s3cr3t-password@db.example/reference"
ENV = {DATABASE_URL: SECRET}


def write(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def run(
    argv: list[str],
    repository: FakeUnitsRepository,
    *,
    environ: dict[str, str] | None = None,
    policy: RequiredLocales = POLICY,
) -> int:
    return main(
        argv,
        environ=ENV if environ is None else environ,
        repository_factory=lambda conninfo: repository,
        snapshot_reader=read_snapshot_document,
        policy_loader=lambda: policy,
        ucum_loader=ucum_table,
    )


def test_incorporate_exits_zero_and_reports_what_was_incorporated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = FakeUnitsRepository()
    assert run(["incorporate", str(write(tmp_path, build_snapshot(1)))], repository) == 0
    out = capsys.readouterr().out
    assert "INCORPORADO snapshot_version=1" in out and "ucum_table_version=2.2" in out
    assert "50 unidades nuevas" in out and "14 magnitudes nuevas" in out
    assert "54 asociaciones nuevas" in out
    assert len(repository.state.units) == 50


def test_resubmitting_is_a_noop_with_exit_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = FakeUnitsRepository()
    path = write(tmp_path, build_snapshot(1))
    run(["incorporate", str(path)], repository)
    capsys.readouterr()
    assert run(["incorporate", str(path)], repository) == 0
    assert "NO-OP snapshot_version=1" in capsys.readouterr().out


def test_a_rejected_snapshot_exits_one_and_lists_each_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = FakeUnitsRepository()
    run(["incorporate", str(write(tmp_path, build_snapshot(1)))], repository)
    capsys.readouterr()
    other = write(tmp_path, build_snapshot(1, codes=("mass",)))
    assert run(["incorporate", str(other)], repository) == 1
    err = capsys.readouterr().err
    assert "RECHAZADO snapshot_version=1" in err and "RF-42" in err


def test_an_invalid_file_exits_one_without_touching_the_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = build_snapshot(1)
    del bad["units"]
    repository = FakeUnitsRepository()
    assert run(["incorporate", str(write(tmp_path, bad))], repository) == 1
    assert "snapshot inválido" in capsys.readouterr().err
    assert repository.transactions == 0 and repository.inspections == 0


def test_an_unreadable_file_and_a_broken_installation_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = FakeUnitsRepository()
    assert run(["incorporate", str(tmp_path / "missing.json")], repository) == 2
    assert "no se pudo leer" in capsys.readouterr().err

    def broken_policy() -> RequiredLocales:
        raise SchemaLoadError("falta required-locales.v1.json")

    def broken_ucum() -> UcumTable:
        raise SchemaLoadError("tabla UCUM adulterada")

    path = write(tmp_path, build_snapshot(1))
    for policy_loader, ucum_loader in (
        (broken_policy, ucum_table),
        (lambda: POLICY, broken_ucum),
    ):
        code = main(
            ["incorporate", str(path)],
            environ=ENV,
            repository_factory=lambda conninfo: repository,
            snapshot_reader=read_snapshot_document,
            policy_loader=policy_loader,
            ucum_loader=ucum_loader,
        )
        assert code == 2 and "instalación incompleta" in capsys.readouterr().err
    assert repository.transactions == 0


def test_a_missing_database_url_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, build_snapshot(1))
    assert run(["incorporate", str(path)], FakeUnitsRepository(), environ={}) == 2
    assert DATABASE_URL in capsys.readouterr().err


@pytest.mark.parametrize(
    "error",
    [
        InvalidConnectionString(),
        PersistenceError("OperationalError (SQLSTATE 08006)"),
        RuntimeError("boom"),
    ],
)
def test_operational_errors_exit_two_and_never_show_the_connection_string(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    def failing(conninfo: str) -> FakeUnitsRepository:
        raise error

    code = main(
        ["incorporate", str(write(tmp_path, build_snapshot(1)))],
        environ=ENV,
        repository_factory=failing,
        snapshot_reader=read_snapshot_document,
        policy_loader=lambda: POLICY,
        ucum_loader=ucum_table,
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "s3cr3t" not in captured.out + captured.err


def test_diff_prints_the_changes_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = FakeUnitsRepository()
    path = write(tmp_path, build_snapshot(1))
    assert run(["diff", str(path)], repository) == 0
    out = capsys.readouterr().out
    assert "DIFF snapshot_version=1" in out and "alta" in out
    assert repository.state.snapshots == [] and repository.transactions == 0


def test_diff_of_an_applied_snapshot_is_a_noop_and_of_a_bad_one_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = FakeUnitsRepository()
    run(["incorporate", str(write(tmp_path, build_snapshot(1)))], repository)
    capsys.readouterr()
    assert run(["diff", str(write(tmp_path, build_snapshot(1)))], repository) == 0
    assert "sin cambios" in capsys.readouterr().out
    bad = write(tmp_path, build_snapshot(1, codes=("mass",)))
    assert run(["diff", str(bad)], repository) == 1
    assert "RF-42" in capsys.readouterr().err


def test_the_command_is_required() -> None:
    with pytest.raises(SystemExit):
        run([], FakeUnitsRepository())
