"""T6: incorporación de Units contra Postgres real.

RF-6, RF-42 a RF-46, RNF-1, RNF-2, CL-16, CA-6, CA-10, CA-14.
"""

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from gi_common_reference.bootstrap import (
    postgres_repository,
    postgres_units_repository,
    read_units_snapshot,
    units_required_locales,
    units_ucum_table,
)
from gi_common_reference.locales.application.incorporate import Outcome as LocaleOutcome
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.units.application.incorporate import (
    IncorporationResult,
    Outcome,
    incorporate_snapshot,
)
from gi_common_reference.units.domain.errors import PersistenceError
from gi_common_reference.units.interfaces.cli import main
from tests.conftest import NetworkGuard
from tests.fixtures.regions import locale_snapshot
from tests.fixtures.units import EN, ES, build_snapshot, kind_id, seal, unit_id
from tests.fixtures.units_variants import SACK_ID, retired_oz, sack_snapshot
from tests.unit.units.helpers import association_row, edit, kind_row, unit_row

TABLES = {
    "unit_snapshot": "snapshot_version, content_digest, locale_snapshot_version, "
    "required_locales_version, ucum_table_version, provenance, artifact",
    "quantity_kind": "quantity_kind_id::text, code, conversion_type, reference_unit_id::text, "
    "status, first_snapshot_version, last_changed_snapshot_version",
    "unit": "unit_id::text, ucum_code, unece_code, symbol, status, first_snapshot_version, "
    "last_changed_snapshot_version",
    "quantity_kind_unit": 'quantity_kind_id::text, unit_id::text, factor, "offset", status, '
    "first_snapshot_version, last_changed_snapshot_version",
    "quantity_kind_locale": "quantity_kind_id::text, locale_id::text, name",
    "unit_locale": "unit_id::text, locale_id::text, name, plural",
}


def incorporate(url: str, document: dict[str, Any]) -> IncorporationResult:
    return incorporate_snapshot(
        document, postgres_units_repository(url), units_required_locales(), units_ucum_table()
    )


def logical_state(url: str) -> dict[str, list[tuple[Any, ...]]]:
    with psycopg.connect(url) as conn:
        return {
            table: conn.execute(f"SELECT {columns} FROM reference.{table} ORDER BY 1, 2").fetchall()
            for table, columns in TABLES.items()
        }


@pytest.fixture
def ready(database_factory: Callable[[], str]) -> Callable[[], str]:
    """Bases nuevas con un snapshot sintético de Locale (con `en` y `es` de la política)."""

    def create() -> str:
        url = database_factory()
        result = incorporate_locales(locale_snapshot(1), postgres_repository(url))
        assert result.outcome is LocaleOutcome.INCORPORATED
        return url

    return create


@pytest.fixture
def url(ready: Callable[[], str]) -> str:
    return ready()


# --- flujo básico


def test_the_first_snapshot_round_trips_exactly(url: str) -> None:
    document = build_snapshot(1)
    result = incorporate(url, document)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.new_units, result.new_quantity_kinds, result.new_associations) == (50, 14, 54)
    assert (result.locale_snapshot_version, result.ucum_table_version) == (1, "2.2")
    state = logical_state(url)
    assert [len(state[t]) for t in ("unit", "quantity_kind", "quantity_kind_unit")] == [50, 14, 54]
    assert len(state["quantity_kind_locale"]) == 28 and len(state["unit_locale"]) == 100
    (snapshot,) = state["unit_snapshot"]
    assert snapshot[:5] == (1, document["content_digest"], 1, 1, "2.2")
    assert snapshot[5] == document["provenance"]
    assert snapshot[6] == document  # el artefacto es el documento tal cual
    assert {row[5] for row in state["unit"]} == {1} and {row[6] for row in state["unit"]} == {1}
    with psycopg.connect(url) as conn:
        factors: dict[str, str] = dict(
            conn.execute(
                "SELECT u.symbol || '|' || k.code, a.factor || '|' || a.\"offset\" "
                "FROM reference.quantity_kind_unit a "
                "JOIN reference.unit u USING (unit_id) "
                "JOIN reference.quantity_kind k USING (quantity_kind_id)"
            ).fetchall()
        )
        nulls = conn.execute(
            "SELECT symbol FROM reference.unit WHERE unece_code IS NULL ORDER BY symbol"
        ).fetchall()
        plural = conn.execute(
            "SELECT plural FROM reference.unit_locale WHERE unit_id = %s AND locale_id = %s",
            [unit_id("lb"), ES],
        ).fetchone()
    assert factors["°F|temperature"] == "5/9|459.67" and factors["km/h|speed"] == "5/18|0"
    assert factors["lb|mass"] == "0.45359237|0" and factors["°C|temperature"] == "1|273.15"
    assert [s for (s,) in nulls][0] == "L/ha" and "ha" in [s for (s,) in nulls]
    assert plural == ("libras",)


def test_resubmitting_the_same_snapshot_is_a_noop_with_an_identical_database(url: str) -> None:
    document = build_snapshot(1)
    incorporate(url, document)
    before = logical_state(url)
    again = incorporate(url, json.loads(json.dumps(document)))
    assert again.outcome is Outcome.NOOP
    assert logical_state(url) == before


def test_a_higher_version_with_gaps_is_applied(url: str) -> None:
    incorporate(url, build_snapshot(1))
    assert incorporate(url, build_snapshot(7)).outcome is Outcome.INCORPORATED
    with psycopg.connect(url) as conn:
        assert conn.execute(
            "SELECT array_agg(snapshot_version ORDER BY snapshot_version) "
            "FROM reference.unit_snapshot"
        ).fetchone() == ([1, 7],)


# --- rechazos con dump idéntico


def omitted_unit() -> dict[str, Any]:
    def omit(document: dict[str, Any]) -> None:
        document["snapshot_version"] = 6
        document["units"] = [u for u in document["units"] if u["unit_id"] != unit_id("oz")]
        document["quantity_kind_units"] = [
            a for a in document["quantity_kind_units"] if a["unit_id"] != unit_id("oz")
        ]
        document["unit_names"] = [
            n for n in document["unit_names"] if n["unit_id"] != unit_id("oz")
        ]

    return seal(edit(build_snapshot(1), omit))


def tampered() -> dict[str, Any]:
    document = build_snapshot(6)
    unit_row(document, "kg")["symbol"] = "KG"
    return document


@pytest.mark.parametrize(
    "case",
    [
        "same_version_other_digest",
        "lower_version",
        "tampered_digest",
        "invalid_ucum",
        "wrong_factor",
        "omission",
        "retired_reference",
        "no_name",
    ],
)
def test_a_rejected_snapshot_leaves_the_database_identical(url: str, case: str) -> None:
    incorporate(url, build_snapshot(5))
    before = logical_state(url)
    document: dict[str, Any]
    if case == "same_version_other_digest":
        document = build_snapshot(5, codes=("mass",))
    elif case == "lower_version":
        document = build_snapshot(3)
    elif case == "tampered_digest":
        document = tampered()
    elif case == "invalid_ucum":
        document = seal(edit(build_snapshot(6), lambda d: unit_row(d, "oz").update(ucum_code="xx")))
    elif case == "wrong_factor":
        document = seal(
            edit(build_snapshot(6), lambda d: association_row(d, "mass", "lb").update(factor="0.5"))
        )
    elif case == "omission":
        document = omitted_unit()
    elif case == "retired_reference":
        document = seal(
            edit(build_snapshot(6), lambda d: unit_row(d, "kg").update(status="inactive"))
        )
    else:
        document = build_snapshot(6)
        document["quantity_kind_names"] = [
            n for n in document["quantity_kind_names"] if n["locale_id"] != EN
        ]
        document = seal(document)
    result = incorporate(url, document)
    assert result.outcome is Outcome.REJECTED and result.violations
    assert logical_state(url) == before


def test_a_snapshot_whose_final_state_violates_a_constraint_is_a_rejection(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el dominio no lo detectara, la base lo rechaza al forzar las constraints diferidas."""
    incorporate(url, build_snapshot(1))
    before = logical_state(url)
    import gi_common_reference.units.application.incorporate as module
    from gi_common_reference.units.domain.catalog import CatalogPlan

    document = seal(edit(build_snapshot(2), lambda d: unit_row(d, "kg").update(status="inactive")))
    result = incorporate(url, document)
    assert result.outcome is Outcome.REJECTED  # lo detecta el dominio
    assert logical_state(url) == before

    # ahora el dominio acepta todo y la base debe rechazar (kg activa referencia de masa)
    def permissive(incoming: Any, *rest: Any) -> CatalogPlan:
        from gi_common_reference.units.domain.catalog import _plan

        return _plan(incoming, rest[0])

    monkeypatch.setattr(module, "plan_catalog_changes", permissive)
    forced = incorporate(url, document)
    assert forced.outcome is Outcome.REJECTED
    assert forced.violations[0].rule == "RF-8"
    assert logical_state(url) == before


def test_a_failure_in_the_middle_of_the_writes_rolls_everything_back(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    incorporate(url, sack_snapshot(1, factor="60"))
    before = logical_state(url)
    from gi_common_reference.units.infrastructure import postgres_repository as module

    def boom(self: Any, associations: Any, version: int) -> None:
        raise psycopg.errors.OperationalError("boom con s3cr3t")

    monkeypatch.setattr(module.PostgresUnitsTransaction, "update_associations", boom)
    with pytest.raises(PersistenceError) as error:
        incorporate(url, sack_snapshot(2, factor="50"))
    assert "s3cr3t" not in str(error.value)
    assert logical_state(url) == before


# --- versión posterior: alta, retiro, cambio de factor


def test_version_two_with_an_addition_a_retirement_and_a_changed_factor(url: str) -> None:
    assert incorporate(url, sack_snapshot(1, factor="60")).outcome is Outcome.INCORPORATED

    def second(document: dict[str, Any]) -> None:
        document["snapshot_version"] = 2
        for row in document["quantity_kind_units"]:
            if row["unit_id"] == SACK_ID:
                row["factor"] = "50"
        unit_row(document, "oz")["status"] = "inactive"
        association_row(document, "mass", "oz")["status"] = "inactive"
        document["units"].append(
            {
                "unit_id": "6f0e0000-0000-4000-8000-0000000000aa",
                "ucum_code": None,
                "unece_code": None,
                "symbol": "bag",
                "status": "active",
            }
        )
        document["quantity_kind_units"].append(
            {
                "quantity_kind_id": kind_id("mass"),
                "unit_id": "6f0e0000-0000-4000-8000-0000000000aa",
                "factor": "25",
                "offset": "0",
                "status": "active",
            }
        )
        document["unit_names"] += [
            {
                "unit_id": "6f0e0000-0000-4000-8000-0000000000aa",
                "locale_id": EN,
                "name": "bag",
                "plural": None,
            },
            {
                "unit_id": "6f0e0000-0000-4000-8000-0000000000aa",
                "locale_id": ES,
                "name": "bolsa",
                "plural": None,
            },
        ]

    document = seal(edit(sack_snapshot(1, factor="60"), second))
    before = {row[0]: row for row in logical_state(url)["unit"]}
    result = incorporate(url, document)
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.new_units, result.updated_units, result.updated_associations) == (1, 1, 2)
    with psycopg.connect(url) as conn:
        factor = conn.execute(
            "SELECT factor, first_snapshot_version, last_changed_snapshot_version "
            "FROM reference.quantity_kind_unit WHERE unit_id = %s",
            [SACK_ID],
        ).fetchone()
        oz = conn.execute(
            "SELECT status, first_snapshot_version, last_changed_snapshot_version "
            "FROM reference.unit WHERE unit_id = %s",
            [unit_id("oz")],
        ).fetchone()
        bag = conn.execute(
            "SELECT first_snapshot_version, last_changed_snapshot_version FROM reference.unit "
            "WHERE symbol = 'bag'"
        ).fetchone()
        assoc_oz = conn.execute(
            "SELECT status, last_changed_snapshot_version FROM reference.quantity_kind_unit "
            "WHERE unit_id = %s",
            [unit_id("oz")],
        ).fetchone()
    assert factor == ("50", 1, 2) and oz == ("inactive", 1, 2) and bag == (2, 2)
    assert assoc_oz == ("inactive", 2)
    after = {row[0]: row for row in logical_state(url)["unit"]}
    untouched = [i for i in before if i not in (unit_id("oz"),)]
    assert all(after[i] == before[i] for i in untouched)  # el resto no cambió ni de versión


def test_a_retirement_alone_keeps_the_rest_of_the_catalog_untouched(url: str) -> None:
    incorporate(url, build_snapshot(1))
    before = logical_state(url)
    result = incorporate(url, retired_oz(2))
    assert result.outcome is Outcome.INCORPORATED, result.violations
    after = logical_state(url)
    changed = [r for r in after["unit"] if r not in before["unit"]]
    assert [r[0] for r in changed] == [unit_id("oz")] and changed[0][4] == "inactive"
    assert after["quantity_kind"] == before["quantity_kind"]


def test_two_databases_receiving_the_same_snapshots_end_in_the_same_state(
    ready: Callable[[], str],
) -> None:
    """RNF-1."""
    first, second = ready(), ready()
    for target in (first, second):
        incorporate(target, sack_snapshot(1))
        incorporate(target, sack_snapshot(2, factor="50", retired=("oz",)))
    state_a, state_b = logical_state(first), logical_state(second)
    for table in TABLES:
        assert [r for r in state_a[table] if table != "unit_snapshot"] == [
            r for r in state_b[table] if table != "unit_snapshot"
        ]
    assert [r[:5] for r in state_a["unit_snapshot"]] == [r[:5] for r in state_b["unit_snapshot"]]


# --- locks, privilegios y CLI


def test_two_simultaneous_incorporations_of_the_same_snapshot_are_serialized(url: str) -> None:
    document = build_snapshot(1)
    results: list[Outcome] = []
    gate = threading.Barrier(2)

    def worker() -> None:
        gate.wait(timeout=20)
        results.append(incorporate(url, json.loads(json.dumps(document))).outcome)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert sorted(results) == [Outcome.INCORPORATED, Outcome.NOOP]
    assert len(logical_state(url)["unit_snapshot"]) == 1


def test_incorporation_works_with_the_least_privileged_loader_role(url: str) -> None:
    """Todas las sentencias de escritura caben en los permisos de `reference_loader`."""
    loader = make_conninfo(url, options="-c role=reference_loader")
    for document in (sack_snapshot(1, factor="60"), sack_snapshot(2, factor="50", retired=("oz",))):
        result = incorporate(loader, document)
        assert result.outcome is Outcome.INCORPORATED, result.violations
    renamed = sack_snapshot(3, factor="50", retired=("oz",))
    for item in renamed["unit_names"]:
        if item["unit_id"] == unit_id("kg") and item["locale_id"] == EN:
            item["name"] = "kilo"
            item["plural"] = "kilos"
    for item in renamed["quantity_kind_names"]:
        if item["quantity_kind_id"] == kind_id("mass") and item["locale_id"] == EN:
            item["name"] = "Mass!"
    assert incorporate(loader, seal(renamed)).outcome is Outcome.INCORPORATED
    state = logical_state(url)
    kg = next(r for r in state["unit"] if r[0] == unit_id("kg"))
    mass = next(r for r in state["quantity_kind"] if r[0] == kind_id("mass"))
    assert kg[5:] == (1, 3) and mass[5:] == (1, 3)
    assert kind_row(renamed, "mass")["status"] == "active"


def test_the_cli_incorporates_diffs_and_never_prints_credentials(
    url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(build_snapshot(1), ensure_ascii=False), encoding="utf-8")
    env = {"REFERENCE_DATABASE_URL": url}

    def cli(*args: str) -> int:
        return main(
            list(args),
            environ=env,
            repository_factory=postgres_units_repository,
            snapshot_reader=read_units_snapshot,
            policy_loader=units_required_locales,
            ucum_loader=units_ucum_table,
        )

    with NetworkGuard(monkeypatch) as guard:
        assert cli("diff", str(path)) == 0
        assert logical_state(url)["unit"] == []  # diff no escribe
        assert cli("incorporate", str(path)) == 0
        assert cli("incorporate", str(path)) == 0  # no-op
        assert cli("diff", str(path)) == 0
        rejected = tmp_path / "other.json"
        rejected.write_text(json.dumps(build_snapshot(1, codes=("mass",))), encoding="utf-8")
        assert cli("incorporate", str(rejected)) == 1
        assert cli("diff", str(rejected)) == 1
    assert not guard.blocked  # RNF-8: ningún acceso de red fuera de localhost
    out = capsys.readouterr()
    assert "INCORPORADO" in out.out and "NO-OP" in out.out and "RECHAZADO" in out.err
    password = str(conninfo_to_dict(url).get("password") or "<none>")
    assert password not in out.out + out.err


def test_the_cli_exits_two_when_the_database_is_unreachable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(build_snapshot(1)), encoding="utf-8")
    unreachable = "postgresql://u:s3cr3t@127.0.0.1:1/none?connect_timeout=2"
    code = main(
        ["incorporate", str(path)],
        environ={"REFERENCE_DATABASE_URL": unreachable},
        repository_factory=postgres_units_repository,
        snapshot_reader=read_units_snapshot,
        policy_loader=units_required_locales,
        ucum_loader=units_ucum_table,
    )
    out = capsys.readouterr()
    assert code == 2 and "s3cr3t" not in out.out + out.err


def test_the_diff_of_a_later_version_lists_the_changed_factor(
    url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    incorporate(url, sack_snapshot(1, factor="60"))
    path = tmp_path / "v2.json"
    path.write_text(json.dumps(sack_snapshot(2, factor="50")), encoding="utf-8")
    code = main(
        ["diff", str(path)],
        environ={"REFERENCE_DATABASE_URL": url},
        repository_factory=postgres_units_repository,
        snapshot_reader=read_units_snapshot,
        policy_loader=units_required_locales,
        ucum_loader=units_ucum_table,
    )
    out = capsys.readouterr().out
    assert code == 0 and "60" in out and "50" in out
    assert len(logical_state(url)["unit_snapshot"]) == 1
