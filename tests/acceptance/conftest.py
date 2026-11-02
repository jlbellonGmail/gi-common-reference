"""Aceptación de 004-currency: caja negra sobre el sistema real (D24 del plan).

Levanta una base Postgres descartable (testcontainers), aplica `alembic upgrade head`, incorpora
Locale y Regions con sus CLI, siembra Countries sintético (003 no se redefine: se consume),
incorpora Currency con **su CLI como subproceso** y consulta la **API real (uvicorn) por HTTP**.
Ambos subprocesos corren con un guard de red (`sitecustomize`) que registra y bloquea todo acceso a
hosts que no sean locales: es la prueba de que Currency no depende en runtime de ISO, CLDR ni de
nada externo (RF-42, CA-14).

Si `ACCEPTANCE_EVIDENCE_DIR` está definido, deja ahí las transcripciones (comandos, salidas y
respuestas HTTP) para `acceptance/currencies/evidence/`. Todo el contenido es sintético y NO
productivo (S-9).
"""

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from psycopg.conninfo import make_conninfo

from tests.conftest import alembic_config, with_database
from tests.fixtures.countries import regions_snapshot
from tests.fixtures.regions import locale_snapshot
from tests.integration.currencies.test_incorporation import seed_countries

ROOT = Path(__file__).resolve().parents[2]
GUARD = """\
import os, socket

LOG = os.environ["ACCEPTANCE_NET_LOG"]
LOCAL = {"127.0.0.1", "localhost", "::1", None}


def _record(kind, host):
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(f"{kind} {host}\\n")


def _host(address):
    return address[0] if isinstance(address, tuple) else None


_connect, _connect_ex, _getaddrinfo = (
    socket.socket.connect,
    socket.socket.connect_ex,
    socket.getaddrinfo,
)


def connect(self, address):
    host = _host(address)
    if host not in LOCAL:
        _record("BLOCKED connect", host)
        raise OSError("acceso de red bloqueado por el guard de aceptacion")
    return _connect(self, address)


def connect_ex(self, address):
    host = _host(address)
    if host not in LOCAL:
        _record("BLOCKED connect_ex", host)
        return 111
    return _connect_ex(self, address)


def getaddrinfo(host, *args, **kwargs):
    if host not in LOCAL:
        _record("BLOCKED getaddrinfo", host)
        raise OSError("resolucion de nombres bloqueada por el guard de aceptacion")
    return _getaddrinfo(host, *args, **kwargs)


socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = (
    connect,
    connect_ex,
    getaddrinfo,
)
"""


def sha256_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass
class Evidence:
    """Transcripciones normalizadas (sin puertos, nombres de base ni contraseñas)."""

    directory: Path | None
    commands: list[dict[str, Any]] = field(default_factory=list)
    http: list[dict[str, Any]] = field(default_factory=list)
    inputs: dict[str, str] = field(default_factory=dict)
    scrub: dict[str, str] = field(default_factory=dict)

    def clean(self, text: str) -> str:
        for secret, placeholder in self.scrub.items():
            text = text.replace(secret, placeholder)
        return re.sub(r"127\.0\.0\.1:\d+", "127.0.0.1:<puerto>", text)


@dataclass
class Stack:
    """El sistema bajo prueba: CLI como subproceso y API real por HTTP."""

    admin_url: str
    loader_url: str
    reader_url: str
    base_url: str
    work: Path
    evidence: Evidence
    net_log: Path
    guard: Path

    def env(self, **extra: str) -> dict[str, str]:
        base = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
        return {
            **base,
            "PYTHONUTF8": "1",
            "PYTHONPATH": str(self.guard),
            "ACCEPTANCE_NET_LOG": str(self.net_log),
            **extra,
        }

    def cli(
        self, module: str, *args: str, url: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        argv = [sys.executable, "-m", module, *args]
        result = subprocess.run(
            argv,
            env=self.env(REFERENCE_DATABASE_URL=url or self.loader_url),
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=300,
            check=False,
        )
        self.evidence.commands.append(
            {
                "command": self.evidence.clean(
                    " ".join(
                        [
                            "python",
                            "-m",
                            module,
                            *(a.replace(str(self.work), "<work>") for a in args),
                        ]
                    )
                ),
                "exit_code": result.returncode,
                "stdout": self.evidence.clean(result.stdout.strip()),
                "stderr": self.evidence.clean(result.stderr.strip()),
            }
        )
        return result

    def currency(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.cli("gi_common_reference.currencies.interfaces.cli", *args)

    def write_snapshot(self, name: str, document: dict[str, Any]) -> Path:
        path = self.work / name
        data = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
        path.write_bytes(data)
        self.evidence.inputs[name] = sha256_of(data)
        return path

    def get(self, path: str) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(self.base_url + path, method="GET")
        return self._send(request, path)

    def send(self, method: str, path: str) -> int:
        request = urllib.request.Request(self.base_url + path, method=method, data=b"{}")
        return self._send(request, path)[0]

    def _send(self, request: urllib.request.Request, path: str) -> tuple[int, dict[str, Any]]:
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        body = json.loads(raw) if raw else {}
        self.evidence.http.append(
            {"request": f"{request.get_method()} {path}", "status": status, "body": body}
        )
        return status, body


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_ready(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("la API terminó antes de estar lista")
        try:
            with urllib.request.urlopen(url + "/v1/currencies/version", timeout=2):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise RuntimeError("la API no respondió a tiempo")


@pytest.fixture(scope="module")
def evidence() -> Iterator[Evidence]:
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
def stack(
    postgres_with_roles: str, tmp_path_factory: pytest.TempPathFactory, evidence: Evidence
) -> Iterator[Stack]:
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
    evidence.scrub = {"loader-pw": "<loader-pw>", "reader-pw": "<reader-pw>", name: "<base>"}

    work = tmp_path_factory.mktemp("acceptance")
    guard = work / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(GUARD, encoding="utf-8")
    net_log = work / "net.log"
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    system = Stack(admin_url, loader_url, reader_url, base_url, work, evidence, net_log, guard)

    # Prerrequisitos cerrados (001–003): se consumen, no se redefinen.
    for module, document in (
        ("gi_common_reference.locales.interfaces.cli", locale_snapshot(1)),
        ("gi_common_reference.regions.interfaces.cli", regions_snapshot(1)),
    ):
        path = system.write_snapshot(f"prereq-{module.split('.')[1]}.json", document)
        done = system.cli(module, "incorporate", str(path))
        assert done.returncode == 0, done.stderr
    seed_countries(
        admin_url
    )  # Countries sintético, sembrado: 003 no se modifica ni se reimplementa

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
