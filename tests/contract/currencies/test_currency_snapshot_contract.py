"""T3: el contrato publicado para PREP coincide con lo que el paquete usa (RF-41, RF-13)."""

import json
import tomllib
from importlib import resources
from pathlib import Path

from gi_common_reference.currencies.domain.digest import content_digest_matches
from gi_common_reference.currencies.infrastructure.policy_reader import (
    POLICY_PACKAGE,
    POLICY_RESOURCE,
)
from gi_common_reference.currencies.infrastructure.snapshot_reader import (
    SCHEMA_PACKAGE,
    SCHEMA_RESOURCE,
    load_snapshot_schema,
    read_snapshot_document,
)
from tests.fixtures.currencies import build_snapshot

ROOT = Path(__file__).resolve().parents[3]
PUBLISHED = ROOT / "contracts" / SCHEMA_RESOURCE
EXAMPLE = ROOT / "contracts" / "currency-snapshot.v1.example.json"


def test_packaged_and_published_schemas_are_equivalent() -> None:
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    resource = resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_RESOURCE)
    assert json.loads(resource.read_text("utf-8")) == published
    assert load_snapshot_schema() == published


def test_the_published_example_is_valid_sealed_and_marked_as_non_production() -> None:
    document = read_snapshot_document(EXAMPLE)
    assert content_digest_matches(document)
    codes = {item["alphabetic_code"] for item in document["currencies"]}
    assert codes >= {"ARS", "USD", "EUR", "XAU", "HRK"}
    assert all("sintético" in source["location"] for source in document["provenance"]["sources"])
    assert {s["role"] for s in document["provenance"]["sources"]} == {
        "identity",
        "names",
        "country_currency",
        "validity",
    }
    assert document["provenance"]["unresolved_conflicts"] == []


def test_the_published_example_is_what_the_fixture_builder_produces() -> None:
    """Regenerar con `python -m tests.fixtures.currencies` si cambia el builder."""
    assert json.loads(EXAMPLE.read_text(encoding="utf-8")) == build_snapshot()


def test_the_build_declares_the_schema_and_the_policy_as_package_data() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]
    assert POLICY_PACKAGE == SCHEMA_PACKAGE
    assert set(package_data[SCHEMA_PACKAGE]) == {SCHEMA_RESOURCE, POLICY_RESOURCE}


def test_the_example_carries_ids_and_the_required_names_for_every_currency() -> None:
    document = read_snapshot_document(EXAMPLE)
    ids = [item["currency_id"] for item in document["currencies"]]
    assert len(set(ids)) == len(ids)
    locales_by_currency: dict[str, set[str]] = {}
    for item in document["currency_names"]:
        locales_by_currency.setdefault(item["currency_id"], set()).add(item["locale_id"])
    assert all(len(locales_by_currency[i]) == 2 for i in ids)
