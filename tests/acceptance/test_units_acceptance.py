"""Aceptación de 005-units-of-measure (caja negra). Cada caso nombra los criterios de la spec.

El sistema real: base Postgres descartable, `alembic upgrade head`, Locale sintético y Units
incorporados con **sus CLI como subproceso**, y la **API real (uvicorn) por HTTP** con el rol
`reference_reader`. Ambos subprocesos corren con un guard de red. Los datos son el ejemplo sellado
`contracts/units-snapshot.v1.example.json` (no productivo, S-3) y dos variantes sintéticas: la v2
(alta de una unidad sin UCUM `sack` y retiro de `oz`) y la v3 (cambio del factor de `sack`).

Los esperados son cadenas literales de la spec y de este archivo (el oráculo): ninguno se calcula
con el código bajo prueba. La única excepción declarada es CA-8, donde la cota de la ida y vuelta
(CL-9) se recalcula aquí con `Fraction` a partir de los factores del ejemplo.

CA-18 tiene dos partes. (a) MECANISMO: el ejemplo sellado se incorpora y supera la verificación
UCUM; se ejecuta aquí. (b) CONTENIDO real de PREP: DIFERIDO; este módulo NO lo verifica ni lo
cuenta.
Ver `acceptance/units/README.md`.

El orden de los casos importa: comparten el sistema (módulo).
"""

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from fractions import Fraction
from typing import Any

import pytest

from tests.acceptance.conftest import ROOT
from tests.acceptance.units_support import UnitsStack
from tests.fixtures.regions import FR
from tests.fixtures.units import EN, ES, UCUM_SHA256, kind_id, seal, unit_id
from tests.fixtures.units_variants import SACK_ID, sack_snapshot
from tests.unit.units.helpers import association_row, edit, unit_row

pytest_plugins = ["tests.acceptance.units_support"]

BASE_REF = os.environ.get("ACCEPTANCE_BASE", "origin/develop")
EXAMPLE = ROOT / "contracts" / "units-snapshot.v1.example.json"
ADMISSIBLE = re.compile(r"-?(0|[1-9][0-9]{0,29})(\.[0-9]{1,30})?")
GHOST = "00000000-0000-4000-8000-000000000000"
V2 = sack_snapshot(2, factor="60", retired=("oz",))
V3 = sack_snapshot(3, factor="50", retired=("oz",))


def request(
    value: Any, source: str, target: str, kind: str | None = "mass", **extra: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "value": value,
        "from_unit_id": SACK_ID if source == "sack" else unit_id(source),
        "to_unit_id": SACK_ID if target == "sack" else unit_id(target),
    }
    if kind is not None:
        payload["quantity_kind_id"] = kind_id(kind)
    return {**payload, **extra}


def result_of(stack: UnitsStack, payload: dict[str, Any]) -> tuple[str, bool]:
    status, body = stack.convert(payload)
    assert status == 200, body
    return body["data"]["result"], body["data"]["exact"]


def rejection(stack: UnitsStack, payload: Any, *, raw: bytes | None = None) -> str:
    status, body = stack.post("/v1/conversions", payload, raw=raw)
    parsed = json.loads(body)
    assert status == 422, parsed
    assert set(parsed) == {"snapshot_version", "error"}
    return str(parsed["error"]["code"])


def test_01_incorporate_the_sealed_example_and_report_it(units_stack: UnitsStack) -> None:
    """CA-18 (a, mecanismo; la parte b, contenido real, está DIFERIDA), CA-14 (no-op), CA-10."""
    stack = units_stack
    example_bytes = EXAMPLE.read_bytes()
    stack.evidence.inputs["units-snapshot.v1.example.json"] = (
        "sha256:" + hashlib.sha256(example_bytes).hexdigest()
    )
    diff = stack.units("diff", str(EXAMPLE))
    assert diff.returncode == 0 and "DIFF snapshot_version=1" in diff.stdout
    assert stack.get("/v1/units/version")[1]["data"] == {
        "snapshot_version": None
    }  # diff no escribe
    done = stack.units("incorporate", str(EXAMPLE))
    assert done.returncode == 0, done.stderr
    assert (
        "INCORPORADO snapshot_version=1" in done.stdout and "ucum_table_version=2.2" in done.stdout
    )
    again = stack.units("incorporate", str(EXAMPLE))
    assert again.returncode == 0 and "NO-OP snapshot_version=1" in again.stdout
    status, body = stack.get("/v1/units/version")
    assert (status, body["data"]) == (200, {"snapshot_version": 1})
    status, kinds = stack.get("/v1/quantity-kinds")
    assert status == 200 and len(kinds["data"]) == 14
    status, units = stack.get("/v1/units")
    assert status == 200 and len(units["data"]) == 50


def test_02_basic_conversions_ca1_ca2_ca3(units_stack: UnitsStack) -> None:
    """CA-1, CA-2, CA-3: cadenas exactas de la spec."""
    stack = units_stack
    expected = [
        (request("1000", "g", "kg"), "1"),  # CA-1
        (request("1", "t", "kg"), "1000"),
        (request("1", "ha", "m2", "area"), "10000"),
        (request("1", "m3", "L", "volume"), "1000"),
        (request("1", "h", "min", "duration"), "60"),
        (request("0", "Cel", "K", "temperature"), "273.15"),  # CA-2
        (request("32", "degF", "Cel", "temperature"), "0"),
        (request("1", "Cel", "K", "temperature_difference"), "1"),
        (request("150", "kg/ha", "g/m2", "mass_per_area"), "15"),  # CA-3
    ]
    for payload, text in expected:
        status, body = stack.convert(payload)
        assert status == 200, body
        assert body["snapshot_version"] == 1
        assert body["data"] == {
            "result": text,
            "exact": True,
            "unit_id": payload["to_unit_id"],
            "quantity_kind_id": payload["quantity_kind_id"],
            "catalog_version": 1,
        }


def test_03_incompatible_and_insufficient_context_are_rejected_ca4(units_stack: UnitsStack) -> None:
    """CA-4: kg → L, unidades de magnitudes distintas, conversión sin magnitud."""
    stack = units_stack
    assert rejection(stack, request("1", "kg", "L", "mass")) == "incompatible_units"
    assert rejection(stack, request("1", "kg", "L", "volume")) == "incompatible_units"
    assert rejection(stack, request("1", "kg", "m", "length")) == "incompatible_units"
    assert rejection(stack, request("1", "kg", "g", None)) == "quantity_kind_required"
    assert rejection(stack, request("1", "kg", "L", None)) == "quantity_kind_required"


def test_04_value_forms_ca16(units_stack: UnitsStack) -> None:
    """CA-16 (CL-7): formas válidas e inválidas; CL-8: los límites aceptados (el rechazo fuera de
    rango no es alcanzable con el ejemplo: lo cubren las suites de dominio y de la API)."""
    stack = units_stack
    thirty = "9" * 30
    fractional = "0.123456789012345678901234567891"
    valid = [
        (request("-40", "Cel", "degF", "temperature"), "-40"),
        (request("0", "kg", "g"), "0"),
        (request("-0", "kg", "g"), "0"),
        (request(thirty, "kg", "kg"), thirty),
        (request(fractional, "kg", "kg"), fractional),
        (request("1.5", "kg", "g"), "1500"),
        (request("0." + "0" * 29 + "1", "cm2", "km2", "area"), "0." + "0" * 39 + "1"),
        (request(thirty, "km2", "cm2", "area"), thirty + "0" * 10),
    ]
    for payload, text in valid:
        assert result_of(stack, payload) == (text, True), payload
    for bad in ("1e3", "+1", "1,5", ".5", "5.", "007", " 1", "NaN", "Infinity", "", "1 ", "0x1"):
        assert rejection(stack, request(bad, "kg", "g")) == "invalid_value", bad
    assert rejection(stack, request("9" * 31, "kg", "g")) == "invalid_value"
    assert rejection(stack, request("0." + "1" * 31, "kg", "g")) == "invalid_value"
    template = (
        ('{"value": %s, "from_unit_id": "' + unit_id("kg") + '", "to_unit_id": "' + unit_id("g"))
        + '", "quantity_kind_id": "'
        + kind_id("mass")
        + '"}'
    )
    for literal in ("1000", "1e3", "1.5", "true", "null", "[1]"):
        code = rejection(stack, None, raw=(template % literal).encode("utf-8"))
        assert code == "invalid_value", literal


def test_05_localization_ca11(units_stack: UnitsStack) -> None:
    """CA-11: nombres en/es presentes; sin traducción `null` y sin fallback; locale inválido 422."""
    stack = units_stack
    expected = {EN: ("Mass", "kilogram", "kilograms"), ES: ("Masa", "kilogramo", "kilogramos")}
    for locale, (kind_name, unit_name, plural) in expected.items():
        status, kind = stack.get(f"/v1/quantity-kinds/{kind_id('mass')}?locale_id={locale}")
        assert status == 200 and kind["data"]["name"] == kind_name
        status, kilogram = stack.get(f"/v1/units/{unit_id('kg')}?locale_id={locale}")
        assert status == 200
        assert (kilogram["data"]["name"], kilogram["data"]["plural"]) == (unit_name, plural)
    status, french = stack.get(f"/v1/units/{unit_id('kg')}?locale_id={FR}")
    assert status == 200 and (french["data"]["name"], french["data"]["plural"]) == (None, None)
    status, plain = stack.get(f"/v1/units/{unit_id('kg')}")
    assert plain["data"]["name"] is None
    status, bad = stack.get("/v1/units?locale_id=nope")
    assert status == 422 and bad["error"]["code"] == "invalid_locale_id"
    status, unknown = stack.get(f"/v1/units?locale_id={GHOST}")
    assert status == 422 and unknown["error"]["code"] == "unknown_locale"


def test_06_celsius_is_one_identity_in_two_kinds_ca12(units_stack: UnitsStack) -> None:
    """CA-12: °C es una sola unidad asociada a dos magnitudes con transformaciones distintas."""
    stack = units_stack
    status, symbols = stack.get("/v1/units?include_inactive=true")
    assert status == 200
    ids = [u["unit_id"] for u in symbols["data"]]
    assert len(ids) == len(set(ids))  # ninguna unidad aparece dos veces
    assert [u["symbol"] for u in symbols["data"]].count("°C") == 1
    status, celsius = stack.get(f"/v1/units/{unit_id('Cel')}")
    kinds = {k["quantity_kind_id"] for k in celsius["data"]["quantity_kinds"]}
    assert kinds == {kind_id("temperature"), kind_id("temperature_difference")}
    # transformaciones distintas: 0 °C → K es 273.15 como temperatura y 0 como diferencia
    assert result_of(stack, request("0", "Cel", "K", "temperature"))[0] == "273.15"
    assert result_of(stack, request("0", "Cel", "K", "temperature_difference"))[0] == "0"


def test_07_round_trips_over_every_pair_ca8(units_stack: UnitsStack) -> None:
    """CA-8 (CL-9): ida y vuelta por HTTP sobre todos los pares ordenados de cada magnitud."""
    stack = units_stack
    document = json.loads(EXAMPLE.read_text("utf-8"))
    kinds = {k["quantity_kind_id"]: k["code"] for k in document["quantity_kinds"]}
    members: dict[str, list[dict[str, str]]] = {}
    for row in document["quantity_kind_units"]:
        members.setdefault(row["quantity_kind_id"], []).append(row)

    def half_ulp(value: Fraction) -> Fraction:
        magnitude = abs(value)
        if magnitude == 0:
            return Fraction(0)
        exponent = len(str(magnitude.numerator)) - len(str(magnitude.denominator))
        while Fraction(10) ** exponent > magnitude:
            exponent -= 1
        while Fraction(10) ** (exponent + 1) <= magnitude:
            exponent += 1
        return Fraction(10) ** (exponent - 33) / 2

    requests = pairs = skipped = 0
    for kind, rows in members.items():
        for source in rows:
            for target in rows:
                pairs += 1
                for value in ("1", "2.5", "-273.15", "0.000123"):
                    x0 = Fraction(value)
                    base = {"quantity_kind_id": kind, "from_unit_id": source["unit_id"]}
                    status, forward = stack.convert(
                        {**base, "value": value, "to_unit_id": target["unit_id"]}, record=False
                    )
                    assert status == 200, (kinds[kind], forward)
                    if not ADMISSIBLE.fullmatch(forward["data"]["result"]):
                        skipped += 1  # el resultado no es un valor de entrada admisible (RF-26)
                        continue
                    back_status, back = stack.convert(
                        {
                            "quantity_kind_id": kind,
                            "value": forward["data"]["result"],
                            "from_unit_id": target["unit_id"],
                            "to_unit_id": source["unit_id"],
                        },
                        record=False,
                    )
                    assert back_status == 200, back
                    requests += 2
                    y1, final = (
                        Fraction(forward["data"]["result"]),
                        Fraction(back["data"]["result"]),
                    )
                    if forward["data"]["exact"] and back["data"]["exact"]:
                        assert final == x0, (kinds[kind], value, source, target)
                        continue
                    f_s, f_t = Fraction(source["factor"]), Fraction(target["factor"])
                    err1 = Fraction(0) if forward["data"]["exact"] else half_ulp(y1)
                    bound = err1 * f_t / f_s + (
                        Fraction(0) if back["data"]["exact"] else half_ulp(final)
                    )
                    assert abs(final - x0) <= bound, (kinds[kind], value, source, target)
    assert pairs >= 150
    stack.evidence.commands.append(
        {
            "command": f"CA-8: ida y vuelta HTTP sobre {pairs} pares ordenados × 4 valores",
            "exit_code": 0,
            "stdout": (
                f"{requests} solicitudes POST /v1/conversions; todas dentro de la cota CL-9; "
                f"{skipped} vueltas omitidas porque el resultado de ida no es un valor de "
                "entrada admisible (más de 30 dígitos enteros o fraccionarios)"
            ),
            "stderr": "",
        }
    )


def test_08_the_new_version_retires_a_unit_and_history_is_reproducible_ca5_ca7(
    units_stack: UnitsStack,
) -> None:
    """CA-5, CA-7, CA-14 (versión posterior con alta y retiro, diff que lo muestra)."""
    stack = units_stack
    oz = request("1", "oz", "kg", catalog_version=1)
    before_status, before = stack.post("/v1/conversions", oz)
    assert before_status == 200
    assert json.loads(before)["data"]["result"] == "0.028349523125"
    path = stack.write_snapshot("units-snapshot-2.json", V2)
    diff = stack.units("diff", str(path))
    assert diff.returncode == 0 and "sack" in diff.stdout and "oz" in diff.stdout
    assert stack.get("/v1/units/version")[1]["data"] == {
        "snapshot_version": 1
    }  # el diff no escribe
    done = stack.units("incorporate", str(path))
    assert done.returncode == 0 and "INCORPORADO snapshot_version=2" in done.stdout
    # la unidad retirada rechaza la conversión nueva...
    assert rejection(stack, request("1", "oz", "kg")) == "inactive_unit"
    status, retired = stack.get(f"/v1/units/{unit_id('oz')}")
    assert status == 200 and retired["data"]["status"] == "inactive"
    # ...y la misma conversión con la versión anterior da el resultado de entonces, byte a byte
    after_status, after = stack.post("/v1/conversions", oz)
    assert after_status == 200
    assert json.loads(after)["snapshot_version"] == 2
    assert json.loads(after)["data"] == json.loads(before)["data"]
    assert (
        json.dumps(json.loads(after)["data"], sort_keys=True).encode()
        == json.dumps(json.loads(before)["data"], sort_keys=True).encode()
    )
    assert json.loads(after)["data"]["catalog_version"] == 1
    # la unidad nueva y su identidad estable
    assert result_of(stack, request("2", "sack", "kg")) == ("120", True)
    assert stack.get(f"/v1/units/{unit_id('kg')}")[1]["data"]["unit_id"] == unit_id("kg")


def test_09_a_factor_change_does_not_alter_the_historical_result_ca7(
    units_stack: UnitsStack,
) -> None:
    """CA-7: el mismo resultado byte a byte antes y después de una versión que cambia el factor."""
    stack = units_stack
    sack_v2 = request("2", "sack", "kg", catalog_version=2)
    first_status, first = stack.post("/v1/conversions", sack_v2)
    assert first_status == 200 and json.loads(first)["data"]["result"] == "120"
    path = stack.write_snapshot("units-snapshot-3.json", V3)
    diff = stack.units("diff", str(path))
    assert diff.returncode == 0 and "60" in diff.stdout and "50" in diff.stdout  # antes → después
    done = stack.units("incorporate", str(path))
    assert done.returncode == 0 and "INCORPORADO snapshot_version=3" in done.stdout
    assert result_of(stack, request("2", "sack", "kg")) == ("100", True)  # la vigente
    second_status, second = stack.post("/v1/conversions", sack_v2)
    assert second_status == 200
    assert json.loads(second)["data"] == json.loads(first)["data"]
    assert json.loads(second)["snapshot_version"] == 3
    assert result_of(stack, request("2", "sack", "kg", catalog_version=2)) == ("120", True)
    assert rejection(stack, request("2", "sack", "kg", catalog_version=1)) == "unit_not_found"
    assert rejection(stack, request("2", "sack", "kg", catalog_version=99)) == (
        "catalog_version_not_available"
    )
    assert rejection(stack, request("2", "sack", "kg", catalog_version=0)) == (
        "invalid_catalog_version"
    )
    # CA-10: avanzar de versión conserva todas las identidades del catálogo inicial
    document = json.loads(EXAMPLE.read_text("utf-8"))
    status, current = stack.get("/v1/units?include_inactive=true")
    published = {u["unit_id"]: u["symbol"] for u in current["data"]}
    assert {u["unit_id"]: u["symbol"] for u in document["units"]} | {SACK_ID: "sack"} == published
    status, kinds = stack.get("/v1/quantity-kinds?include_inactive=true")
    assert {k["quantity_kind_id"] for k in kinds["data"]} == {
        k["quantity_kind_id"] for k in document["quantity_kinds"]
    }


def test_10_invalid_snapshots_are_rejected_without_partial_changes_ca6_ca14(
    units_stack: UnitsStack,
) -> None:
    """CA-6 (UCUM incorrecto, factor distinto del normativo), CA-14 (digest, versión, omisión)."""
    stack = units_stack
    before = stack.state()

    def v4(change: Any) -> dict[str, Any]:
        def apply(document: dict[str, Any]) -> None:
            document["snapshot_version"] = 4
            change(document)

        return seal(edit(V3, apply))

    def add_unit(document: dict[str, Any], ucum: str, factor: str = "1") -> None:
        """Una unidad nueva de masa con ese código UCUM y ese factor declarado (respecto de kg)."""
        new = "6f0e0000-0000-4000-8000-0000000000aa"
        document["units"].append(
            {
                "unit_id": new,
                "ucum_code": ucum,
                "unece_code": None,
                "symbol": "bad",
                "status": "active",
            }
        )
        document["quantity_kind_units"].append(
            {
                "quantity_kind_id": kind_id("mass"),
                "unit_id": new,
                "factor": factor,
                "offset": "0",
                "status": "active",
            }
        )
        document["unit_names"] += [
            {"unit_id": new, "locale_id": EN, "name": "bad", "plural": None},
            {"unit_id": new, "locale_id": ES, "name": "mala", "plural": None},
        ]

    def drop_wk(document: dict[str, Any]) -> None:
        wk = unit_id("wk")
        document["units"] = [u for u in document["units"] if u["unit_id"] != wk]
        document["quantity_kind_units"] = [
            a for a in document["quantity_kind_units"] if a["unit_id"] != wk
        ]
        document["unit_names"] = [n for n in document["unit_names"] if n["unit_id"] != wk]

    tampered = v4(lambda d: None)
    tampered["units"][0]["symbol"] = tampered["units"][0]["symbol"] + "x"  # sin volver a sellar
    cases: dict[str, tuple[dict[str, Any], str]] = {
        "ucum-sintaxis": (v4(lambda d: add_unit(d, "kg/")), "RF-15"),
        "ucum-atomo-desconocido": (v4(lambda d: add_unit(d, "xyzzy")), "RF-15"),
        "ucum-prefijo-sobre-no-metrico": (v4(lambda d: add_unit(d, "k[in_i]")), "RF-15"),
        "ucum-factor-declarado-distinto": (v4(lambda d: add_unit(d, "hg", "1")), "RF-16"),
        "ucum-publicado-cambiado": (
            v4(lambda d: unit_row(d, "kg").update(ucum_code="kg/")),
            "RF-5",
        ),
        "factor-distinto-del-normativo": (
            v4(lambda d: association_row(d, "mass", "g").update(factor="0.01")),
            "RF-16",
        ),
        "omision-de-una-unidad-publicada": (v4(drop_wk), "RF-43"),
        "digest-adulterado": (tampered, ""),
        "misma-version-otro-digest": (
            seal(edit(V3, lambda d: unit_row(d, "kg").update(symbol="KG"))),
            "",
        ),
        "version-anterior": (seal(edit(V2, lambda d: unit_row(d, "kg").update(symbol="KG"))), ""),
    }
    for name, (document, rule) in cases.items():
        path = stack.write_snapshot(f"rejected-{name}.json", document)
        done = stack.units("incorporate", str(path))
        assert done.returncode == 1, (name, done.stdout, done.stderr)
        assert "RECHAZADO" in done.stderr and rule in done.stderr, (name, done.stderr)
        assert stack.state() == before, name  # dump idéntico: sin cambios parciales
        shown = stack.units("diff", str(path))
        assert shown.returncode == 1 and stack.state() == before, name
    assert stack.get("/v1/units/version")[1]["data"] == {"snapshot_version": 3}
    # un archivo ilegible es un error operativo (2), no un rechazo
    assert stack.units("incorporate", str(stack.work / "no-existe.json")).returncode == 2


def test_11_the_published_contract_and_error_shapes_ca15(units_stack: UnitsStack) -> None:
    """CA-15 (muestra): OpenAPI publicado = servido; 404 vs 422; 405; sin `tenant_id`."""
    stack = units_stack
    status, served = stack.get("/v1/openapi/units.json")
    assert status == 200
    assert served == json.loads(
        (ROOT / "contracts" / "units-api.v1.openapi.json").read_text("utf-8")
    )
    assert set(served["paths"]) == {
        "/v1/quantity-kinds",
        "/v1/quantity-kinds/{quantity_kind_id}",
        "/v1/units",
        "/v1/units/version",
        "/v1/units/{unit_id}",
        "/v1/conversions",
    }
    assert stack.get(f"/v1/units/{GHOST}")[0] == 404
    status, malformed = stack.get("/v1/units/nope")
    assert status == 422 and malformed["error"]["code"] == "invalid_unit_id"
    assert stack.get(f"/v1/quantity-kinds/{GHOST}")[0] == 404
    assert stack.get(f"/v1/units?quantity_kind_id={GHOST}")[0] == 404
    assert stack.get("/v1/units?include_inactive=maybe")[1]["error"]["code"] == "invalid_parameter"
    assert stack.get("/v1/units/version")[0] == 200  # la ruta fija gana a {unit_id}
    for method in ("PUT", "PATCH", "DELETE"):
        for path in (
            "/v1/units",
            f"/v1/units/{unit_id('kg')}",
            "/v1/quantity-kinds",
            "/v1/conversions",
        ):
            assert stack.send(method, path) == 405, (method, path)
    assert stack.get("/v1/conversions")[0] == 405
    assert stack.send("POST", "/v1/units") == 405
    assert rejection(stack, {"value": "1"}) == "invalid_request"
    assert rejection(stack, {**request("1", "kg", "g"), "tenant_id": GHOST}) == "invalid_request"
    for path in ("/v1/units", "/v1/quantity-kinds", f"/v1/units/{unit_id('Cel')}"):
        assert "tenant_id" not in json.dumps(stack.get(path)[1])


def test_12_the_privileged_role_boundaries_hold_for_the_reader(units_stack: UnitsStack) -> None:
    """CA-9 (parte observable): el rol lector de la API no puede escribir; la base lo rechaza."""
    import psycopg

    stack = units_stack
    with psycopg.connect(stack.reader_url, autocommit=True) as conn:
        for statement in (
            "UPDATE reference.unit SET symbol = 'x'",
            "DELETE FROM reference.unit",
            "TRUNCATE reference.unit",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)


FORBIDDEN_IMPORTS = {"httpx", "requests", "urllib", "http", "socket", "aiohttp", "ftplib"}


def test_13_units_depends_on_no_other_catalog_and_uses_no_network_client(
    units_stack: UnitsStack,
) -> None:
    """CA-17 (dependencias de código): Units no importa Regions, Countries ni Currency (ni
    Locale), ninguno de ellos lo importa y no hay clientes de red."""
    package = ROOT / "src" / "gi_common_reference"
    others = ("locales", "regions", "countries", "currencies")
    imported: set[str] = set()
    for path in sorted((package / "units").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert not [m for m in imported if any(f"gi_common_reference.{o}" in m for o in others)]
    assert not {m.split(".")[0] for m in imported} & FORBIDDEN_IMPORTS
    for catalog in others:
        for path in (package / catalog).rglob("*.py"):
            assert "units" not in {
                part
                for node in ast.walk(ast.parse(path.read_text("utf-8")))
                if isinstance(node, ast.ImportFrom) and node.module
                for part in node.module.split(".")
            }, path


def test_14_the_closed_modules_were_not_modified_by_005_ca17(units_stack: UnitsStack) -> None:
    """CA-17: el diff de las rutas de 001–004 respecto de la base es vacío."""
    stack = units_stack
    paths = [
        *(
            f"src/gi_common_reference/{c}"
            for c in ("locales", "regions", "countries", "currencies")
        ),
        *(
            f"migrations/versions/{n}"
            for n in (
                "0001_locales.py",
                "0002_regions.py",
                "0003_countries.py",
                "0004_currencies.py",
            )
        ),
        *(
            f"contracts/{n}"
            for n in (
                "locales-api.v1.openapi.json",
                "regions-api.v1.openapi.json",
                "countries-api.v1.openapi.json",
                "currencies-api.v1.openapi.json",
                "locale-snapshot.v1.schema.json",
                "region-snapshot.v1.schema.json",
                "country-snapshot.v1.schema.json",
                "currency-snapshot.v1.schema.json",
                "locale-snapshot.v1.example.json",
                "region-snapshot.v1.example.json",
                "country-snapshot.v1.example.json",
                "currency-snapshot.v1.example.json",
                "locale-snapshot.v1.vectors.json",
            )
        ),
        "specs/001-locales",
        "specs/002-regions-subregions",
        "specs/003-countries",
        "specs/004-currency",
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
            "command": f"git diff --stat {BASE_REF} -- <rutas de 001-004>",
            "exit_code": diff.returncode,
            "stdout": diff.stdout.strip(),
            "stderr": "",
        }
    )
    # Las pruebas preexistentes solo se amplían donde enumeran catálogos (fronteras compartidas).
    touched = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=MDR", BASE_REF, "--", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert touched.returncode == 0, touched.stderr
    shared = {
        "tests/contract/test_architecture_contract.py",
        "tests/contract/test_composition_root.py",
        "tests/contract/test_layer_imports.py",
        "tests/contract/test_module_contract.py",
        "tests/integration/currencies/test_dependency_direction.py",
    }
    assert set(touched.stdout.split()) <= shared, touched.stdout
    stack.evidence.commands.append(
        {
            "command": f"git diff --name-only --diff-filter=MDR {BASE_REF} -- tests",
            "exit_code": touched.returncode,
            "stdout": touched.stdout.strip(),
            "stderr": "",
        }
    )


def test_15_no_process_reached_outside_localhost(units_stack: UnitsStack) -> None:
    """RNF-1, CA-17: la CLI y la API corrieron con un guard de red; ninguna salió de localhost."""
    stack = units_stack
    stack.get("/v1/units")
    log = stack.net_log.read_text("utf-8") if stack.net_log.exists() else ""
    assert "BLOCKED" not in log, log
    # Canario: el mismo guard, en un proceso aparte, SÍ bloquea y registra un acceso externo.
    canary_log = stack.work / "canary.log"
    canary = subprocess.run(
        [sys.executable, "-c", "import socket; socket.socket().connect(('192.0.2.1', 80))"],
        env={**stack.env(), "ACCEPTANCE_NET_LOG": str(canary_log)},
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=60,
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


def test_16_the_packaged_ucum_table_is_the_official_one(units_stack: UnitsStack) -> None:
    """RNF-7: la tabla UCUM empaquetada coincide con la oficial fijada (sha256)."""
    path = ROOT / "src/gi_common_reference/units/infrastructure/ucum/ucum-essence.xml"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    units_stack.evidence.inputs["ucum-essence.xml"] = "sha256:" + digest
    assert digest == UCUM_SHA256
    assert (path.parent / "NOTICE.md").exists()
