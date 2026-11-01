"""Aceptación de 001-locales contra un Postgres real de Supabase (gi-dev), sin UI.

Usa solo las vías oficiales: `alembic upgrade head` (dueño del schema), la CLI de incorporación
(`reference_loader`) y la API (`reference_reader`). Las lecturas de verificación se hacen con el
dueño del schema o con el rol bajo prueba. Ninguna URL ni contraseña se imprime.

Credenciales: JSON `{rol: contraseña}` fuera del repositorio (`--credentials`). Conexión por el
pooler de Supavisor en modo sesión: usuario `<rol>.<project_ref>`.

TLS: por defecto `sslmode=verify-full`, que exige `--sslrootcert`. El pooler presenta una cadena
privada (`Supabase Root 2021 CA`), que no está entre las CA del sistema: el certificado se descarga
del dashboard del proyecto (Database → SSL Configuration). Con `--sslmode require` la conexión va
cifrada pero sin verificar el servidor, y el encabezado de la evidencia lo declara.

Cada comando empieza con un encabezado (entorno, project-ref, destino, TLS, comando y fecha UTC)
para que la evidencia diga contra qué base se generó. No incluye usuarios con contraseña ni URLs.

Uso: python tools/acceptance/gi_dev.py --environment gi-dev --credentials <json> \
    --pooler-host <host> --sslrootcert <ca.crt> <comando> [...]
"""

import argparse
import copy
import hashlib
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable
TABLES = ("locale_snapshot", "locale", "locale_alias")
FINGERPRINT_SQL = {
    "locale_snapshot": "SELECT count(*), md5(coalesce(string_agg(snapshot_version::text || '|' || "
    "content_digest || '|' || iana_file_date || '|' || md5(artifact::text) || '|' || "
    "incorporated_at, ',' ORDER BY snapshot_version), '')) FROM reference.locale_snapshot",
    "locale": "SELECT count(*), md5(coalesce(string_agg(locale_id || '|' || code || '|' || status "
    "|| '|' || iana_deprecated || '|' || coalesce(replacement_locale_id::text, '-') || '|' || "
    "first_snapshot_version, ',' ORDER BY code), '')) FROM reference.locale",
    "locale_alias": "SELECT count(*), md5(coalesce(string_agg(subtag || '>' || "
    "preferred_value, ',' ORDER BY subtag), '')) FROM reference.locale_alias",
}
VERIFYING_SSLMODES = ("verify-ca", "verify-full")


def ca_fingerprints(path: Path) -> list[str]:
    """Huella SHA-256 del DER de cada CA del archivo PEM, como `openssl x509 -fingerprint -sha256`.

    OpenSSL decodifica el PEM, así que la huella no depende de los fines de línea ni del texto
    alrededor de los bloques: es la del certificado, no la del archivo.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        context.load_verify_locations(cafile=path)
    except ssl.SSLError as exc:
        raise ValueError(
            f"{path.name} no contiene un certificado X.509 PEM válido ({exc})"
        ) from exc
    ders = context.get_ca_certs(binary_form=True)
    if not ders:
        raise ValueError(f"{path.name} no contiene ningún certificado de CA")
    return [hashlib.sha256(der).digest().hex(":").upper() for der in ders]


class Env:
    def __init__(
        self,
        credentials: Path,
        host: str,
        ref: str,
        port: int,
        sslmode: str,
        sslrootcert: Path | None,
    ) -> None:
        self._passwords: dict[str, str] = json.loads(credentials.read_text(encoding="utf-8"))
        self._host, self._ref, self._port, self._sslmode = host, ref, port, sslmode
        self._sslrootcert = sslrootcert

    def url(self, role: str) -> str:
        """Con `--project-ref ''` el usuario es el rol a secas (Postgres local de ensayo)."""
        user = f"{role}.{self._ref}" if self._ref else role
        password = quote(self._passwords[role], safe="")
        rootcert = (
            f"&sslrootcert={quote(str(self._sslrootcert), safe='')}" if self._sslrootcert else ""
        )
        return (
            f"postgresql://{user}:{password}@{self._host}:{self._port}/postgres"
            f"?sslmode={self._sslmode}{rootcert}&application_name=gi-common-reference-acceptance"
        )

    def describe_tls(self) -> str:
        if self._sslmode not in VERIFYING_SSLMODES:
            return f"sslmode={self._sslmode} (certificado del servidor NO verificado)"
        assert self._sslrootcert is not None
        digest = ", ".join(ca_fingerprints(self._sslrootcert))
        return (
            f"sslmode={self._sslmode} sslrootcert={self._sslrootcert.name} (SHA-256 DER {digest})"
        )

    def destination(self) -> str:
        return f"{self._host}:{self._port}/postgres"

    def connect(self, role: str) -> "psycopg.Connection[Any]":
        return psycopg.connect(self.url(role), autocommit=True)


def header(env: Env, environment: str, ref: str, command: list[str]) -> None:
    """Identifica la base de la evidencia sin credenciales: nada de URLs ni contraseñas."""
    print(f"# entorno={environment} project_ref={ref or '-'} destino={env.destination()}")
    print(f"# tls: {env.describe_tls()}")
    print(f"# comando={' '.join(command)}")
    print(f"# generado={datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}")


def run(args: list[str], env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **env_extra, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        args, cwd=ROOT, env=env, capture_output=True, encoding="utf-8", timeout=900
    )


def show(result: subprocess.CompletedProcess[str]) -> None:
    print(f"exit={result.returncode}")
    for line in (result.stdout + result.stderr).strip().splitlines()[-25:]:
        print(f"  | {line}")


# --- comandos ---------------------------------------------------------------------------------


def probe(env: Env, _: argparse.Namespace) -> None:
    for role in ("reference_owner", "reference_reader", "reference_loader"):
        with env.connect(role) as conn:
            row = conn.execute("SELECT current_user, version()").fetchone()
            assert row is not None
            print(f"{role}: current_user={row[0]} ({row[1].split(' on ')[0]})")


def migrate(env: Env, _: argparse.Namespace) -> None:
    alembic = [PYTHON, "-m", "alembic"]
    owner = {"REFERENCE_MIGRATION_DATABASE_URL": env.url("reference_owner")}
    show(run([*alembic, "upgrade", "head"], owner))
    show(run([*alembic, "current"], owner))


def inspect(env: Env, _: argparse.Namespace) -> None:
    queries = {
        "schema": "SELECT nspname, nspowner::regrole::text FROM pg_namespace "
        "WHERE nspname = 'reference'",
        "tablas": "SELECT c.relname, c.relowner::regrole::text, c.relrowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'reference' "
        "AND c.relkind = 'r' ORDER BY 1",
        "alembic_version": "SELECT version_num FROM reference.alembic_version",
        "constraints": "SELECT conrelid::regclass::text, conname, contype, condeferrable, "
        "condeferred FROM pg_constraint WHERE connamespace = 'reference'::regnamespace "
        "ORDER BY 1, 2",
        "fks": "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE connamespace = 'reference'::regnamespace AND contype = 'f' ORDER BY 1",
        "triggers": "SELECT tgrelid::regclass::text, tgname, tgfoid::regproc::text FROM pg_trigger "
        "WHERE NOT tgisinternal AND tgrelid::regclass::text LIKE 'reference.%' ORDER BY 1, 2",
        "privilegios_tabla": "SELECT grantee, table_name, string_agg(privilege_type, ',' ORDER BY "
        "privilege_type) FROM information_schema.role_table_grants WHERE table_schema = "
        "'reference' AND grantee <> 'reference_owner' GROUP BY 1, 2 ORDER BY 1, 2",
        "privilegios_columna": "SELECT grantee, table_name, privilege_type, string_agg("
        "column_name, ',' ORDER BY column_name) FROM information_schema.column_privileges "
        "WHERE table_schema = 'reference' AND grantee = 'reference_loader' AND privilege_type = "
        "'UPDATE' GROUP BY 1, 2, 3",
        "acl_schema": "SELECT nspacl::text FROM pg_namespace WHERE nspname = 'reference'",
        "runbook_verify (esperado t,f,t,f,f)": "SELECT "
        "has_table_privilege('reference_reader', 'reference.locale', 'SELECT'), "
        "has_table_privilege('reference_reader', 'reference.locale', 'INSERT'), "
        "has_table_privilege('reference_loader', 'reference.locale', 'INSERT'), "
        "has_table_privilege('reference_loader', 'reference.locale', 'DELETE'), "
        "has_schema_privilege('public', 'reference', 'USAGE')",
    }
    with env.connect("reference_owner") as conn:
        for title, sql in queries.items():
            print(f"## {title}")
            for row in conn.execute(sql).fetchall():
                print("  ", row)


def fingerprint(env: Env) -> dict[str, tuple[int, str]]:
    with env.connect("reference_owner") as conn:
        result = {}
        for table, sql in FINGERPRINT_SQL.items():
            row = conn.execute(sql).fetchone()
            assert row is not None
            result[table] = (row[0], row[1])
        return result


def incorporate(env: Env, args: argparse.Namespace) -> None:
    before = fingerprint(env)
    started = time.monotonic()
    result = run(
        [PYTHON, "-m", "gi_common_reference.locales.interfaces.cli", "incorporate", args.file],
        {"REFERENCE_DATABASE_URL": env.url("reference_loader")},
    )
    print(f"duración={time.monotonic() - started:.1f}s")
    show(result)
    after = fingerprint(env)
    print(f"antes:   {before}")
    print(f"después: {after}")
    print(f"base sin cambios: {before == after}")


def stats(env: Env, _: argparse.Namespace) -> None:
    queries = {
        "conteos": "SELECT (SELECT count(*) FROM reference.locale), "
        "(SELECT count(*) FROM reference.locale WHERE status = 'active'), "
        "(SELECT count(*) FROM reference.locale WHERE status = 'inactive'), "
        "(SELECT count(*) FROM reference.locale WHERE iana_deprecated), "
        "(SELECT count(*) FROM reference.locale WHERE replacement_locale_id IS NOT NULL), "
        "(SELECT count(*) FROM reference.locale_alias), "
        "(SELECT count(*) FROM reference.locale_snapshot)",
        "snapshots": "SELECT snapshot_version, content_digest, iana_file_date, iana_digest, "
        "provenance->>'source', jsonb_array_length(artifact->'locales'), "
        "length(artifact->'iana'->>'registry_text'), incorporated_at "
        "FROM reference.locale_snapshot ORDER BY 1",
        "activos (ejemplos)": "SELECT code, locale_id, status, iana_deprecated "
        "FROM reference.locale "
        "WHERE code IN ('es', 'en', 'he', 'id', 'yi', 'pt', 'fil', 'zh', 'cmn') ORDER BY code",
        "deprecated (ejemplos)": "SELECT code, locale_id, status, iana_deprecated, "
        "replacement_locale_id FROM reference.locale WHERE iana_deprecated ORDER BY code LIMIT 8",
        "alias (ejemplos)": "SELECT a.subtag, a.preferred_value, l.locale_id, l.status "
        "FROM reference.locale_alias a LEFT JOIN reference.locale l ON l.code = a.preferred_value "
        "WHERE a.subtag IN ('iw', 'in', 'ji', 'mo', 'jw', 'tl') OR a.subtag < 'aj' ORDER BY 1",
        "alias sin locale destino": "SELECT a.subtag, a.preferred_value "
        "FROM reference.locale_alias a LEFT JOIN reference.locale l ON l.code = a.preferred_value "
        "WHERE l.code IS NULL",
        "códigos excluidos publicados (debe ser vacío)": "SELECT code FROM reference.locale WHERE "
        "code IN ('und', 'mul', 'mis', 'zxx', 'iw', 'in', 'ji', 'qaa')",
    }
    with env.connect("reference_owner") as conn:
        for title, sql in queries.items():
            print(f"## {title}")
            for row in conn.execute(sql).fetchall():
                print("  ", row)


def _seal(document: dict[str, Any]) -> dict[str, Any]:
    from gi_common_reference.locales.domain.snapshot import content_digest

    document["content_digest"] = content_digest(document)
    return document


def _variants(original: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """(nombre, regla esperada, documento). Cada uno rompe una sola cosa sobre una copia."""
    from gi_common_reference.locales.domain.snapshot import iana_digest

    def variant(change: Callable[[dict[str, Any]], None], seal: bool = True) -> dict[str, Any]:
        document = copy.deepcopy(original)
        change(document)
        return _seal(document) if seal else document

    def by_code(document: dict[str, Any], code: str) -> dict[str, Any]:
        return next(item for item in document["locales"] if item["code"] == code)

    def uppercase(d: dict[str, Any]) -> None:
        d["snapshot_version"] = 3
        by_code(d, "es")["code"] = "ES"

    def wrong_content_digest(d: dict[str, Any]) -> None:
        d["snapshot_version"] = 3
        d["content_digest"] = "sha256:" + "0" * 64

    def wrong_iana_digest(d: dict[str, Any]) -> None:
        d["snapshot_version"] = 3
        d["iana"]["digest"] = "sha256:" + hashlib.sha256(b"otro").hexdigest()

    def same_version_other_digest(d: dict[str, Any]) -> None:
        d["provenance"]["note"] = "mismo snapshot_version, otro contenido"

    def old_unseen(d: dict[str, Any]) -> None:
        d["snapshot_version"] = 1

    def regressive_file_date(d: dict[str, Any]) -> None:
        d["snapshot_version"] = 3
        text = d["iana"]["registry_text"].replace("File-Date: 2026-09-17", "File-Date: 2026-09-01")
        d["iana"].update(file_date="2026-09-01", registry_text=text, digest=iana_digest(text))

    def file_date_mismatch(d: dict[str, Any]) -> None:
        d["snapshot_version"] = 3
        d["iana"]["file_date"] = "2026-09-18"

    def publish_alias_code(d: dict[str, Any]) -> None:
        # `iw` tiene Preferred-Value `he`: no es su propia forma preferida y no se publica (RF-4).
        d["snapshot_version"] = 3
        he = by_code(d, "he")["locale_id"]
        d["locales"].append(
            {
                "locale_id": "00000000-0000-4000-8000-0000000000aa",
                "code": "iw",
                "status": "inactive",
                "iana_deprecated": True,
                "replacement_locale_id": he,
            }
        )

    def replacement_without_preferred(d: dict[str, Any]) -> None:
        d["snapshot_version"] = 3
        deprecated = next(item for item in d["locales"] if item["iana_deprecated"])
        deprecated["replacement_locale_id"] = by_code(d, "es")["locale_id"]

    def empty_preferred_value(d: dict[str, Any]) -> None:
        d["snapshot_version"] = 3
        text = d["iana"]["registry_text"].replace(
            "Subtag: iw\n", "Subtag: iw\nPreferred-Value:\n", 1
        )
        text = text.replace("Preferred-Value: he\n", "", 1)
        d["iana"].update(registry_text=text, digest=iana_digest(text))

    def omit_published(d: dict[str, Any]) -> None:
        d["snapshot_version"] = 3
        d["locales"] = [item for item in d["locales"] if item["code"] != "es"]

    def deprecated_active(d: dict[str, Any]) -> None:
        d["snapshot_version"] = 3
        next(item for item in d["locales"] if item["iana_deprecated"])["status"] = "active"

    return [
        ("code en mayúsculas", "RF-28", variant(uppercase)),
        ("content_digest incorrecto", "RF-31", variant(wrong_content_digest, seal=False)),
        ("digest IANA incorrecto", "RF-30", variant(wrong_iana_digest)),
        ("snapshot_version existente con otro digest", "RF-32", variant(same_version_other_digest)),
        ("snapshot viejo nunca visto (v1 < v2)", "RF-32", variant(old_unseen)),
        ("File-Date regresivo", "RF-29", variant(regressive_file_date)),
        ("File-Date declarado distinto del artefacto", "RF-30", variant(file_date_mismatch)),
        ("Preferred-Value: publicar iw como locale nuevo", "RF-4", variant(publish_alias_code)),
        (
            "replacement sin Preferred-Value en IANA",
            "RF-26",
            variant(replacement_without_preferred),
        ),
        ("Preferred-Value vacío en el artefacto", "RF-30", variant(empty_preferred_value)),
        ("omite un locale publicado", "RF-15", variant(omit_published)),
        ("deprecado con status active", "RF-27", variant(deprecated_active)),
    ]


def negatives(env: Env, args: argparse.Namespace) -> None:
    original_bytes = Path(args.file).read_bytes()
    original = json.loads(original_bytes)
    cli = [PYTHON, "-m", "gi_common_reference.locales.interfaces.cli", "incorporate"]
    loader = {"REFERENCE_DATABASE_URL": env.url("reference_loader")}
    failures = 0
    with tempfile.TemporaryDirectory(prefix="locale-negatives-") as tmp:
        for index, (name, rule, document) in enumerate(_variants(original), start=1):
            path = Path(tmp) / f"variant-{index:02d}.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            before = fingerprint(env)
            result = run([*cli, str(path)], loader)
            after = fingerprint(env)
            output = result.stdout + result.stderr
            ok = result.returncode == 1 and f"{rule}:" in output and before == after
            failures += not ok
            first = next((line for line in output.splitlines() if line.startswith("  - ")), "")
            print(
                f"[{'PASS' if ok else 'FAIL'}] {name}: exit={result.returncode} "
                f"esperado={rule} base_idéntica={before == after}"
            )
            print(f"        {first.strip()[:160]}")
    unchanged = Path(args.file).read_bytes() == original_bytes
    print(f"snapshot original intacto: {unchanged}")
    print(f"resultado: {'PASS' if failures == 0 and unchanged else f'FAIL ({failures})'}")


def _expect_error(conn: "psycopg.Connection[Any]", sql: str) -> str:
    try:
        with conn.transaction(force_rollback=True):
            conn.execute(sql)
        return "PERMITIDO"
    except psycopg.Error as error:
        return f"denegado ({type(error).__name__}, SQLSTATE {error.sqlstate})"


def _expect_ok(conn: "psycopg.Connection[Any]", sql: str) -> str:
    try:
        with conn.transaction(force_rollback=True):
            conn.execute(sql)
        return "permitido (rollback)"
    except psycopg.Error as error:
        return f"DENEGADO ({type(error).__name__}, SQLSTATE {error.sqlstate})"


def security(env: Env, _: argparse.Namespace) -> None:
    before = fingerprint(env)
    alias_row = "INSERT INTO reference.locale_alias VALUES ('zz', 'es')"
    checks: list[tuple[str, str, Callable[..., str], str]] = [
        ("reference_reader", "SELECT locale", _expect_ok, "SELECT count(*) FROM reference.locale"),
        (
            "reference_reader",
            "SELECT alias",
            _expect_ok,
            "SELECT count(*) FROM reference.locale_alias",
        ),
        (
            "reference_reader",
            "SELECT snapshot",
            _expect_ok,
            "SELECT count(*) FROM reference.locale_snapshot",
        ),
        ("reference_reader", "INSERT alias", _expect_error, alias_row),
        (
            "reference_reader",
            "UPDATE locale.status",
            _expect_error,
            "UPDATE reference.locale SET status = status",
        ),
        ("reference_reader", "DELETE alias", _expect_error, "DELETE FROM reference.locale_alias"),
        (
            "reference_reader",
            "CREATE TABLE en reference",
            _expect_error,
            "CREATE TABLE reference.x (id int)",
        ),
        ("reference_loader", "SELECT locale", _expect_ok, "SELECT count(*) FROM reference.locale"),
        (
            "reference_loader",
            "UPDATE locale (status, iana_deprecated, replacement)",
            _expect_ok,
            "UPDATE reference.locale SET status = status, iana_deprecated = iana_deprecated, "
            "replacement_locale_id = replacement_locale_id WHERE code = 'es'",
        ),
        (
            "reference_loader",
            "INSERT + DELETE alias",
            _expect_ok,
            f"{alias_row}; DELETE FROM reference.locale_alias WHERE subtag = 'zz'",
        ),
        (
            "reference_loader",
            "UPDATE locale.code",
            _expect_error,
            "UPDATE reference.locale SET code = code WHERE code = 'es'",
        ),
        (
            "reference_loader",
            "UPDATE locale.first_snapshot_version",
            _expect_error,
            "UPDATE reference.locale SET first_snapshot_version = first_snapshot_version",
        ),
        (
            "reference_loader",
            "DELETE locale",
            _expect_error,
            "DELETE FROM reference.locale WHERE code = 'es'",
        ),
        (
            "reference_loader",
            "UPDATE locale_snapshot",
            _expect_error,
            "UPDATE reference.locale_snapshot SET provenance = provenance",
        ),
        (
            "reference_loader",
            "DELETE locale_snapshot",
            _expect_error,
            "DELETE FROM reference.locale_snapshot",
        ),
        ("reference_loader", "TRUNCATE locale", _expect_error, "TRUNCATE reference.locale"),
        (
            "reference_loader",
            "CREATE TABLE en reference",
            _expect_error,
            "CREATE TABLE reference.x (id int)",
        ),
        (
            "reference_owner",
            "DELETE locale (trigger)",
            _expect_error,
            "DELETE FROM reference.locale WHERE code = 'es'",
        ),
        (
            "reference_owner",
            "UPDATE locale.code (trigger)",
            _expect_error,
            "UPDATE reference.locale SET code = 'xx' WHERE code = 'es'",
        ),
        (
            "reference_owner",
            "UPDATE locale_snapshot (trigger)",
            _expect_error,
            "UPDATE reference.locale_snapshot SET provenance = provenance",
        ),
        (
            "reference_owner",
            "TRUNCATE locale_snapshot (trigger)",
            _expect_error,
            "TRUNCATE reference.locale_snapshot CASCADE",
        ),
        (
            "reference_owner",
            "code en mayúsculas (CHECK)",
            _expect_error,
            "INSERT INTO reference.locale VALUES (gen_random_uuid(), 'EN', 'active', false, null, "
            "2)",
        ),
        (
            "reference_owner",
            "deprecado active (CHECK)",
            _expect_error,
            "UPDATE reference.locale SET iana_deprecated = true WHERE code = 'es'",
        ),
        (
            "reference_owner",
            "replacement inexistente (FK diferida)",
            _expect_error,
            "UPDATE reference.locale SET iana_deprecated = true, status = 'inactive', "
            "replacement_locale_id = gen_random_uuid() WHERE code = 'es'; SET CONSTRAINTS ALL "
            "IMMEDIATE",
        ),
    ]
    for role, title, check, sql in checks:
        with env.connect(role) as conn:
            print(f"{role:17} {title:55} {check(conn, sql)}")

    print("## privilegios de roles de la API de Supabase y PUBLIC sobre reference")
    with env.connect("reference_owner") as conn:
        rows = conn.execute(
            "SELECT r.rolname, has_schema_privilege(r.oid, 'reference', 'USAGE'), "
            "bool_or(has_table_privilege(r.oid, 'reference.' || t, p)) "
            "FROM pg_roles r, unnest(ARRAY['locale','locale_alias','locale_snapshot']) t, "
            "unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE']) p "
            "WHERE r.rolname IN ('anon', 'authenticated', 'service_role', 'authenticator') "
            "GROUP BY r.rolname, r.oid ORDER BY 1"
        ).fetchall()
        for name, usage, any_table in rows:
            print(f"  {name:15} USAGE schema={usage} algún privilegio de tabla={any_table}")
        public = conn.execute(
            "SELECT has_schema_privilege('public', 'reference', 'USAGE'), "
            "(SELECT count(*) FROM information_schema.role_table_grants "
            "WHERE table_schema = 'reference' AND grantee = 'PUBLIC')"
        ).fetchone()
        print(
            f"  PUBLIC          USAGE schema={public and public[0]} grants de tabla="
            f"{public and public[1]}"
        )
    print(f"base sin cambios tras las pruebas: {before == fingerprint(env)}")


def api(env: Env, args: argparse.Namespace) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen(
        [
            PYTHON,
            "-m",
            "uvicorn",
            "--factory",
            "gi_common_reference.app:app_from_environment",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env={**os.environ, "REFERENCE_READER_DATABASE_URL": env.url("reference_reader")},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
    )
    base = f"http://127.0.0.1:{port}"
    failures = 0

    def check(name: str, ok: bool, detail: str) -> None:
        nonlocal failures
        failures += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    try:
        with httpx.Client(base_url=base, timeout=60) as client:
            for _ in range(60):
                try:
                    client.get("/v1/openapi.json")
                    break
                except httpx.TransportError:
                    time.sleep(0.5)
            listing = client.get("/v1/locales")
            body = listing.json()
            version = body["snapshot_version"]
            codes = [item["code"] for item in body["data"]]
            ordered = codes == sorted(codes)
            check(
                "GET /v1/locales",
                listing.status_code == 200 and len(codes) == args.total and ordered,
                f"{listing.status_code} snapshot_version={version} n={len(codes)} "
                f"primeros={codes[:5]} ordenado={ordered}",
            )
            for status, expected in (("active", args.active), ("inactive", args.inactive)):
                response = client.get("/v1/locales", params={"status": status})
                data = response.json()["data"]
                check(
                    f"GET /v1/locales?status={status}",
                    response.status_code == 200
                    and len(data) == expected
                    and all(x["status"] == status for x in data),
                    f"{response.status_code} n={len(data)}",
                )
            es = client.get("/v1/locales/by-code/es")
            es_data = es.json()["data"]
            check(
                "GET /by-code/es",
                es.status_code == 200 and es_data["code"] == "es",
                f"{es.status_code} {es.json()}",
            )
            upper = client.get("/v1/locales/by-code/ES")
            check(
                "GET /by-code/ES (tolera mayúsculas)",
                upper.status_code == 200 and upper.json()["data"] == es_data,
                f"{upper.status_code}",
            )
            by_id = client.get(f"/v1/locales/{es_data['locale_id']}")
            check(
                "GET /{locale_id}",
                by_id.status_code == 200 and by_id.json()["data"] == es_data,
                f"{by_id.status_code} {by_id.json()}",
            )
            by_id_upper = client.get(f"/v1/locales/{es_data['locale_id'].upper()}")
            check(
                "GET /{LOCALE_ID en mayúsculas}",
                by_id_upper.status_code == 200,
                f"{by_id_upper.status_code}",
            )
            he = client.get("/v1/locales/by-code/he").json()["data"]
            for alias, target in (("iw", he), ("IW", he)):
                response = client.get(f"/v1/locales/by-code/{alias}")
                check(
                    f"GET /by-code/{alias} (alias Preferred-Value → he)",
                    response.status_code == 200 and response.json()["data"] == target,
                    f"{response.status_code} {response.json()}",
                )
            for alias, code in (("in", "id"), ("ji", "yi")):
                response = client.get(f"/v1/locales/by-code/{alias}")
                check(
                    f"GET /by-code/{alias} → {code}",
                    response.status_code == 200 and response.json()["data"]["code"] == code,
                    f"{response.status_code} code={response.json().get('data', {}).get('code')}",
                )
            deprecated = client.get("/v1/locales", params={"status": "inactive"}).json()["data"][0]
            response = client.get(f"/v1/locales/by-code/{deprecated['code']}")
            check(
                "GET /by-code/<deprecado sin Preferred-Value>",
                response.status_code == 200 and response.json()["data"]["iana_deprecated"],
                f"{response.status_code} {response.json()}",
            )
            for path, expected_status, expected_code in (
                ("/v1/locales/by-code/qaa", 404, "not_found"),
                ("/v1/locales/by-code/und", 404, "not_found"),
                ("/v1/locales/00000000-0000-4000-8000-000000000000", 404, "not_found"),
                ("/v1/locales/no-es-uuid", 404, "not_found"),
                ("/v1/locales/by-code/es-AR", 422, "invalid_code"),
                ("/v1/locales/by-code/e", 422, "invalid_code"),
                ("/v1/locales/by-code/%20es", 422, "invalid_code"),
                ("/v1/locales?status=deprecated", 422, "invalid_status"),
            ):
                response = client.get(path)
                body = response.json()
                check(
                    f"GET {path}",
                    response.status_code == expected_status
                    and body["error"]["code"] == expected_code
                    and body["snapshot_version"] == version,
                    f"{response.status_code} {body}",
                )
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                for path in (
                    "/v1/locales",
                    f"/v1/locales/{es_data['locale_id']}",
                    "/v1/locales/by-code/es",
                ):
                    response = client.request(method, path, json={})
                    check(
                        f"{method} {path}", response.status_code == 405, f"{response.status_code}"
                    )
            paths = client.get("/v1/openapi.json").json()["paths"]
            methods = sorted({m for item in paths.values() for m in item})
            check(
                "OpenAPI: solo GET", methods == ["get"], f"paths={sorted(paths)} métodos={methods}"
            )
            published = json.loads(
                (ROOT / "contracts" / "locales-api.v1.openapi.json").read_text(encoding="utf-8")
            )
            check(
                "OpenAPI servido == contrato publicado",
                client.get("/v1/openapi.json").json() == published,
                "comparación JSON",
            )
            check("docs deshabilitados", client.get("/docs").status_code == 404, "/docs → 404")
    finally:
        server.terminate()
        try:
            output, _ = server.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
            output, _ = server.communicate()
    errors = [line for line in output.splitlines() if "ERROR" in line or "Traceback" in line]
    print(f"log del servidor: {len(output.splitlines())} líneas, {len(errors)} con ERROR")
    print(f"resultado: {'PASS' if failures == 0 else f'FAIL ({failures})'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--environment", required=True, help="entorno que se declara en la evidencia (gi-dev, …)"
    )
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--pooler-host", required=True)
    parser.add_argument("--project-ref", default="gletzbwuvmwjkmoufmyj")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--sslmode", default="verify-full")
    parser.add_argument("--sslrootcert", type=Path, help="CA del servidor (PEM)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "migrate", "inspect", "stats", "security"):
        commands.add_parser(name)
    for name in ("incorporate", "negatives"):
        commands.add_parser(name).add_argument("file")
    api_parser = commands.add_parser("api")
    for name in ("total", "active", "inactive"):
        api_parser.add_argument(f"--{name}", type=int, required=True)
    args = parser.parse_args()
    if args.sslmode in VERIFYING_SSLMODES and args.sslrootcert is None:
        parser.error(
            f"--sslmode {args.sslmode} exige --sslrootcert: la CA de Supabase no es del sistema "
            "(dashboard: Database > SSL Configuration). Sin verificar: --sslmode require"
        )
    if args.sslrootcert is not None and not args.sslrootcert.is_file():
        parser.error(f"--sslrootcert: no existe {args.sslrootcert}")
    if args.sslrootcert is not None:
        try:
            ca_fingerprints(args.sslrootcert)
        except ValueError as exc:
            parser.error(f"--sslrootcert: {exc}")
    env = Env(
        args.credentials,
        args.pooler_host,
        args.project_ref,
        args.port,
        args.sslmode,
        args.sslrootcert,
    )
    command = [args.command]
    if args.command in ("incorporate", "negatives"):
        command.append(Path(args.file).name)
    if args.command == "api":
        command += [
            f"--total {args.total}",
            f"--active {args.active}",
            f"--inactive {args.inactive}",
        ]
    header(env, args.environment, args.project_ref, command)
    handlers: dict[str, Callable[[Env, argparse.Namespace], None]] = {
        "probe": probe,
        "migrate": migrate,
        "inspect": inspect,
        "incorporate": incorporate,
        "stats": stats,
        "negatives": negatives,
        "security": security,
        "api": api,
    }
    handlers[args.command](env, args)


if __name__ == "__main__":
    main()
