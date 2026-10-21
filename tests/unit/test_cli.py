"""T7: CLI de incorporación (interfaz). Se prueba con un repositorio en memoria inyectado."""

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from gi_common_reference.bootstrap import postgres_repository
from gi_common_reference.locales.domain.errors import (
    InvalidConnectionString,
    PersistenceError,
    SchemaLoadError,
)
from gi_common_reference.locales.domain.ports import LocaleRepository
from gi_common_reference.locales.infrastructure import snapshot_reader
from gi_common_reference.locales.infrastructure.snapshot_reader import read_snapshot_document
from gi_common_reference.locales.interfaces.cli import main
from tests.fixtures.fakes import FakeRepository
from tests.fixtures.snapshots import (
    build_snapshot,
    iana_text,
    iw_scenario,
    language_entry,
    locale,
    locale_id,
)

ENV = {"REFERENCE_DATABASE_URL": "postgresql://unused"}


def write(tmp_path: Path, document: Any, name: str = "snapshot.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def run(args: list[str], repo: FakeRepository, env: dict[str, str] | None = None) -> int:
    def factory(url: str) -> LocaleRepository:
        assert url == ENV["REFERENCE_DATABASE_URL"]
        return repo

    return main(
        args,
        environ=ENV if env is None else env,
        repository_factory=factory,
        snapshot_reader=read_snapshot_document,
    )


def test_incorporating_a_valid_snapshot_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    v1, _ = iw_scenario()
    repo = FakeRepository()
    assert run(["incorporate", str(write(tmp_path, v1))], repo) == 0
    out = capsys.readouterr().out
    assert "INCORPORADO" in out and "snapshot_version=1" in out and "3 nuevos" in out
    assert len(repo.state.locales) == 3


def test_resubmitting_is_a_noop_with_exit_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    v1, _ = iw_scenario()
    repo = FakeRepository()
    path = write(tmp_path, v1)
    run(["incorporate", str(path)], repo)
    capsys.readouterr()
    assert run(["incorporate", str(path)], repo) == 0
    assert "NO-OP" in capsys.readouterr().out


def test_a_violation_exits_non_zero_and_lists_every_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = FakeRepository()
    bad = build_snapshot(1, locales=[locale("es"), locale("EN"), locale("PT")])
    code = run(["incorporate", str(write(tmp_path, bad))], repo)
    assert code == 1
    err = capsys.readouterr().err
    assert "RECHAZADO" in err and err.count("RF-28") == 2
    assert repo.state.locales == {}


def test_a_violation_with_non_encodable_text_is_reported_on_a_non_utf8_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Endurecimiento defensivo: streams cp1252 con manejo de errores estricto, que no admiten la
    # flecha (→) de los ciclos de replacement (RF-22). El stderr estándar de CPython ya escapa
    # (`backslashreplace`); el test fija que la CLI no dependa de eso.
    v1 = build_snapshot(
        1,
        registry=iana_text("2026-09-01", language_entry("xa"), language_entry("xb")),
        locales=[locale("xa"), locale("xb")],
    )
    deprecated = {"status": "inactive", "iana_deprecated": True}
    cycle = build_snapshot(
        2,
        registry=iana_text(
            "2026-10-01",
            language_entry("xa", "2020-01-01", "xb"),
            language_entry("xb", "2021-01-01", "xa"),
        ),
        file_date="2026-10-01",
        locales=[
            locale("xa", **deprecated, replacement_locale_id=locale_id("xb")),
            locale("xb", **deprecated, replacement_locale_id=locale_id("xa")),
        ],
    )
    repo = FakeRepository()
    assert run(["incorporate", str(write(tmp_path, v1, "v1.json"))], repo) == 0
    published = dict(repo.state.locales)

    stderr_bytes = io.BytesIO()
    stderr = io.TextIOWrapper(stderr_bytes, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    monkeypatch.setattr(sys, "stderr", stderr)

    assert run(["incorporate", str(write(tmp_path, cycle, "v2.json"))], repo) == 1

    stderr.flush()
    err = stderr_bytes.getvalue().decode("cp1252")
    assert "RECHAZADO snapshot_version=2" in err
    assert "RF-22: ciclo de replacement: xa \\u2192 xb \\u2192 xa" in err
    assert repo.state.locales == published


def test_an_invalid_snapshot_file_exits_non_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = {"snapshot_version": 1}
    repo = FakeRepository()
    assert run(["incorporate", str(write(tmp_path, broken))], repo) == 1
    assert "snapshot inválido" in capsys.readouterr().err
    assert repo.transactions == 0


def test_a_missing_file_exits_non_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["incorporate", str(tmp_path / "no-existe.json")], FakeRepository()) == 2
    assert "error" in capsys.readouterr().err


def test_a_missing_database_url_exits_non_zero_without_reading_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    v1, _ = iw_scenario()
    repo = FakeRepository()
    assert run(["incorporate", str(write(tmp_path, v1))], repo, env={}) == 2
    assert "REFERENCE_DATABASE_URL" in capsys.readouterr().err
    assert repo.transactions == 0


def test_an_operational_failure_exits_non_zero_and_does_not_leave_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    v1, _ = iw_scenario()
    repo = FakeRepository()
    repo.fail_at = "insert_locales"
    assert run(["incorporate", str(write(tmp_path, v1))], repo) == 2
    assert "insert_locales" in capsys.readouterr().err
    assert repo.state.snapshots == [] and repo.state.locales == {}


def test_unknown_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        run(["borrar"], FakeRepository())
    assert raised.value.code == 2


def test_there_is_no_write_command_other_than_incorporate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for command in ("delete", "update", "create", "serve"):
        with pytest.raises(SystemExit):
            run([command], FakeRepository())


# --- errores del schema, de lectura y de base de datos se distinguen y no filtran la conexión ----

SECRET = "SECRETPW"


def cli(path: Path, factory: Any, url: str, reader: Any = read_snapshot_document) -> int:
    return main(
        ["incorporate", str(path)],
        environ={"REFERENCE_DATABASE_URL": url},
        repository_factory=factory,
        snapshot_reader=reader,
    )


def test_a_schema_load_failure_is_reported_as_an_incomplete_installation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshot_reader, "SCHEMA_RESOURCE", "no-existe.schema.json")
    v1, _ = iw_scenario()
    repo = FakeRepository()
    assert run(["incorporate", str(write(tmp_path, v1))], repo) == 2
    err = capsys.readouterr().err
    assert "instalación incompleta" in err and "no-existe.schema.json" in err
    assert "no se pudo leer" not in err and str(tmp_path) not in err
    assert repo.transactions == 0


def test_an_unreadable_snapshot_is_not_reported_as_an_incomplete_installation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["incorporate", str(tmp_path / "no-existe.json")], FakeRepository()) == 2
    err = capsys.readouterr().err
    assert "no se pudo leer" in err and "instalación incompleta" not in err


def test_a_schema_error_raised_by_the_reader_never_reaches_the_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken_reader(path: Path) -> dict[str, Any]:
        raise SchemaLoadError("no se pudo cargar el schema")

    repo = FakeRepository()
    v1, _ = iw_scenario()
    assert cli(write(tmp_path, v1), lambda url: repo, "postgresql://x", broken_reader) == 2
    assert repo.transactions == 0
    assert "instalación incompleta" in capsys.readouterr().err


def test_an_invalid_connection_string_is_reported_without_echoing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    v1, _ = iw_scenario()
    assert cli(write(tmp_path, v1), postgres_repository, SECRET) == 2
    err = capsys.readouterr().err
    assert SECRET not in err
    assert "REFERENCE_DATABASE_URL" in err and str(InvalidConnectionString()) in err


def test_an_unreachable_database_is_reported_by_type_without_the_connection_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    v1, _ = iw_scenario()
    url = f"postgresql://user:{SECRET}@127.0.0.1:1/db?connect_timeout=1"
    assert cli(write(tmp_path, v1), postgres_repository, url) == 2
    err = capsys.readouterr().err
    assert "falló la base de datos" in err
    assert SECRET not in err and "127.0.0.1" not in err and "user" not in err.replace("usuario", "")


def test_a_persistence_error_prints_only_its_safe_description(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing(url: str) -> LocaleRepository:
        raise PersistenceError("OperationalError (SQLSTATE 28P01)")

    v1, _ = iw_scenario()
    assert cli(write(tmp_path, v1), failing, "postgresql://x") == 2
    assert "falló la base de datos: OperationalError (SQLSTATE 28P01)" in capsys.readouterr().err
