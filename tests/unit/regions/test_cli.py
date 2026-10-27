"""T7: CLI de incorporación de Regions: códigos de salida y salida sin credenciales."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from gi_common_reference.regions.domain.errors import (
    InvalidConnectionString,
    PersistenceError,
    SchemaLoadError,
)
from gi_common_reference.regions.domain.policy import RequiredLocales
from gi_common_reference.regions.domain.ports import RegionRepository
from gi_common_reference.regions.infrastructure.snapshot_reader import read_snapshot_document
from gi_common_reference.regions.interfaces.cli import main
from tests.fixtures.region_fakes import FakeRegionRepository
from tests.fixtures.regions import POLICY, build_snapshot, region

SECRET = "postgresql://reference_loader:s3cr3t-pw@db.example/ref"
ENV = {"REFERENCE_DATABASE_URL": SECRET}


def write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "regions.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def run(
    tmp_path: Path,
    document: Any,
    repository: RegionRepository,
    *,
    environ: dict[str, str] | None = None,
    policy_loader: Callable[[], RequiredLocales] = lambda: POLICY,
) -> int:
    return main(
        ["incorporate", str(write(tmp_path, document))],
        environ=ENV if environ is None else environ,
        repository_factory=lambda conninfo: repository,
        snapshot_reader=read_snapshot_document,
        policy_loader=policy_loader,
    )


def test_incorporated_noop_and_rejected_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = FakeRegionRepository()
    assert run(tmp_path, build_snapshot(1), repository) == 0
    assert "INCORPORADO snapshot_version=1" in capsys.readouterr().out
    assert run(tmp_path, build_snapshot(1), repository) == 0
    assert "NO-OP snapshot_version=1" in capsys.readouterr().out
    assert run(tmp_path, build_snapshot(2, regions=[region("019")]), repository) == 1
    err = capsys.readouterr().err
    assert "RECHAZADO snapshot_version=2" in err and "RF-22" in err


def test_an_invalid_document_is_rejected_with_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = build_snapshot(1)
    del document["recodings"]
    assert run(tmp_path, document, FakeRegionRepository()) == 1
    assert "RECHAZADO: snapshot inválido" in capsys.readouterr().err


def test_a_missing_variable_is_an_operational_error(tmp_path: Path) -> None:
    assert run(tmp_path, build_snapshot(1), FakeRegionRepository(), environ={}) == 2


def test_an_unreadable_file_is_an_operational_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["incorporate", str(tmp_path / "missing.json")],
        environ=ENV,
        repository_factory=lambda conninfo: FakeRegionRepository(),
        snapshot_reader=read_snapshot_document,
        policy_loader=lambda: POLICY,
    )
    assert code == 2 and "no se pudo leer" in capsys.readouterr().err


def test_a_broken_policy_is_an_operational_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken() -> RequiredLocales:
        raise SchemaLoadError("la política no se pudo cargar")

    assert run(tmp_path, build_snapshot(1), FakeRegionRepository(), policy_loader=broken) == 2
    assert "instalación incompleta" in capsys.readouterr().err


@pytest.mark.parametrize(
    "error",
    [InvalidConnectionString(), PersistenceError("OperationalError"), RuntimeError("boom")],
)
def test_database_and_unexpected_errors_never_print_the_connection_string(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    def factory(conninfo: str) -> RegionRepository:
        raise error

    code = main(
        ["incorporate", str(write(tmp_path, build_snapshot(1)))],
        environ=ENV,
        repository_factory=factory,
        snapshot_reader=read_snapshot_document,
        policy_loader=lambda: POLICY,
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "s3cr3t-pw" not in captured.out + captured.err
    assert SECRET not in captured.out + captured.err
