"""T3: el contrato publicado para PREP coincide con lo que el paquete usa (RF-27, RF-35)."""

import json
import tomllib
from importlib import resources
from pathlib import Path

from gi_common_reference.countries.domain.digest import content_digest_matches
from gi_common_reference.countries.infrastructure.policy_reader import (
    POLICY_PACKAGE,
    POLICY_RESOURCE,
)
from gi_common_reference.countries.infrastructure.snapshot_reader import (
    SCHEMA_PACKAGE,
    SCHEMA_RESOURCE,
    load_snapshot_schema,
    read_snapshot_document,
)
from tests.fixtures.countries import build_snapshot

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = ROOT / "contracts" / SCHEMA_RESOURCE
EXAMPLE = ROOT / "contracts" / "country-snapshot.v1.example.json"


def test_packaged_and_published_schemas_are_equivalent() -> None:
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    resource = resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_RESOURCE)
    assert json.loads(resource.read_text("utf-8")) == published
    assert load_snapshot_schema() == published


def test_the_published_example_is_valid_sealed_and_marked_as_non_production() -> None:
    document = read_snapshot_document(EXAMPLE)
    assert content_digest_matches(document)
    assert document["recodings"] == [] and document["code_reassignments"] == []
    assert {item["alpha2"] for item in document["countries"]} >= {"AR", "NA", "AQ", "TW"}
    assert all("sintético" in source["location"] for source in document["provenance"]["sources"])


def test_the_published_example_is_what_the_fixture_builder_produces() -> None:
    """Regenerar con `python -m tests.fixtures.countries` si cambia el builder."""
    assert json.loads(EXAMPLE.read_text(encoding="utf-8")) == build_snapshot()


def test_the_build_declares_the_schema_and_the_policy_as_package_data() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]
    assert POLICY_PACKAGE == SCHEMA_PACKAGE
    assert set(package_data[SCHEMA_PACKAGE]) == {SCHEMA_RESOURCE, POLICY_RESOURCE}
