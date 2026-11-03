"""Soporte de la aceptación de 005-units-of-measure (D18 del plan).

Módulo nuevo: no modifica `conftest.py` ni la aceptación de 004. Reutiliza de ahí el guard de red,
el registro de evidencia y el `Stack` (CLI como subproceso, GET/405 por HTTP). Levanta una base
Postgres descartable, aplica `alembic upgrade head`, incorpora un Locale sintético con la CLI de
Locale y arranca la API real (uvicorn, rol `reference_reader`). Units se incorpora desde los casos.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from psycopg.conninfo import make_conninfo

from tests.acceptance.conftest import (
    GUARD,
    ROOT,
    Evidence,
    Stack,
    free_port,
)
from tests.conftest import alembic_config, with_database
from tests.fixtures.regions import locale_snapshot

UNITS_CLI = "gi_common_reference.units.interfaces.cli"
TABLES = (
    "unit_snapshot",
    "quantity_kind",
    "unit",
    "quantity_kind_unit",
    "quantity_kind_locale",
    "unit_locale",
)


@dataclass
class UnitsStack(Stack):
    """`Stack` con la CLI de Units y POST con cuerpo crudo (para enviar JSON no canónico)."""

    def units(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.cli(UNITS_CLI, *args)

    def post(
        self, path: str, payload: Any, *, record: bool = True, raw: bytes | None = None
    ) -> tuple[int, bytes]:
        """POST JSON; `raw` envía ese cuerpo tal cual. Devuelve (estado, cuerpo en bytes)."""
        data = raw if raw is not None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            method="POST",
            data=data,
            headers={"content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, body = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
        if record:
            self.evidence.http.append(
                {
                    "request": f"POST {path} {data.decode('utf-8', 'replace')}",
                    "status": status,
                    "body": json.loads(body) if body else {},
                }
            )
        return status, body

    def convert(
        self, payload: dict[str, Any], *, record: bool = True
    ) -> tuple[int, dict[str, Any]]:
        status, body = self.post("/v1/conversions", payload, record=record)
        return status, json.loads(body)

    def state(self) -> dict[str, str]:
        """Huella de cada tabla de Units: dos huellas iguales son un dump idéntico."""
        digests: dict[str, str] = {}
        with psycopg.connect(self.admin_url) as conn:
            for table in TABLES:
                row = conn.execute(
                    "SELECT count(*), "
                    "coalesce(md5(string_agg(t::text, '|' ORDER BY t::text)), '') "
                    f"FROM reference.{table} t"
                ).fetchone()
                assert row is not None
                digests[table] = f"{row[0]}:{row[1]}"
        return digests


def wait_until_ready(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("la API terminó antes de estar lista")
        try:
            with urllib.request.urlopen(url + "/v1/units/version", timeout=2):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise RuntimeError("la API no respondió a tiempo")


@pytest.fixture(scope="module")
def units_evidence() -> Iterator[Evidence]:
    configured = os.environ.get("ACCEPTANCE_EVIDENCE_DIR")
    record = Evidence(Path(configured) if configured else None)
    yield record
    if record.directory is None:
        return
    record.directory.mkdir(parents=True, exist_ok=True)
    (record.directory / "commands.json").write_text(
        json.dumps(record.commands, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (record.directory / "http-transcripts.json").write_text(
        json.dumps(record.http, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (record.directory / "inputs-sha256.json").write_text(
        json.dumps(record.inputs, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@pytest.fixture(scope="module")
def units_stack(
    postgres_with_roles: str, tmp_path_factory: pytest.TempPathFactory, units_evidence: Evidence
) -> Iterator[UnitsStack]:
    name = f"acc_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    admin_url = with_database(postgres_with_roles, name)
    command.upgrade(alembic_config(admin_url), "head")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("ALTER ROLE reference_loader LOGIN PASSWORD 'loader-pw'")
        conn.execute("ALTER ROLE reference_reader LOGIN PASSWORD 'reader-pw'")
    loader_url = make_conninfo(admin_url, user="reference_loader", password="loader-pw")
    reader_url = make_conninfo(admin_url, user="reference_reader", password="reader-pw")
    units_evidence.scrub = {"loader-pw": "<loader-pw>", "reader-pw": "<reader-pw>", name: "<base>"}

    work = tmp_path_factory.mktemp("acceptance")
    guard = work / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(GUARD, encoding="utf-8")
    net_log = work / "net.log"
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    system = UnitsStack(
        admin_url, loader_url, reader_url, base_url, work, units_evidence, net_log, guard
    )

    # Prerrequisito cerrado (001): Locale sintético, incorporado con su CLI.
    path = system.write_snapshot("prereq-locales.json", locale_snapshot(1))
    done = system.cli("gi_common_reference.locales.interfaces.cli", "incorporate", str(path))
    assert done.returncode == 0, done.stderr

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--factory",
            "gi_common_reference.app:app_from_environment",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env=system.env(REFERENCE_READER_DATABASE_URL=reader_url),
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_until_ready(base_url, process)
        yield system
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
