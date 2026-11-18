"""Soporte de la aceptación transversal 006 (001–005 en conjunto, caja negra).

Módulo nuevo: no modifica `conftest.py` ni las aceptaciones de 004/005. Reutiliza de ahí el guard
de red, el registro de evidencia y el `Stack`. A diferencia de 004 (que siembra Countries con SQL),
aquí **cada catálogo se incorpora con su propia CLI**, en el orden del grafo de dependencias, sobre
una base Postgres descartable migrada con `alembic` como subproceso; la API real (uvicorn, rol
`reference_reader`) sirve los cinco catálogos a la vez.

Los datos son sintéticos, deterministas y NO productivos: salen de los builders de
`tests/fixtures/*` (los mismos que usan las suites de cada módulo), así que cada ejecución produce
byte a byte los mismos snapshots (sus sha256 quedan en la evidencia).
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from tests.acceptance.conftest import GUARD, ROOT, Evidence, Stack, free_port
from tests.conftest import with_database
from tests.fixtures import countries as countries_fx
from tests.fixtures import currencies as currencies_fx
from tests.fixtures import units as units_fx
from tests.fixtures.regions import locale_snapshot

CLI = {
    "locales": "gi_common_reference.locales.interfaces.cli",
    "regions": "gi_common_reference.regions.interfaces.cli",
    "countries": "gi_common_reference.countries.interfaces.cli",
    "currencies": "gi_common_reference.currencies.interfaces.cli",
    "units": "gi_common_reference.units.interfaces.cli",
}
# Orden topológico del grafo de dependencias (docs/dependency-graph.json).
ORDER = ("locales", "regions", "countries", "currencies", "units")
GRAPH = ROOT / "docs" / "dependency-graph.json"

# Países del snapshot de Countries (fixture de 003) que Currency referencia por `country_id`.
CURRENCY_CODES = ("ARS", "USD", "EUR", "JPY", "XAU")


def currency_association(alpha2: str, code: str, start: date | None = None) -> dict[str, Any]:
    """Asociación país-moneda que apunta al `country_id` REAL publicado por Countries."""
    return currencies_fx.association(
        alpha2, code, start, None, country_id=countries_fx.country_id(alpha2)
    )


def currency_snapshot(version: int = 1, **overrides: Any) -> dict[str, Any]:
    associations = overrides.pop(
        "country_currencies",
        [
            currency_association("AR", "ARS"),
            currency_association("US", "USD"),
            currency_association("PR", "USD", date(1899, 1, 1)),
        ],
    )
    return currencies_fx.build_snapshot(
        version, codes=CURRENCY_CODES, country_currencies=associations, **overrides
    )


def countries_snapshot(version: int = 1, **overrides: Any) -> dict[str, Any]:
    """Snapshot de Countries para la CLI INSTALADA: el paquete no trae SVG de bandera hasta que
    PREP aporte el dataset real (003, S-7), así que cada país declara una excepción de bandera
    (mismo criterio que `test_the_cli_module_runs_as_documented_with_the_loader_role` de 003)."""
    keys = overrides.pop("keys", countries_fx.DEFAULT_KEYS)
    document = countries_fx.build_snapshot(
        version,
        keys=keys,
        flags=[],
        flag_exceptions=[
            {
                "country_id": countries_fx.country_id(k),
                "reason": countries_fx.FLAG_EXCEPTIONS.get(
                    k, "Asset SVG pendiente del dataset de PREP (sintético, no productivo)"
                ),
            }
            for k in keys
        ],
        **overrides,
    )
    document["provenance"]["sources"] = [
        s for s in document["provenance"]["sources"] if s["role"] != "flags"
    ]
    return countries_fx.seal(document)


GHOST = "00000000-0000-4000-8000-000000000000"


def countries_with_ghost_region(version: int = 2) -> dict[str, Any]:
    """Countries v2 cuyo país BV apunta a una Region inexistente (CA-7)."""
    keys = countries_fx.DEFAULT_KEYS
    return countries_snapshot(
        version,
        countries=[countries_fx.country(k) for k in keys if k != "BV"]
        + [countries_fx.country("BV", region_id=GHOST, subregion_id=None)],
    )


def countries_retiring_pr(version: int = 2) -> dict[str, Any]:
    """Countries v2 que retira PR (`inactive`) sin conocer Currency (CA-15)."""
    return countries_snapshot(
        version,
        countries=[
            countries_fx.country(k, status="inactive") if k == "PR" else countries_fx.country(k)
            for k in countries_fx.DEFAULT_KEYS
        ],
    )


def currencies_closing_pr(version: int = 2) -> dict[str, Any]:
    """Currency v2 sobre Countries v2: cierra la vigencia PR–USD el 2026-01-01 (CA-15)."""
    return currency_snapshot(
        version,
        country_snapshot_version=2,
        country_currencies=[
            currency_association("AR", "ARS"),
            currency_association("US", "USD"),
            currencies_fx.association(
                "PR",
                "USD",
                date(1899, 1, 1),
                date(2026, 1, 1),
                country_id=countries_fx.country_id("PR"),
            ),
        ],
    )


def snapshots() -> dict[str, dict[str, Any]]:
    """Dataset v1 de los cinco catálogos, coherente entre sí."""
    return {
        "locales": locale_snapshot(1),
        "regions": countries_fx.regions_snapshot(1),
        "countries": countries_snapshot(1),
        "currencies": currency_snapshot(1),
        "units": units_fx.build_snapshot(1),
    }


@dataclass
class ReferenceStack(Stack):
    """Los cinco catálogos: CLI por subproceso, migraciones por subproceso, API real por HTTP."""

    database: str = ""
    server: str = ""

    def catalog(
        self, module: str, *args: str, url: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return self.cli(CLI[module], *args, url=url)

    def incorporate(self, module: str, document: dict[str, Any], name: str) -> Any:
        return self.catalog(module, "incorporate", str(self.write_snapshot(name, document)))

    def alembic(self, *args: str, url: str | None = None) -> subprocess.CompletedProcess[str]:
        """`alembic` como subproceso, con el rol dueño del schema (nunca el de la CLI)."""
        env = self.env(REFERENCE_MIGRATION_DATABASE_URL=url or self.admin_url)
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            env=env,
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=300,
            check=False,
        )
        self.evidence.commands.append(
            {
                "command": "python -m alembic " + " ".join(args),
                "exit_code": result.returncode,
                "stdout": self.evidence.clean(result.stdout.strip()),
                "stderr": self.evidence.clean(_alembic_noise(result.stderr)),
            }
        )
        return result

    def post(self, path: str, payload: Any) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            self.base_url + path,
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        status, body = self._send(request, path)
        return status, body

    def fingerprint(self, url: str | None = None) -> dict[str, str]:
        """Huella de TODAS las tablas del schema `reference`: igual ⇔ dump lógico idéntico."""
        digests: dict[str, str] = {}
        with psycopg.connect(url or self.admin_url) as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'reference' AND table_type = 'BASE TABLE' "
                    "AND table_name <> 'alembic_version' ORDER BY table_name"
                )
            ]
            for table in tables:
                row = conn.execute(
                    "SELECT count(*), "
                    "coalesce(md5(string_agg(t::text, '|' ORDER BY t::text)), '') "
                    f"FROM reference.{table} t"
                ).fetchone()
                assert row is not None
                digests[table] = f"{row[0]}:{row[1]}"
        return digests


def _alembic_noise(stderr: str) -> str:
    """Alembic informa por stderr (`INFO [alembic...]`): se conserva tal cual, sin rutas."""
    return stderr.replace(str(ROOT), "<repo>").strip()


def new_database(postgres_with_roles: str) -> tuple[str, str]:
    """Base vacía nueva (sin migrar) y su URL de administrador."""
    name = f"acc_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    return name, with_database(postgres_with_roles, name)


def drop_database(postgres_with_roles: str, name: str) -> None:
    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def wait_until_ready(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("la API terminó antes de estar lista")
        try:
            with urllib.request.urlopen(url + "/v1/locales", timeout=2):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise RuntimeError("la API no respondió a tiempo")


@pytest.fixture(scope="module")
def cross_evidence() -> Iterator[Evidence]:
    configured = os.environ.get("ACCEPTANCE_EVIDENCE_DIR")
    record = Evidence(Path(configured) if configured else None)
    yield record
    if record.directory is None:
        return
    record.directory.mkdir(parents=True, exist_ok=True)
    for name, data in (
        ("commands.json", record.commands),
        ("http-transcripts.json", record.http),
    ):
        (record.directory / name).write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
    (record.directory / "inputs-sha256.json").write_text(
        json.dumps(record.inputs, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def _make_stack(
    postgres_with_roles: str, work: Path, evidence: Evidence
) -> tuple[ReferenceStack, Callable[[], None]]:
    name, admin_url = new_database(postgres_with_roles)
    guard = work / "guard"
    guard.mkdir(exist_ok=True)
    (guard / "sitecustomize.py").write_text(GUARD, encoding="utf-8")
    loader_url = make_conninfo(admin_url, user="reference_loader", password="loader-pw")
    reader_url = make_conninfo(admin_url, user="reference_reader", password="reader-pw")
    port = free_port()
    stack = ReferenceStack(
        admin_url,
        loader_url,
        reader_url,
        f"http://127.0.0.1:{port}",
        work,
        evidence,
        work / "net.log",
        guard,
        database=name,
    )
    evidence.scrub.update({"loader-pw": "<loader-pw>", "reader-pw": "<reader-pw>", name: "<base>"})
    return stack, lambda: drop_database(postgres_with_roles, name)


@pytest.fixture(scope="module")
def reference_stack(
    postgres_with_roles: str, tmp_path_factory: pytest.TempPathFactory, cross_evidence: Evidence
) -> Iterator[ReferenceStack]:
    """Base migrada por subproceso, cinco catálogos v1 incorporados por CLI y API arrancada."""
    work = tmp_path_factory.mktemp("cross")
    stack, drop = _make_stack(postgres_with_roles, work, cross_evidence)
    try:
        migrated = stack.alembic("upgrade", "head")
        assert migrated.returncode == 0, migrated.stderr
        with psycopg.connect(stack.admin_url, autocommit=True) as conn:
            conn.execute("ALTER ROLE reference_loader LOGIN PASSWORD 'loader-pw'")
            conn.execute("ALTER ROLE reference_reader LOGIN PASSWORD 'reader-pw'")
        for module, document in snapshots().items():
            done = stack.incorporate(module, document, f"{module}-v1.json")
            assert done.returncode == 0, (module, done.stdout, done.stderr)
        port = stack.base_url.rsplit(":", 1)[1]
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
                port,
                "--log-level",
                "warning",
            ],
            env=stack.env(REFERENCE_READER_DATABASE_URL=stack.reader_url),
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            wait_until_ready(stack.base_url, process)
            yield stack
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
    finally:
        drop()


@pytest.fixture
def blank_stack(
    postgres_with_roles: str, tmp_path: Path, cross_evidence: Evidence
) -> Iterator[ReferenceStack]:
    """Base nueva y vacía (sin migrar), sin API: para órdenes inválidos y ciclos de migración."""
    stack, drop = _make_stack(postgres_with_roles, tmp_path, cross_evidence)
    try:
        yield stack
    finally:
        drop()
