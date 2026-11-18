"""Aceptación transversal 006: los cinco catálogos (001–005) juntos, caja negra.

Sistema real: Postgres 16 descartable (testcontainers), migraciones con `alembic` como subproceso,
cada catálogo incorporado con SU CLI (subproceso) en el orden del grafo de dependencias, y la API
real (uvicorn, rol `reference_reader`) consultada por HTTP. Todos los procesos corren con el guard
de red de 004. Ningún caso usa mocks ni repositorios en memoria. Los ids/criterios (`CA-n`) son los
de `specs/006-cross-module-acceptance/spec.md`.
"""

import json
import os
import re
import subprocess
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg import errors

from tests.acceptance.conftest import ROOT
from tests.acceptance.cross_module_support import (
    CLI,
    GRAPH,
    ORDER,
    ReferenceStack,
    countries_retiring_pr,
    countries_snapshot,
    countries_with_ghost_region,
    currencies_closing_pr,
    currency_association,
    currency_snapshot,
    snapshots,
)
from tests.fixtures import countries as countries_fx
from tests.fixtures import currencies as currencies_fx
from tests.fixtures import regions as regions_fx
from tests.fixtures import units as units_fx

pytest_plugins = ["tests.acceptance.cross_module_support"]

EN, ES, FR = regions_fx.EN, regions_fx.ES, regions_fx.FR
GHOST = "00000000-0000-4000-8000-000000000000"
GRAPH_DATA: dict[str, Any] = json.loads(GRAPH.read_text("utf-8"))
MODULES: dict[str, Any] = GRAPH_DATA["modules"]
OPENAPI = {
    "locales": ("/v1/openapi.json", "locales-api.v1.openapi.json"),
    "regions": ("/v1/openapi/regions.json", "regions-api.v1.openapi.json"),
    "countries": ("/v1/openapi/countries.json", "countries-api.v1.openapi.json"),
    "currencies": ("/v1/openapi/currencies.json", "currencies-api.v1.openapi.json"),
    "units": ("/v1/openapi/units.json", "units-api.v1.openapi.json"),
}


def base_ref() -> str:
    """Base contra la que 006 no debe tocar código: la punta de 005 mientras no esté en develop."""
    configured = os.environ.get("CROSS_ACCEPTANCE_BASE")
    if configured:
        return configured
    for candidate in ("origin/feature/005-units-of-measure", "origin/develop", "develop"):
        found = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", candidate],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if found.returncode == 0:
            return candidate
    raise RuntimeError("sin revisión base")


def data(body: dict[str, Any]) -> Any:
    return body.get("data", body)


def items(body: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data(body)
    return payload if isinstance(payload, list) else payload.get("items", [])


def owner_of(table: str) -> str:
    owners = [name for name, module in MODULES.items() if table in module["tables"]]
    assert len(owners) == 1, (table, owners)
    return owners[0]


def enable_logins(stack: ReferenceStack) -> None:
    with psycopg.connect(stack.admin_url, autocommit=True) as conn:
        conn.execute("ALTER ROLE reference_loader LOGIN PASSWORD 'loader-pw'")
        conn.execute("ALTER ROLE reference_reader LOGIN PASSWORD 'reader-pw'")


def test_01_migrations_reach_head_and_every_reference_is_global(
    reference_stack: ReferenceStack,
) -> None:
    """CA-1: head = 0005; cada tabla tiene un único módulo dueño; ninguna lleva `tenant_id`;
    `anon`/`authenticated`/`PUBLIC` no tienen privilegios; `reference_reader` solo lee."""
    stack = reference_stack
    current = stack.alembic("current")
    assert current.returncode == 0, current.stderr
    assert "0005 (head)" in current.stdout + current.stderr

    with psycopg.connect(stack.admin_url) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'reference' AND table_type = 'BASE TABLE' "
                "AND table_name <> 'alembic_version'"
            )
        }
        declared = {t for module in MODULES.values() for t in module["tables"]}
        assert tables == declared
        for table in tables:
            owner_of(table)
        tenant = conn.execute(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'reference' AND column_name ILIKE '%tenant%'"
        ).fetchall()
        assert tenant == []
        grants = conn.execute(
            "SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants "
            "WHERE table_schema = 'reference' AND grantee IN "
            "('anon', 'authenticated', 'PUBLIC', 'reference_reader')"
        ).fetchall()
    public = [g for g in grants if g[0] != "reference_reader"]
    assert public == []
    reader = {g[2] for g in grants if g[0] == "reference_reader"}
    assert reader == {"SELECT"}


def test_02_dependency_graph_matches_the_real_system(reference_stack: ReferenceStack) -> None:
    """CA-2: el grafo declarado = FKs reales entre módulos = specs = cadena de migraciones;
    acíclico; el orden de incorporación es topológico; ningún módulo importa a otro."""
    stack = reference_stack
    with psycopg.connect(stack.admin_url) as conn:
        fks = conn.execute(
            "SELECT src.relname, dst.relname FROM pg_constraint c "
            "JOIN pg_class src ON src.oid = c.conrelid "
            "JOIN pg_class dst ON dst.oid = c.confrelid "
            "JOIN pg_namespace n ON n.oid = src.relnamespace "
            "WHERE c.contype = 'f' AND n.nspname = 'reference'"
        ).fetchall()
    real = {(owner_of(a), owner_of(b)) for a, b in fks if owner_of(a) != owner_of(b)}
    declared = {(m, d) for m, module in MODULES.items() for d in module["dependsOn"]}
    assert real == declared, {"solo en la base": real - declared, "solo declarado": declared - real}

    order = GRAPH_DATA["incorporationOrder"]
    assert tuple(order) == ORDER and set(order) == set(MODULES)
    for module, dependency in declared:
        assert order.index(dependency) < order.index(module)
        assert MODULES[dependency]["migration"] < MODULES[module]["migration"]

    chain: dict[str, str | None] = {}
    for path in (ROOT / "migrations" / "versions").glob("*.py"):
        text = path.read_text("utf-8")
        revision = re.search(r'^revision = "(\w+)"', text, re.M)
        down = re.search(r"^down_revision = (None|\"(\w+)\")", text, re.M)
        assert revision and down
        chain[revision.group(1)] = down.group(2)
    assert chain == {"0001": None, "0002": "0001", "0003": "0002", "0004": "0003", "0005": "0004"}

    architecture = json.loads((ROOT / "architecture.json").read_text("utf-8"))
    assert set(architecture["modules"]) == set(MODULES)

    for module, info in MODULES.items():
        spec = (ROOT / "specs" / info["spec"] / "spec.md").read_text("utf-8")
        line = next(x for x in spec.splitlines() if x.startswith("- **Depende de:**"))
        named = {m for m, other in MODULES.items() if f"`{other['spec']}`" in line}
        assert named == set(info["dependsOn"]), (module, line)
        assert CLI[module] == info["cli"]

    package = ROOT / "src" / "gi_common_reference"
    for module in MODULES:
        for path in (package / module).rglob("*.py"):
            text = path.read_text("utf-8")
            for other in set(MODULES) - {module}:
                assert f"gi_common_reference.{other}" not in text, (path, other)
    stack.evidence.commands.append(
        {
            "command": "verificación del grafo (FKs, specs, migraciones, imports)",
            "exit_code": 0,
            "stdout": json.dumps(sorted(real)),
            "stderr": "",
        }
    )


def test_03_all_five_catalogs_incorporated_in_order_and_diff_does_not_write(
    reference_stack: ReferenceStack,
) -> None:
    """CA-3: las cinco CLIs incorporaron v1 (exit 0) en orden; `diff` de cada v1 no escribe."""
    stack = reference_stack
    incorporations = [c for c in stack.evidence.commands if " incorporate " in c["command"]][:5]
    assert [c["command"].split()[2] for c in incorporations] == [CLI[m] for m in ORDER]
    assert all(c["exit_code"] == 0 for c in incorporations)

    before = stack.fingerprint()
    for module, document in snapshots().items():
        if module in ("locales", "regions"):  # 001 y 002 solo exponen `incorporate`
            continue
        shown = stack.catalog(
            module, "diff", str(stack.write_snapshot(f"{module}-v1.json", document))
        )
        assert shown.returncode == 0, (module, shown.stdout, shown.stderr)
    assert stack.fingerprint() == before
    counts = {table: int(value.split(":")[0]) for table, value in before.items()}
    for module in ORDER:
        snapshot_table = {
            "locales": "locale_snapshot",
            "regions": "region_snapshot",
            "countries": "country_snapshot",
            "currencies": "currency_snapshot",
            "units": "unit_snapshot",
        }[module]
        assert counts[snapshot_table] == 1, (module, counts)


def test_04_reincorporating_every_catalog_is_idempotent(reference_stack: ReferenceStack) -> None:
    """CA-4: reenviar los cinco snapshots idénticos es un no-op (exit 0, dump idéntico)."""
    stack = reference_stack
    before = stack.fingerprint()
    for module, document in snapshots().items():
        again = stack.incorporate(module, document, f"{module}-v1-again.json")
        assert again.returncode == 0, (module, again.stdout, again.stderr)
    assert stack.fingerprint() == before


def test_05_consumers_navigate_across_catalogs_through_the_public_api(
    reference_stack: ReferenceStack,
) -> None:
    """CA-5: Locale → Region/Subregion → Country → Currency → Units por identidades estables."""
    stack = reference_stack
    status, body = stack.get("/v1/locales/by-code/es")
    assert status == 200, body
    assert data(body)["locale_id"] == ES

    status, body = stack.get(f"/v1/countries/by-alpha2/AR?locale_id={ES}")
    assert status == 200, body
    argentina = data(body)
    assert argentina["country_id"] == countries_fx.country_id("AR")
    assert argentina["region_id"] == regions_fx.region_id("019")
    assert argentina["subregion_id"] == regions_fx.subregion_id("419")

    status, body = stack.get(f"/v1/regions/{argentina['region_id']}")
    assert status == 200, body
    assert data(body)["code"] == "019"
    status, body = stack.get(f"/v1/subregions/{argentina['subregion_id']}")
    assert status == 200, body
    assert data(body)["code"] == "419"
    assert data(body)["region_id"] == argentina["region_id"]

    status, body = stack.get(f"/v1/currencies/by-country/{argentina['country_id']}")
    assert status == 200, body
    assert [c["currency"]["alphabetic_code"] for c in items(body)] == ["ARS"]

    status, body = stack.get("/v1/currencies/by-code/USD")
    assert status == 200, body
    usd = data(body)["currency_id"]
    status, body = stack.get(f"/v1/currencies/{usd}/countries")
    assert status == 200, body
    linked = {row["country_id"] for row in items(body)}
    assert linked == {countries_fx.country_id("US"), countries_fx.country_id("PR")}
    for country_id in linked:
        status, body = stack.get(f"/v1/countries/{country_id}")
        assert status == 200, body

    status, body = stack.get(f"/v1/units?quantity_kind_id={units_fx.kind_id('mass')}")
    assert status == 200, body
    assert {units_fx.unit_id("kg"), units_fx.unit_id("lb")} <= {u["unit_id"] for u in items(body)}
    status, body = stack.post(
        "/v1/conversions",
        {
            "value": "1",
            "from_unit_id": units_fx.unit_id("lb"),
            "to_unit_id": units_fx.unit_id("kg"),
            "quantity_kind_id": units_fx.kind_id("mass"),
        },
    )
    assert status == 200, body
    assert data(body)["result"] == "0.45359237"
    assert data(body)["exact"] is True


LOCALIZED = (
    ("regions", lambda: f"/v1/regions/{regions_fx.region_id('019')}", ("Americas", "Américas")),
    ("subregions", lambda: f"/v1/subregions/{regions_fx.subregion_id('419')}", None),
    (
        "countries",
        lambda: f"/v1/countries/{countries_fx.country_id('US')}",
        ("United States", "Estados Unidos"),
    ),
    (
        "currencies",
        lambda: f"/v1/currencies/{currencies_fx.currency_id('USD')}",
        ("US Dollar", "dólar estadounidense"),
    ),
    ("units", lambda: f"/v1/units/{units_fx.unit_id('kg')}", ("kilogram", "kilogramo")),
    ("quantity-kinds", lambda: f"/v1/quantity-kinds/{units_fx.kind_id('mass')}", None),
)


def localized_name(payload: dict[str, Any]) -> Any:
    return payload.get("name")


@pytest.mark.parametrize(("label", "path", "expected"), LOCALIZED, ids=[x[0] for x in LOCALIZED])
def test_06_localization_is_uniform_across_catalogs(
    reference_stack: ReferenceStack, label: str, path: Any, expected: tuple[str, str] | None
) -> None:
    """CA-6: el mismo `locale_id` de Locale localiza todos los catálogos; `en`/`es` dan sus
    nombres, `fr` (activo, sin traducciones) no cae a otro idioma, un id mal formado o
    inexistente se rechaza con 4xx en todos."""
    stack = reference_stack
    names = {}
    for locale in (EN, ES, FR):
        status, body = stack.get(f"{path()}?locale_id={locale}")
        assert status == 200, (label, locale, body)
        names[locale] = localized_name(data(body))
    if expected is not None:
        assert (names[EN], names[ES]) == expected
    else:
        assert names[EN] and names[ES], (label, names)
    assert names[FR] in (None, ""), (label, names[FR])
    for bad in ("not-a-uuid", GHOST):
        status, body = stack.get(f"{path()}?locale_id={bad}")
        assert 400 <= status < 500, (label, bad, status, body)


def test_07_cross_module_references_are_validated_on_incorporation(
    reference_stack: ReferenceStack,
) -> None:
    """CA-7: cada CLI rechaza (exit ≠ 0, sin escribir nada) un snapshot que referencia una
    identidad inexistente de otro módulo o una versión no incorporada de su dependencia."""
    stack = reference_stack
    before = stack.fingerprint()
    ghost_region = countries_with_ghost_region()
    v1_associations = [
        currency_association("AR", "ARS"),
        currency_association("US", "USD"),
        currency_association("PR", "USD", date(1899, 1, 1)),
    ]
    ghost_country = currency_snapshot(
        2,
        country_currencies=[
            *v1_associations,
            currencies_fx.association("TW", "USD", n=9, country_id=GHOST),
        ],
    )
    future_countries = currency_snapshot(2, country_snapshot_version=2)
    future_regions = countries_snapshot(2, region_snapshot_version=2)
    unit_rows = [
        row
        for key in units_fx.unit_keys(units_fx.DEFAULT_KINDS)
        for row in units_fx.unit_names(key)
    ]
    ghost_locale_unit = units_fx.build_snapshot(
        2,
        unit_names_=[
            *unit_rows,
            {"unit_id": units_fx.unit_id("kg"), "locale_id": GHOST, "name": "x", "plural": "x"},
        ],
    )
    region_ids = [regions_fx.region_id(k) for k in ("002", "019", "142")]
    ghost_locale_region = countries_fx.regions_snapshot(
        2,
        region_names=[
            *regions_fx.names_for_regions(region_ids),
            regions_fx.region_name("019", GHOST, "Amériques"),
        ],
    )
    # (módulo, snapshot, archivo, motivo esperado en la salida de la CLI)
    cases = (
        ("countries", ghost_region, "country-ghost-region.json", "no existe en Region/Subregion"),
        ("countries", future_regions, "country-future-regions.json", "RF-47"),
        ("currencies", ghost_country, "currency-ghost-country.json", GHOST),
        ("currencies", future_countries, "currency-future-countries.json", "RF-41"),
        ("units", ghost_locale_unit, "units-ghost-locale.json", GHOST),
        ("regions", ghost_locale_region, "regions-ghost-locale.json", GHOST),
    )
    for module, document, name, reason in cases:
        rejected = stack.incorporate(module, document, name)
        output = rejected.stdout + rejected.stderr
        assert rejected.returncode == 1, (name, output)
        assert "RECHAZADO" in output and reason in output, (name, output)
        assert "omite" not in output, (name, output)  # el rechazo es por la referencia, no otro
    assert stack.fingerprint() == before


def clone_with(url: str, table: str, overrides: dict[str, str]) -> str:
    """INSERT de una fila NUEVA copiada de una existente de `table`, con `overrides` (jsonb);
    omite las columnas generadas."""
    with psycopg.connect(url) as conn:
        columns = [
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = "
                "'reference' AND table_name = %s AND is_generated = 'NEVER' "
                "ORDER BY ordinal_position",
                [table],
            )
        ]
    names = ", ".join(columns)
    pairs = ", ".join(f"'{column}', %s::text" for column in overrides)
    return (
        f"INSERT INTO reference.{table} ({names}) SELECT {names} FROM "
        f"jsonb_populate_record(NULL::reference.{table}, (SELECT to_jsonb(t) || "
        f"jsonb_build_object({pairs}) FROM reference.{table} t LIMIT 1))"
    )


# Referencias entre módulos (aristas del grafo) que la base debe rechazar con una FK (23503).
FOREIGN_KEYS = (
    ("regions → locales", "region_locale", {"locale_id": GHOST}),
    ("regions → locales", "subregion_locale", {"locale_id": GHOST}),
    ("countries → locales", "country_locale", {"locale_id": GHOST}),
    ("currencies → locales", "currency_locale", {"locale_id": GHOST}),
    ("units → locales", "unit_locale", {"locale_id": GHOST}),
    ("units → locales", "quantity_kind_locale", {"locale_id": GHOST}),
    (
        "currencies → countries",
        "country_currency",
        {"country_currency_id": "6f1f9a3c-0000-4000-8000-000000000001", "country_id": GHOST},
    ),
)


def test_08_the_database_protects_cross_module_integrity(reference_stack: ReferenceStack) -> None:
    """CA-8: aun saltando la aplicación (rol dueño, SQL directo), la base rechaza toda referencia
    rota entre módulos (FK, 23503), el cambio de una referencia publicada y el borrado de
    identidades referenciadas (triggers de inmutabilidad, 23001)."""
    stack = reference_stack
    before = stack.fingerprint()
    outcomes = []

    def attempt(statement: str, params: list[str]) -> errors.Error:
        with psycopg.connect(stack.admin_url) as conn:
            with pytest.raises(errors.Error) as raised:
                with conn.transaction():
                    conn.execute(statement, params)
                    conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        outcomes.append(f"{statement} {params} -> {raised.value.sqlstate}")
        return raised.value

    for edge, table, overrides in FOREIGN_KEYS:
        error = attempt(clone_with(stack.admin_url, table, overrides), list(overrides.values()))
        assert isinstance(error, errors.ForeignKeyViolation), (edge, table, error)
    error = attempt("UPDATE reference.country SET region_id = %s WHERE alpha2 = 'AR'", [GHOST])
    assert isinstance(error, errors.ForeignKeyViolation), error
    for statement, target in (
        ("UPDATE reference.country_locale SET locale_id = %s", FR),
        ("UPDATE reference.country_currency SET country_id = %s", countries_fx.country_id("CA")),
        ("DELETE FROM reference.locale WHERE locale_id = %s", ES),
        ("DELETE FROM reference.region WHERE region_id = %s", regions_fx.region_id("019")),
        ("DELETE FROM reference.country WHERE country_id = %s", countries_fx.country_id("AR")),
        ("DELETE FROM reference.currency WHERE currency_id = %s", currencies_fx.currency_id("USD")),
        ("DELETE FROM reference.unit WHERE unit_id = %s", units_fx.unit_id("kg")),
    ):
        error = attempt(statement, [target])
        assert isinstance(error, errors.RestrictViolation | errors.ForeignKeyViolation), error
    stack.evidence.commands.append(
        {
            "command": "SQL directo (rol dueño)",
            "exit_code": 0,
            "stdout": "\n".join(outcomes),
            "stderr": "",
        }
    )
    assert stack.fingerprint() == before


def test_09_runtime_enforces_the_dependency_order(blank_stack: ReferenceStack) -> None:
    """CA-9: en una base nueva, incorporar un catálogo antes que su dependencia falla sin
    escribir; luego, en orden, todo pasa; `downgrade base` + `upgrade head` es reversible."""
    stack = blank_stack
    assert stack.alembic("upgrade", "head").returncode == 0
    enable_logins(stack)
    documents = snapshots()
    empty = stack.fingerprint()
    assert all(value.startswith("0:") for value in empty.values())
    for module in ("regions", "countries", "currencies", "units"):
        early = stack.incorporate(module, documents[module], f"early-{module}.json")
        assert early.returncode != 0, (module, early.stdout, early.stderr)
        assert "Traceback" not in early.stderr, (module, early.stderr)
    assert stack.fingerprint() == empty
    # Countries sin Regions aunque Locale ya esté; Currency sin Countries aunque Regions esté.
    assert stack.incorporate("locales", documents["locales"], "locales.json").returncode == 0
    assert stack.incorporate("countries", documents["countries"], "c-early.json").returncode != 0
    assert stack.incorporate("regions", documents["regions"], "regions.json").returncode == 0
    assert stack.incorporate("currencies", documents["currencies"], "k-early.json").returncode != 0
    for module in ("countries", "currencies", "units"):
        done = stack.incorporate(module, documents[module], f"{module}.json")
        assert done.returncode == 0, (module, done.stdout, done.stderr)

    down = stack.alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr
    with psycopg.connect(stack.admin_url) as conn:
        left = conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'reference' "
            "AND table_name <> 'alembic_version'"
        ).fetchone()
    assert left == (0,)
    up = stack.alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    enable_logins(stack)
    for module in ORDER:
        done = stack.incorporate(module, documents[module], f"again-{module}.json")
        assert done.returncode == 0, (module, done.stdout, done.stderr)


def test_10_the_api_is_read_only_and_roles_are_least_privilege(
    reference_stack: ReferenceStack,
) -> None:
    """CA-10: los catálogos no se modifican por HTTP (405) y `reference_reader` no escribe."""
    stack = reference_stack
    for path in (
        "/v1/locales",
        "/v1/regions",
        "/v1/subregions",
        "/v1/countries",
        "/v1/currencies",
        "/v1/units",
        "/v1/quantity-kinds",
    ):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert stack.send(method, path) == 405, (method, path)
    for method in ("GET", "PUT", "DELETE"):
        assert stack.send(method, "/v1/conversions") == 405, method
    with psycopg.connect(stack.reader_url) as conn:
        for statement in (
            "DELETE FROM reference.locale",
            "UPDATE reference.country SET calling_code = '0'",
            "INSERT INTO reference.currency_snapshot DEFAULT VALUES",
            "TRUNCATE reference.unit",
        ):
            with pytest.raises(errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute(statement)


@pytest.mark.parametrize("module", list(OPENAPI))
def test_11_served_openapi_equals_the_published_contract(
    reference_stack: ReferenceStack, module: str
) -> None:
    """CA-11: regresión de contratos: lo servido = `contracts/*-api.v1.openapi.json`."""
    url, published = OPENAPI[module]
    status, body = reference_stack.get(url)
    assert status == 200
    assert body == json.loads((ROOT / "contracts" / published).read_text("utf-8"))


CONVERSIONS = (
    ("1", "lb", "kg", "mass", "0.45359237", True),
    ("100", "Cel", "degF", "temperature", "212", True),
    ("0", "K", "Cel", "temperature", "-273.15", True),
    ("1", "km", "m", "length", "1000", True),
)


@pytest.mark.parametrize(("value", "source", "target", "kind", "result", "exact"), CONVERSIONS)
def test_12_conversions_are_exact_in_the_integrated_system(
    reference_stack: ReferenceStack,
    value: str,
    source: str,
    target: str,
    kind: str,
    result: str,
    exact: bool,
) -> None:
    """CA-12: conversiones lineales y afines exactas, como cadenas decimales (sin float)."""
    status, body = reference_stack.post(
        "/v1/conversions",
        {
            "value": value,
            "from_unit_id": units_fx.unit_id(source),
            "to_unit_id": units_fx.unit_id(target),
            "quantity_kind_id": units_fx.kind_id(kind),
        },
    )
    assert status == 200, body
    assert data(body)["result"] == result
    assert data(body)["exact"] is exact
    assert Decimal(data(body)["result"]) == Decimal(result)


def test_12b_incompatible_conversion_is_rejected(reference_stack: ReferenceStack) -> None:
    """CA-12: convertir entre magnitudes distintas (kg → m) se rechaza con 4xx y un código."""
    status, body = reference_stack.post(
        "/v1/conversions",
        {
            "value": "1",
            "from_unit_id": units_fx.unit_id("kg"),
            "to_unit_id": units_fx.unit_id("m"),
            "quantity_kind_id": units_fx.kind_id("mass"),
        },
    )
    assert 400 <= status < 500, body
    assert "code" in json.dumps(body)


def test_13_no_process_reached_outside_localhost(reference_stack: ReferenceStack) -> None:
    """CA-13: CLIs, migraciones y API corrieron con el guard de red: nada salió de localhost."""
    stack = reference_stack
    stack.get("/v1/locales")
    log = stack.net_log.read_text("utf-8") if stack.net_log.exists() else ""
    assert log == ""


def test_14_006_does_not_modify_product_code_or_existing_tests(
    reference_stack: ReferenceStack,
) -> None:
    """CA-14: 006 solo agrega pruebas, documentación, el grafo y su spec: código, migraciones,
    contratos y pruebas existentes de 001–005 quedan idénticos."""
    base = base_ref()
    paths = (
        "src",
        "migrations",
        "contracts",
        "architecture.json",
        "pyproject.toml",
        "constraints.txt",
        "specs/001-locales",
        "specs/002-regions-subregions",
        "specs/003-countries",
        "specs/004-currency",
        "specs/005-units-of-measure",
    )
    diff = subprocess.run(
        ["git", "diff", "--stat", base, "--", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert diff.returncode == 0, diff.stderr
    assert diff.stdout.strip() == "", diff.stdout
    touched = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=MDR", base, "--", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert touched.returncode == 0, touched.stderr
    assert touched.stdout.strip() == "", touched.stdout
    reference_stack.evidence.commands.append(
        {
            "command": f"git diff --stat {base} -- <código, migraciones, contratos, specs 001-005>",
            "exit_code": diff.returncode,
            "stdout": diff.stdout.strip(),
            "stderr": "",
        }
    )


def test_15_country_retirement_drift_is_detected_and_repaired_across_modules(
    reference_stack: ReferenceStack,
) -> None:
    """CA-15: Countries v2 retira PR mientras Currency tiene PR–USD abierta (Countries no conoce
    Currency): `currencies check-integrity` lo detecta (exit 1), Currency v2 con la vigencia
    cerrada lo repara (exit 0) y la API refleja ambos cambios. Va al final: cambia el estado."""
    stack = reference_stack
    assert stack.catalog("currencies", "check-integrity").returncode == 0

    retired = countries_retiring_pr()
    done = stack.incorporate("countries", retired, "countries-v2-retire-pr.json")
    assert done.returncode == 0, (done.stdout, done.stderr)
    status, body = stack.get(f"/v1/countries/{countries_fx.country_id('PR')}")
    assert status == 200 and data(body)["status"] == "inactive", body

    drift = stack.catalog("currencies", "check-integrity", url=stack.reader_url)
    assert drift.returncode == 1, (drift.stdout, drift.stderr)
    assert "INTEGRIDAD VIOLADA" in drift.stdout + drift.stderr
    assert currencies_fx.association_id("PR", "USD") in drift.stdout + drift.stderr

    stale = currency_snapshot(2, country_snapshot_version=1)
    rejected = stack.incorporate("currencies", stale, "currencies-v2-stale.json")
    assert rejected.returncode == 1, (rejected.stdout, rejected.stderr)

    repaired = currencies_closing_pr()
    done = stack.incorporate("currencies", repaired, "currencies-v2-close-pr.json")
    assert done.returncode == 0, (done.stdout, done.stderr)
    healthy = stack.catalog("currencies", "check-integrity", url=stack.reader_url)
    assert healthy.returncode == 0, (healthy.stdout, healthy.stderr)

    status, body = stack.get("/v1/currencies/by-code/USD")
    usd = data(body)["currency_id"]
    status, body = stack.get(f"/v1/currencies/{usd}/countries")
    assert status == 200, body
    assert {row["country_id"] for row in items(body)} == {countries_fx.country_id("US")}
    status, body = stack.get(f"/v1/currencies/{usd}/countries/history")
    assert status == 200, body
    assert countries_fx.country_id("PR") in {row["country_id"] for row in items(body)}
