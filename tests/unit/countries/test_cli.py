"""T8: CLI de Countries: códigos de salida, diff sin escrituras y salida sin credenciales."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from gi_common_reference.countries.domain.errors import (
    InvalidConnectionString,
    PersistenceError,
    SchemaLoadError,
)
from gi_common_reference.countries.domain.policy import RequiredLocales
from gi_common_reference.countries.domain.ports import CountryRepository
from gi_common_reference.countries.infrastructure.flag_store import DirectoryFlagStore
from gi_common_reference.countries.infrastructure.snapshot_reader import read_snapshot_document
from gi_common_reference.countries.interfaces.cli import main
from tests.fixtures.countries import FLAGS_DIR, POLICY, build_snapshot
from tests.fixtures.country_fakes import FakeCountryRepository

SECRET = "postgresql://reference_loader:s3cr3t-pw@db.example/ref"
ENV = {"REFERENCE_DATABASE_URL": SECRET}
STORE = DirectoryFlagStore(FLAGS_DIR)


def write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "countries.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def run(
    tmp_path: Path,
    document: Any,
    repository: CountryRepository,
    *,
    command: str = "incorporate",
    environ: dict[str, str] | None = None,
    policy_loader: Callable[[], RequiredLocales] = lambda: POLICY,
    flag_store: DirectoryFlagStore = STORE,
) -> int:
    return main(
        [command, str(write(tmp_path, document))],
        environ=ENV if environ is None else environ,
        repository_factory=lambda conninfo: repository,
        snapshot_reader=read_snapshot_document,
        policy_loader=policy_loader,
        flag_store=flag_store,
    )


def test_incorporated_noop_and_rejected_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = FakeCountryRepository()
    assert run(tmp_path, build_snapshot(1), repository) == 0
    out = capsys.readouterr().out
    assert "INCORPORADO snapshot_version=1" in out and "8 países nuevos" in out
    assert run(tmp_path, build_snapshot(1), repository) == 0
    assert "NO-OP snapshot_version=1" in capsys.readouterr().out
    assert run(tmp_path, build_snapshot(2, keys=("AR",)), repository) == 1
    err = capsys.readouterr().err
    assert "RECHAZADO snapshot_version=2" in err and "RF-21" in err


def test_an_invalid_document_is_rejected_with_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = build_snapshot(1)
    del document["recodings"]
    assert run(tmp_path, document, FakeCountryRepository()) == 1
    assert "RECHAZADO: snapshot inválido" in capsys.readouterr().err


def test_a_missing_variable_is_an_operational_error(tmp_path: Path) -> None:
    assert run(tmp_path, build_snapshot(1), FakeCountryRepository(), environ={}) == 2


def test_an_unreadable_file_is_an_operational_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["incorporate", str(tmp_path / "missing.json")],
        environ=ENV,
        repository_factory=lambda conninfo: FakeCountryRepository(),
        snapshot_reader=read_snapshot_document,
        policy_loader=lambda: POLICY,
        flag_store=STORE,
    )
    assert code == 2 and "no se pudo leer" in capsys.readouterr().err


def test_a_broken_policy_is_an_operational_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken() -> RequiredLocales:
        raise SchemaLoadError("la política no se pudo cargar")

    assert run(tmp_path, build_snapshot(1), FakeCountryRepository(), policy_loader=broken) == 2
    assert "instalación incompleta" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["incorporate", "diff"])
@pytest.mark.parametrize(
    "error",
    [InvalidConnectionString(), PersistenceError("OperationalError"), RuntimeError("boom")],
)
def test_database_and_unexpected_errors_never_print_the_connection_string(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], error: Exception, command: str
) -> None:
    def factory(conninfo: str) -> CountryRepository:
        raise error

    code = main(
        [command, str(write(tmp_path, build_snapshot(1)))],
        environ=ENV,
        repository_factory=factory,
        snapshot_reader=read_snapshot_document,
        policy_loader=lambda: POLICY,
        flag_store=STORE,
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "s3cr3t-pw" not in captured.out + captured.err
    assert SECRET not in captured.out + captured.err


# --- diff ----------------------------------------------------------------------------------------


def test_diff_prints_the_changes_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = FakeCountryRepository()
    assert run(tmp_path, build_snapshot(1), repository, command="diff") == 0
    out = capsys.readouterr().out
    assert "DIFF snapshot_version=1" in out and "alta" in out and "AR" in out
    assert repository.state.snapshots == [] and repository.calls == []
    assert repository.transactions == 0 and repository.inspections == 1


def test_diff_of_an_incorporated_snapshot_and_of_an_invalid_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = FakeCountryRepository()
    run(tmp_path, build_snapshot(1), repository)
    capsys.readouterr()
    assert run(tmp_path, build_snapshot(1), repository, command="diff") == 0
    assert "NO-OP snapshot_version=1" in capsys.readouterr().out
    assert run(tmp_path, build_snapshot(2, keys=("AR",)), repository, command="diff") == 1
    assert "RF-21" in capsys.readouterr().err
    assert repository.transactions == 1  # solo la incorporación inicial


def test_diff_does_not_need_the_flag_assets(tmp_path: Path) -> None:
    empty = DirectoryFlagStore(tmp_path / "no-assets")
    repository = FakeCountryRepository()
    assert run(tmp_path, build_snapshot(1), repository, command="diff", flag_store=empty) == 0
    assert run(tmp_path, build_snapshot(1), repository, flag_store=empty) == 1
