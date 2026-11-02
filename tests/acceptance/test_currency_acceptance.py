"""Aceptación de 004-currency (caja negra). Cada caso nombra los criterios de la spec que verifica.

CA-1 tiene dos partes. (a) MECANISMO: el catálogo cargado desde un snapshot respeta D-8 (todo
`active`, sin `XTS` ni `XXX`); se ejecuta aquí con un snapshot SINTÉTICO sellado y no productivo.
(b) CONTENIDO: que el catálogo sea exactamente ISO 4217 List One de la edición declarada; exige el
dataset real que produce PREP (S-9) y está DIFERIDO: este módulo NO lo verifica ni lo cuenta como
ejecutado. Ver `acceptance/currencies/README.md`.

El orden de los casos importa: comparten el sistema (módulo): primero el snapshot 1, después la
transición HRK → EUR (snapshot 2), después los rechazos.
"""

import ast
import subprocess
import sys
from datetime import date
from typing import Any

import psycopg
import pytest

from tests.acceptance.conftest import ROOT, Stack
from tests.fixtures.currencies import (
    DEFAULT_CODES,
    EN,
    ES,
    association,
    build_snapshot,
    country_id,
    currency,
    currency_id,
    names,
    seal,
    transition_snapshot,
)

BASE_REF = "origin/develop"
FORBIDDEN_IMPORTS = {
    "httpx",
    "requests",
    "urllib",
    "http",
    "socket",
    "aiohttp",
    "ftplib",
    "smtplib",
}
EXTERNAL_HINTS = (
    "iso.org",
    "six-group",
    "unicode.org",
    "cldr.unicode",
    "github.com",
    "http://",
    "https://",
)


def codes(body: dict[str, Any]) -> list[str]:
    return [
        item["alphabetic_code"]
        if "alphabetic_code" in item
        else item["currency"]["alphabetic_code"]
        for item in body["data"]
    ]


def test_01_incorporate_the_first_snapshot_and_report_it(stack: Stack) -> None:
    """CA-1 (a, mecanismo; la parte b, contenido real, está DIFERIDA), CA-2, CA-11 (D-8)."""
    document = build_snapshot(1)
    path = stack.write_snapshot("currency-snapshot-1.json", document)
    done = stack.currency("incorporate", str(path))
    assert done.returncode == 0, done.stderr
    assert "INCORPORADO snapshot_version=1" in done.stdout
    assert {c["status"] for c in document["currencies"]} == {"active"}
    assert not {"XTS", "XXX"} & {c["alphabetic_code"] for c in document["currencies"]}
    again = stack.currency("incorporate", str(path))
    assert again.returncode == 0 and "NO-OP snapshot_version=1" in again.stdout  # CA-11
    status, body = stack.get("/v1/currencies/version")
    assert (status, body["data"]) == (200, {"snapshot_version": 1})  # CA-14


def test_02_resolve_ars_usd_and_eur_by_code_and_by_id_with_names_in_en_and_es(stack: Stack) -> None:
    """CA-4, CA-16: resolver ARS, USD y EUR; nombre en/es."""
    expected = {
        "ARS": ("Argentine Peso", "peso argentino"),
        "USD": ("US Dollar", "dólar estadounidense"),
        "EUR": ("Euro", "euro"),
    }
    for code, (name_en, name_es) in expected.items():
        for spelling in (code, code.lower()):
            status, by_code = stack.get(f"/v1/currencies/by-code/{spelling}?locale_id={EN}")
            assert status == 200 and by_code["data"]["name"] == name_en
        status, by_id = stack.get(f"/v1/currencies/{currency_id(code)}?locale_id={ES}")
        assert status == 200 and by_id["data"]["name"] == name_es
        assert by_id["data"]["alphabetic_code"] == code and by_id["data"]["status"] == "active"
    assert stack.get("/v1/currencies/by-code/ARS")[1]["data"]["numeric_code"] == "032"
    status, body = stack.get("/v1/currencies/by-code/XAU")
    assert body["data"]["minor_units"] is None  # «no aplicable», distinto de 0


def test_03_current_currencies_of_a_country_and_countries_of_a_currency(stack: Stack) -> None:
    """CA-7, CA-17: monedas actuales de un Country y Country de una Currency."""
    status, body = stack.get(f"/v1/currencies/by-country/{country_id('AR')}?as_of=2026-11-01")
    assert status == 200 and codes(body) == ["ARS"]
    status, body = stack.get(f"/v1/currencies/{currency_id('EUR')}/countries?as_of=2026-11-01")
    assert status == 200
    assert [r["country_id"] for r in body["data"]] == sorted([country_id("DE"), country_id("FR")])
    status, body = stack.get(f"/v1/currencies/by-country/{country_id('AQ')}")
    assert (status, body["data"]) == (200, [])  # país sin moneda
    assert codes(stack.get(f"/v1/currencies/{currency_id('XDR')}/countries")[1]) == []  # sin países


def test_04_several_simultaneous_currencies_in_one_country(stack: Stack) -> None:
    """CA-17, CL-21: PA con PAB y USD a la vez; una moneda en varios países."""
    status, body = stack.get(f"/v1/currencies/by-country/{country_id('PA')}?as_of=2026-11-01")
    assert status == 200 and codes(body) == ["PAB", "USD"]
    status, body = stack.get(f"/v1/currencies/{currency_id('USD')}/countries?as_of=2026-11-01")
    assert {r["country_id"] for r in body["data"]} == {country_id("US"), country_id("PA")}


def test_05_the_croatia_transition_is_incorporated_and_the_history_is_resolved_by_date(
    stack: Stack,
) -> None:
    """CA-9, CA-18, CL-8, CL-20: HRK → EUR; 2022-12-31 devuelve HRK y 2023-01-01, EUR.

    Se incorpora como `snapshot_version` 5 (se admiten saltos): deja versiones 2 a 4 sin usar para
    poder probar después el rechazo por regresión."""
    path = stack.write_snapshot("currency-snapshot-5-transition.json", transition_snapshot(5))
    diff = stack.currency("diff", str(path))
    assert diff.returncode == 0 and "vigencia" in diff.stdout and "reemplazos" in diff.stdout
    status, body = stack.get("/v1/currencies/version")
    assert body["data"]["snapshot_version"] == 1  # el diff no escribe
    done = stack.currency("incorporate", str(path))
    assert done.returncode == 0 and "INCORPORADO snapshot_version=5" in done.stdout
    hr = country_id("HR")
    for day, expected in (
        ("1994-05-29", []),
        ("2022-12-31", ["HRK"]),
        ("2023-01-01", ["EUR"]),
        ("2026-11-01", ["EUR"]),
    ):
        status, body = stack.get(f"/v1/currencies/by-country/{hr}?as_of={day}")
        assert status == 200 and codes(body) == expected, day
    assert stack.get(f"/v1/currencies/by-country/{hr}?as_of=2023-02-30")[0] == 422


def test_06_a_retired_currency_keeps_resolving_and_validates_as_inactive(stack: Stack) -> None:
    """CA-6, CA-22: la moneda retirada sigue resoluble; su validación devuelve `inactive`."""
    status, body = stack.get(f"/v1/currencies/{currency_id('HRK')}?locale_id={ES}")
    data = body["data"]
    assert status == 200 and (data["status"], data["name"]) == ("inactive", "kuna croata")
    assert data["replacement_currency_ids"] == [currency_id("EUR")]
    assert stack.get(f"/v1/currencies/{currency_id('HRK')}/validation")[1]["data"] == {
        "result": "inactive"
    }
    assert stack.get(f"/v1/currencies/{currency_id('ARS')}/validation")[1]["data"] == {
        "result": "active"
    }
    ghost = stack.get("/v1/currencies/00000000-0000-4000-8000-000000000000/validation")
    assert ghost[1]["data"] == {"result": "not_found"}
    assert "HRK" not in codes(stack.get("/v1/currencies")[1])  # fuera del listado por defecto


def test_07_the_history_is_preserved_after_the_transition(stack: Stack) -> None:
    """CA-19, RF-49: la asociación HR–HRK sigue `active`, cerrada; nada desapareció."""
    status, body = stack.get(f"/v1/currencies/by-country/{country_id('HR')}/history")
    assert status == 200
    rows = [
        (r["currency"]["alphabetic_code"], r["status"], r["valid_from"], r["valid_to"])
        for r in body["data"]
    ]
    assert rows == [
        ("HRK", "active", "1994-05-30", "2023-01-01"),
        ("EUR", "active", "2023-01-01", None),
    ]
    with psycopg.connect(stack.admin_url) as conn:
        total = conn.execute("SELECT count(*) FROM reference.country_currency").fetchone()
        first = conn.execute(
            "SELECT first_snapshot_version FROM reference.currency WHERE alphabetic_code = 'HRK'"
        ).fetchone()
    assert total == (16,) and first == (
        1,
    )  # 15 del snapshot 1 + la nueva HR–EUR; HRK conserva su id


def test_08_rewriting_history_and_other_invalid_snapshots_are_rejected_with_the_database_unchanged(
    stack: Stack,
) -> None:
    """CA-10, CA-19, RF-39: mismo versión+otro digest, versión menor, digest alterado, país
    inexistente, nombre faltante, reescritura de un período cerrado. Cada rechazo sale con código 1
    y la base queda idéntica."""

    def dump() -> list[Any]:
        with psycopg.connect(stack.admin_url) as conn:
            return [
                conn.execute(f"SELECT * FROM reference.{t} ORDER BY 1, 2").fetchall()
                for t in ("currency_snapshot", "currency", "currency_locale", "country_currency")
            ]

    before = dump()
    rewritten = transition_snapshot(7)
    for item in rewritten["country_currencies"]:
        if item["currency_id"] == currency_id("HRK"):
            item["valid_to"] = "2023-06-01"
    tampered = transition_snapshot(7)
    tampered["currencies"][0]["minor_units"] = 9
    kept = [n for c in DEFAULT_CODES for n in names(c) if not (c == "ARS" and n["locale_id"] == EN)]
    cases = {
        "same-version-other-digest": build_snapshot(5, codes=("ARS",)),
        "lower-version": build_snapshot(3),
        "tampered-digest": tampered,
        "unknown-country": seal(
            {
                **transition_snapshot(7),
                "country_currencies": [
                    *transition_snapshot(7)["country_currencies"],
                    association(
                        "AR",
                        "USD",
                        date(2000, 1, 1),
                        country_id="00000000-0000-4000-8000-000000000009",
                    ),
                ],
            }
        ),
        "missing-required-name": transition_snapshot(7) | {"currency_names": kept},
        "rewritten-closed-period": seal(rewritten),
    }
    cases["missing-required-name"] = seal(cases["missing-required-name"])
    for label, document in cases.items():
        path = stack.write_snapshot(f"reject-{label}.json", document)
        result = stack.currency("incorporate", str(path))
        assert result.returncode == 1, (label, result.stdout, result.stderr)
        assert "RECHAZADO" in result.stderr, label
        assert dump() == before, label


def test_09_a_missing_currency_id_and_a_numeric_code_as_a_number_are_invalid_snapshots(
    stack: Stack,
) -> None:
    """CA-10 (RF-41): el schema y el dominio rechazan; la CLI sale con 1 sin tocar la base."""
    missing = transition_snapshot(7)
    del missing["currencies"][0]["currency_id"]
    numeric = transition_snapshot(7)
    numeric["currencies"][0]["numeric_code"] = 32
    for label, document in (
        ("no-currency-id", seal(missing)),
        ("numeric-as-number", seal(numeric)),
    ):
        path = stack.write_snapshot(f"invalid-{label}.json", document)
        result = stack.currency("incorporate", str(path))
        assert result.returncode == 1 and "snapshot inválido" in result.stderr, label


def test_10_a_later_list_three_currency_is_additive(stack: Stack) -> None:
    """CA-15, RF-43: se agrega YUM `inactive` con id nuevo sin alterar las existentes."""
    document = transition_snapshot(6)
    document["currencies"].append(currency("YUM", status="inactive"))
    document["currency_names"] += names("YUM")
    path = stack.write_snapshot("currency-snapshot-6-list-three.json", seal(document))
    with psycopg.connect(stack.admin_url) as conn:
        before = conn.execute("SELECT * FROM reference.currency ORDER BY currency_id").fetchall()
    done = stack.currency("incorporate", str(path))
    assert done.returncode == 0, done.stderr
    with psycopg.connect(stack.admin_url) as conn:
        after = conn.execute("SELECT * FROM reference.currency ORDER BY currency_id").fetchall()
    assert [r for r in after if r not in before][0][1] == "YUM"
    assert all(r in after for r in before)
    status, body = stack.get("/v1/currencies/by-code/YUM")
    assert status == 200 and body["data"]["status"] == "inactive"


def test_11_consumers_have_no_write_path(stack: Stack) -> None:
    """RF-34, CA-13: ni métodos de escritura en la API ni privilegios de escritura al lector."""
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert stack.send(method, "/v1/currencies") == 405
        assert stack.send(method, f"/v1/currencies/{currency_id('ARS')}") == 405
    with psycopg.connect(stack.reader_url, autocommit=True) as conn:
        for statement in (
            "UPDATE reference.currency SET status = 'inactive'",
            "DELETE FROM reference.country_currency",
            "INSERT INTO reference.currency_locale (currency_id, locale_id, name) "
            "VALUES (gen_random_uuid(), gen_random_uuid(), 'x')",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)
    document = stack.get("/v1/openapi/currencies.json")[1]
    assert all(set(operations) == {"get"} for operations in document["paths"].values())


def test_12_the_persistence_rejects_invalid_state_even_for_the_loader(stack: Stack) -> None:
    """CA-3, RNF-5: dos asociaciones activas del mismo par con períodos solapados, o un ciclo de
    reemplazos, fallan en la base aunque la aplicación no intervenga."""
    with psycopg.connect(stack.admin_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.ExclusionViolation):
            conn.execute(
                "INSERT INTO reference.country_currency (country_currency_id, country_id, "
                "currency_id, status, valid_from, first_snapshot_version, "
                "last_changed_snapshot_version) VALUES (gen_random_uuid(), %s, %s, 'active', "
                "'2024-01-01', 1, 1)",
                [country_id("HR"), currency_id("EUR")],
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE reference.currency SET replacement_currency_ids = %s "
                "WHERE currency_id = %s",
                [[currency_id("USD")], currency_id("ARS")],
            )  # un reemplazo en una moneda `active`


def test_13_no_runtime_dependency_on_iso_cldr_or_any_external_host(stack: Stack) -> None:
    """RF-42, CA-14: los subprocesos (CLI y API) corrieron con un guard de red; ninguno intentó
    salir de localhost. Además el código de Currency no importa clientes de red ni cita URLs
    externas."""
    stack.get("/v1/currencies")
    log = stack.net_log.read_text("utf-8") if stack.net_log.exists() else ""
    assert "BLOCKED" not in log, log
    # Canario: el mismo guard, en un proceso aparte, SÍ bloquea y registra un acceso externo. Sin
    # esto un log vacío podría significar un guard que nunca se cargó.
    canary_log = stack.work / "canary.log"
    canary = subprocess.run(
        [
            sys.executable,
            "-c",
            "import socket; socket.socket().connect(('192.0.2.1', 80))",
        ],
        env={**stack.env(), "ACCEPTANCE_NET_LOG": str(canary_log)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert canary.returncode != 0
    assert "BLOCKED connect 192.0.2.1" in canary_log.read_text("utf-8")
    stack.evidence.commands.append(
        {
            "command": "python -c <canario: connect a 192.0.2.1 con el guard de red>",
            "exit_code": canary.returncode,
            "stdout": canary_log.read_text("utf-8").strip(),
            "stderr": "",
        }
    )
    source = ROOT / "src" / "gi_common_reference" / "currencies"
    imported: set[str] = set()
    hints: list[str] = []
    for path in sorted(source.rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                hints += [
                    f"{path.name}: {hint}"
                    for hint in EXTERNAL_HINTS
                    if hint in node.value and not _is_doc(tree, node)
                ]
    assert not FORBIDDEN_IMPORTS & imported, FORBIDDEN_IMPORTS & imported
    assert hints == [], hints


def _is_doc(tree: ast.AST, constant: ast.Constant) -> bool:
    """Los docstrings pueden nombrar fuentes (ISO, CLDR) sin dependencia en runtime."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and body[0].value is constant:
                return True
    return False


def test_14_the_closed_dependencies_were_not_modified_by_004(stack: Stack) -> None:
    """CA-24: 001–003 intactas; ningún catálogo anterior importa Currency."""
    paths = [
        "src/gi_common_reference/locales",
        "src/gi_common_reference/regions",
        "src/gi_common_reference/countries",
        "migrations/versions/0001_locales.py",
        "migrations/versions/0002_regions.py",
        "migrations/versions/0003_countries.py",
        "contracts/locales-api.v1.openapi.json",
        "contracts/regions-api.v1.openapi.json",
        "contracts/countries-api.v1.openapi.json",
        "contracts/locale-snapshot.v1.schema.json",
        "contracts/region-snapshot.v1.schema.json",
        "contracts/country-snapshot.v1.schema.json",
        "specs/001-locales",
        "specs/002-regions-subregions",
        "specs/003-countries",
    ]
    diff = subprocess.run(
        ["git", "diff", "--stat", BASE_REF, "--", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert diff.returncode == 0, diff.stderr
    assert diff.stdout.strip() == "", diff.stdout
    stack.evidence.commands.append(
        {
            "command": f"git diff --stat {BASE_REF} -- <rutas de 001-003>",
            "exit_code": diff.returncode,
            "stdout": diff.stdout.strip(),
            "stderr": "",
        }
    )
    for catalog in ("locales", "regions", "countries"):
        for path in (ROOT / "src" / "gi_common_reference" / catalog).rglob("*.py"):
            assert "currencies" not in path.read_text("utf-8"), path
    # Ninguna prueba preexistente (001–003 incluidas) se modifica ni se borra: las únicas pruebas
    # que 004 toca son las fronteras de arquitectura compartidas, que solo se amplían.
    touched = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=MDR", BASE_REF, "--", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert touched.returncode == 0, touched.stderr
    shared_boundaries = {
        "tests/contract/test_architecture_contract.py",
        "tests/contract/test_composition_root.py",
        "tests/contract/test_layer_imports.py",
        "tests/contract/test_module_contract.py",
    }
    assert set(touched.stdout.split()) <= shared_boundaries, touched.stdout
    assert "tests/integration/test_migration_0003.py" not in touched.stdout


def test_15_country_has_no_currency_attribute_and_currency_has_no_country_attribute(
    stack: Stack,
) -> None:
    """CA-8, RF-20."""
    with psycopg.connect(stack.admin_url) as conn:
        country_columns = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'reference' AND table_name = 'country'"
            )
        }
        currency_columns = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'reference' AND table_name = 'currency'"
            )
        }
    assert not {c for c in country_columns if "currenc" in c}
    assert not {c for c in currency_columns if "countr" in c}
    assert not (country_columns | currency_columns) & {"tenant_id", "organization_id"}  # CA-2
