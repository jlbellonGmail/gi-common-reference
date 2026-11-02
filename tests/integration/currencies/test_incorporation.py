"""T6: incorporación de Currency contra Postgres real.

RF-3, RF-10, RF-19, RF-36 a RF-41, RF-43, RF-45, RF-47, RNF-1, RNF-2, RNF-5, RNF-8, CA-10, CA-11.
"""

import json
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from gi_common_reference.bootstrap import (
    currency_required_locales,
    postgres_currency_repository,
    postgres_region_repository,
    postgres_repository,
    read_currency_snapshot,
    required_locales,
)
from gi_common_reference.currencies.application.incorporate import (
    IncorporationResult,
    Outcome,
    incorporate_snapshot,
)
from gi_common_reference.currencies.interfaces.cli import main
from gi_common_reference.locales.application.incorporate import Outcome as LocaleOutcome
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.regions.application.incorporate import Outcome as RegionOutcome
from gi_common_reference.regions.application.incorporate import (
    incorporate_snapshot as incorporate_regions,
)
from tests.conftest import NetworkGuard
from tests.fixtures.countries import regions_snapshot
from tests.fixtures.currencies import (
    COUNTRY_CODES,
    DEFAULT_ASSOCIATIONS,
    DEFAULT_CODES,
    EN,
    association,
    build_snapshot,
    country_id,
    currency,
    currency_id,
    names,
    seal,
    transition_snapshot,
)
from tests.fixtures.regions import locale_snapshot

D = date
TABLES = {
    "currency_snapshot": "snapshot_version, content_digest, locale_snapshot_version, "
    "country_snapshot_version, country_current_snapshot_version, required_locales_version, "
    "provenance, artifact",
    "currency": "currency_id::text, alphabetic_code, numeric_code, minor_units, fund_code, status, "
    "replacement_currency_ids::text[], first_snapshot_version, last_changed_snapshot_version",
    "currency_locale": "currency_id::text, locale_id::text, name",
    "country_currency": "country_currency_id::text, country_id::text, currency_id::text, status, "
    "valid_from, valid_to, first_snapshot_version, last_changed_snapshot_version",
}


def incorporate(url: str, document: dict[str, Any]) -> IncorporationResult:
    return incorporate_snapshot(
        document, postgres_currency_repository(url), currency_required_locales()
    )


def logical_state(url: str) -> dict[str, list[tuple[Any, ...]]]:
    with psycopg.connect(url) as conn:
        return {
            table: conn.execute(f"SELECT {columns} FROM reference.{table} ORDER BY 1, 2").fetchall()
            for table, columns in TABLES.items()
        }


def seed_countries(url: str, *, inactive: tuple[str, ...] = (), version: int = 1) -> None:
    """Un snapshot de Countries y los países de los fixtures (sin clasificación)."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO reference.country_snapshot (snapshot_version, content_digest, "
            "locale_snapshot_version, region_snapshot_version, region_current_snapshot_version, "
            "required_locales_version, provenance, artifact) "
            "VALUES (%s, %s, 1, 1, 1, 1, '{}', '{}')",
            [version, "sha256:" + "d" * 64],
        )
        for index, code in enumerate(COUNTRY_CODES, start=1):
            conn.execute(
                "INSERT INTO reference.country (country_id, alpha2, alpha3, numeric_code, status, "
                "first_snapshot_version, codes_snapshot_version, last_changed_snapshot_version) "
                "VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s)",
                [
                    country_id(code),
                    code,
                    code + "X",
                    f"{900 + index:03d}",
                    "inactive" if code in inactive else "active",
                    version,
                    version,
                    version,
                ],
            )


@pytest.fixture
def ready(database_factory: Callable[[], str]) -> Callable[[], str]:
    """Bases nuevas con Locale (en, es) y Regions incorporados y Countries sembrado."""

    def create() -> str:
        url = database_factory()
        assert (
            incorporate_locales(locale_snapshot(1), postgres_repository(url)).outcome
            is LocaleOutcome.INCORPORATED
        )
        result = incorporate_regions(
            regions_snapshot(1), postgres_region_repository(url), required_locales()
        )
        assert result.outcome is RegionOutcome.INCORPORATED, result.violations
        seed_countries(url)
        return url

    return create


@pytest.fixture
def url(ready: Callable[[], str]) -> str:
    return ready()


def all_codes() -> tuple[str, ...]:
    return DEFAULT_CODES


def transition(version: int = 2) -> dict[str, Any]:
    return transition_snapshot(version)


# --- flujo básico ---------------------------------------------------------------------------------


def test_the_first_snapshot_registers_every_version_in_force(url: str) -> None:
    result = incorporate(url, build_snapshot(1))
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.new_currencies, result.new_associations, result.names) == (15, 15, 30)
    assert (result.locale_snapshot_version, result.country_snapshot_version) == (1, 1)
    state = logical_state(url)
    assert len(state["currency"]) == 15 and len(state["country_currency"]) == 15
    (snapshot,) = state["currency_snapshot"]
    assert snapshot[:6] == (1, build_snapshot(1)["content_digest"], 1, 1, 1, 1)
    assert snapshot[7]["currencies"][0]["alphabetic_code"] == "ARS"  # el artefacto se conserva
    assert {row[7] for row in state["currency"]} == {1}


def test_codes_dates_and_minor_units_round_trip_exactly(url: str) -> None:
    incorporate(url, build_snapshot(1))
    with psycopg.connect(url) as conn:
        rows: dict[str, str] = dict(
            conn.execute(
                "SELECT alphabetic_code, numeric_code || '|' || coalesce(minor_units::text, 'NA') "
                "FROM reference.currency"
            ).fetchall()
        )
        hr = conn.execute(
            "SELECT valid_from, valid_to FROM reference.country_currency WHERE country_id = %s",
            [country_id("HR")],
        ).fetchone()
    assert rows["ARS"] == "032|2" and rows["BOB"] == "068|2"
    assert rows["JPY"] == "392|0" and rows["KWD"] == "414|3" and rows["CLF"] == "990|4"
    assert rows["XAU"] == "959|NA" and rows["XDR"] == "960|NA"
    assert hr == (D(1994, 5, 30), None)


def test_resubmitting_the_same_snapshot_is_a_noop_with_an_identical_database(url: str) -> None:
    document = build_snapshot(1)
    incorporate(url, document)
    before = logical_state(url)
    again = incorporate(url, json.loads(json.dumps(document)))
    assert again.outcome is Outcome.NOOP
    assert logical_state(url) == before


def test_a_higher_version_with_gaps_is_applied(url: str) -> None:
    incorporate(url, build_snapshot(1))
    result = incorporate(url, build_snapshot(7))
    assert result.outcome is Outcome.INCORPORATED
    with psycopg.connect(url) as conn:
        assert conn.execute(
            "SELECT array_agg(snapshot_version ORDER BY snapshot_version) "
            "FROM reference.currency_snapshot"
        ).fetchone() == ([1, 7],)


# --- rechazos con dump idéntico


@pytest.mark.parametrize(
    "case",
    ["same_version_other_digest", "lower_version", "tampered_digest", "unknown_country", "no_name"],
)
def test_a_rejected_snapshot_leaves_the_database_identical(url: str, case: str) -> None:
    incorporate(url, build_snapshot(5))
    before = logical_state(url)
    document: dict[str, Any]
    if case == "same_version_other_digest":
        document = build_snapshot(5, codes=("ARS",))
    elif case == "lower_version":
        document = build_snapshot(3)
    elif case == "tampered_digest":
        document = build_snapshot(6)
        document["currencies"][0]["minor_units"] = 9
    elif case == "unknown_country":
        document = build_snapshot(
            6,
            country_currencies=[association(a, c, f, t) for a, c, f, t in DEFAULT_ASSOCIATIONS]
            + [
                association(
                    "AR", "USD", D(2000, 1, 1), country_id="00000000-0000-4000-8000-000000000001"
                )
            ],
        )
    else:
        kept = [
            n for c in all_codes() for n in names(c) if not (c == "ARS" and n["locale_id"] == EN)
        ]
        document = build_snapshot(6, currency_names=kept)
    result = incorporate(url, document)
    assert result.outcome is Outcome.REJECTED and result.violations
    assert logical_state(url) == before


def test_a_failure_in_the_middle_of_the_writes_rolls_everything_back(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RF-39: atomicidad dentro de Currency, también ante un error técnico."""
    incorporate(url, build_snapshot(1))
    before = logical_state(url)
    from gi_common_reference.currencies.infrastructure import postgres_repository as module

    def boom(self: Any, associations: Any, version: int) -> None:
        raise psycopg.errors.OperationalError("boom con s3cr3t")

    monkeypatch.setattr(module.PostgresCurrencyTransaction, "insert_associations", boom)
    from gi_common_reference.currencies.domain.errors import PersistenceError

    with pytest.raises(PersistenceError) as error:
        incorporate(url, transition())
    assert "s3cr3t" not in str(error.value)
    assert logical_state(url) == before


# --- transición, división, reactivación, historia


def test_hrk_to_eur_keeps_the_id_and_preserves_the_history(url: str) -> None:
    """CA-9, CA-19, CL-8, CL-20."""
    incorporate(url, build_snapshot(1))
    result = incorporate(url, transition())
    assert result.outcome is Outcome.INCORPORATED, result.violations
    assert (result.updated_currencies, result.new_associations, result.updated_associations) == (
        1,
        1,
        1,
    )
    with psycopg.connect(url) as conn:
        hrk = conn.execute(
            "SELECT currency_id::text, status, replacement_currency_ids::text[], "
            "first_snapshot_version, last_changed_snapshot_version "
            "FROM reference.currency WHERE alphabetic_code = 'HRK'"
        ).fetchone()
        history = conn.execute(
            "SELECT c.alphabetic_code, a.status, a.validity::text "
            "FROM reference.country_currency a "
            "JOIN reference.currency c USING (currency_id) WHERE a.country_id = %s "
            "ORDER BY a.valid_from",
            [country_id("HR")],
        ).fetchall()

        def on_day(day: date) -> list[tuple[Any, ...]]:
            return conn.execute(
                "SELECT c.alphabetic_code FROM reference.country_currency a "
                "JOIN reference.currency c USING (currency_id) "
                "WHERE a.country_id = %s AND a.status = 'active' AND a.validity @> %s::date",
                [country_id("HR"), day],
            ).fetchall()

        before_day, on_the_day = on_day(D(2022, 12, 31)), on_day(D(2023, 1, 1))
        integrity = conn.execute(
            "SELECT count(*) FROM reference.country_currency_integrity_violation"
        ).fetchone()
    assert hrk == (currency_id("HRK"), "inactive", [currency_id("EUR")], 1, 2)
    assert history == [
        ("HRK", "active", "[1994-05-30,2023-01-01)"),
        ("EUR", "active", "[2023-01-01,)"),
    ]
    assert before_day == [("HRK",)] and on_the_day == [("EUR",)]
    assert integrity == (0,)


def test_the_published_history_cannot_be_rewritten_by_a_later_snapshot(url: str) -> None:
    incorporate(url, build_snapshot(1))
    incorporate(url, transition())
    before = logical_state(url)
    rewritten = transition(3)
    for item in rewritten["country_currencies"]:
        if item["currency_id"] == currency_id("HRK"):
            item["valid_to"] = "2023-06-01"
    result = incorporate(url, seal(rewritten))
    assert result.outcome is Outcome.REJECTED
    assert {v.rule for v in result.violations} == {"RF-47"}
    assert logical_state(url) == before


def test_a_division_stores_many_replacements_in_ascending_order(url: str) -> None:
    """CL-18."""
    codes = ("CSK", "CZK", "SKK")
    incorporate(url, build_snapshot(1, codes=codes, country_currencies=[]))
    csk = currency(
        "CSK", status="inactive", replacement_currency_ids=[currency_id("SKK"), currency_id("CZK")]
    )
    result = incorporate(
        url,
        build_snapshot(
            2,
            currencies=[csk, currency("CZK"), currency("SKK")],
            currency_names=[n for c in codes for n in names(c)],
            country_currencies=[],
        ),
    )
    assert result.outcome is Outcome.INCORPORATED, result.violations
    with psycopg.connect(url) as conn:
        stored = conn.execute(
            "SELECT replacement_currency_ids::text[] FROM reference.currency "
            "WHERE alphabetic_code = 'CSK'"
        ).fetchone()
    assert stored == (sorted([currency_id("CZK"), currency_id("SKK")]),)


def test_a_reactivation_clears_the_replacements_and_revalidates_the_numeric_code(url: str) -> None:
    """CL-19."""
    codes = ("HRK", "EUR")
    retired = currency("HRK", status="inactive", replacement_currency_ids=[currency_id("EUR")])
    incorporate(
        url,
        build_snapshot(
            1,
            currencies=[retired, currency("EUR")],
            currency_names=[n for c in codes for n in names(c)],
            country_currencies=[],
        ),
    )
    result = incorporate(
        url,
        build_snapshot(
            2,
            currencies=[currency("HRK"), currency("EUR")],
            currency_names=[n for c in codes for n in names(c)],
            country_currencies=[],
        ),
    )
    assert result.outcome is Outcome.INCORPORATED, result.violations
    with psycopg.connect(url) as conn:
        assert conn.execute(
            "SELECT status, replacement_currency_ids FROM reference.currency "
            "WHERE alphabetic_code = 'HRK'"
        ).fetchone() == ("active", [])


def test_a_list_three_currency_is_added_later_without_touching_the_existing_ones(url: str) -> None:
    """CA-15, RF-43."""
    incorporate(url, build_snapshot(1))
    before = {r[0]: r for r in logical_state(url)["currency"]}
    old = currency("YUM", status="inactive")
    result = incorporate(
        url,
        build_snapshot(
            2,
            currencies=[*(currency(c) for c in all_codes()), old],
            currency_names=[n for c in (*all_codes(), "YUM") for n in names(c)],
        ),
    )
    assert result.outcome is Outcome.INCORPORATED, result.violations
    after = {r[0]: r for r in logical_state(url)["currency"]}
    assert set(after) - set(before) == {currency_id("YUM")}
    assert all(after[i] == before[i] for i in before)


def test_two_databases_receiving_the_same_snapshots_end_in_the_same_state(
    ready: Callable[[], str],
) -> None:
    """RNF-1, CA-11."""
    first, second = ready(), ready()
    for url in (first, second):
        incorporate(url, build_snapshot(1))
        incorporate(url, transition())
    assert logical_state(first) == logical_state(second)


# --- deriva entre catálogos (S-8)


def test_a_country_retirement_in_countries_is_detected_and_must_be_fixed_by_the_next_snapshot(
    url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    incorporate(url, build_snapshot(1))
    env = {"REFERENCE_DATABASE_URL": url}

    def cli(*args: str) -> int:
        return main(
            list(args),
            environ=env,
            repository_factory=postgres_currency_repository,
            snapshot_reader=read_currency_snapshot,
            policy_loader=currency_required_locales,
        )

    assert cli("check-integrity") == 0
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "UPDATE reference.country SET status = 'inactive' WHERE country_id = %s",
            [country_id("AR")],
        )
    capsys.readouterr()
    assert cli("check-integrity") == 1
    assert "Country inactive" in capsys.readouterr().err
    stale = incorporate(url, build_snapshot(2))
    assert stale.outcome is Outcome.REJECTED and {v.rule for v in stale.violations} == {"RF-19"}
    fixed = build_snapshot(
        2,
        country_currencies=[
            association(a, c, f, D(2026, 1, 1) if a == "AR" else t)
            for a, c, f, t in DEFAULT_ASSOCIATIONS
        ],
    )
    assert incorporate(url, fixed).outcome is Outcome.INCORPORATED
    assert cli("check-integrity") == 0


def test_country_catalog_does_not_know_currency(url: str) -> None:
    """RNF-6, CA-24: retirar un país en 003 nunca es bloqueado ni observado por Currency."""
    incorporate(url, build_snapshot(1))
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "UPDATE reference.country SET status = 'inactive' WHERE country_id = %s",
            [country_id("HR")],
        )  # sin error: 003 puede retirar un país con asociaciones abiertas


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
    assert len(logical_state(url)["currency_snapshot"]) == 1


def test_incorporation_works_with_the_least_privileged_loader_role(url: str) -> None:
    """Todas las sentencias de escritura caben en los permisos de `reference_loader`."""
    loader = make_conninfo(url, options="-c role=reference_loader")
    for document in (build_snapshot(1), transition()):
        result = incorporate(loader, document)
        assert result.outcome is Outcome.INCORPORATED, result.violations
    renamed = transition(3)
    for item in renamed["currency_names"]:
        if item["currency_id"] == currency_id("ARS") and item["locale_id"] == EN:
            item["name"] = "Peso"
    assert incorporate(loader, seal(renamed)).outcome is Outcome.INCORPORATED


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
            repository_factory=postgres_currency_repository,
            snapshot_reader=read_currency_snapshot,
            policy_loader=currency_required_locales,
        )

    with NetworkGuard(monkeypatch) as guard:
        assert cli("diff", str(path)) == 0
        assert logical_state(url)["currency"] == []  # diff no escribe
        assert cli("incorporate", str(path)) == 0
        assert cli("incorporate", str(path)) == 0  # no-op
        assert cli("diff", str(path)) == 0
    assert not guard.blocked  # RNF-8: ningún acceso de red fuera de localhost
    out = capsys.readouterr()
    assert "INCORPORADO" in out.out and "NO-OP" in out.out
    password = str(conninfo_to_dict(url).get("password") or "<none>")
    assert password not in out.out + out.err
