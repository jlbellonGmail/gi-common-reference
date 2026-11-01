"""T3: el contrato publicado para PREP coincide con lo que el paquete usa (RF-21, RF-31)."""

import json
import tomllib
from importlib import resources
from pathlib import Path

from gi_common_reference.regions.domain.digest import content_digest_matches
from gi_common_reference.regions.infrastructure.policy_reader import (
    POLICY_PACKAGE,
    POLICY_RESOURCE,
)
from gi_common_reference.regions.infrastructure.snapshot_reader import (
    SCHEMA_PACKAGE,
    SCHEMA_RESOURCE,
    load_snapshot_schema,
    read_snapshot_document,
)

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = ROOT / "contracts" / SCHEMA_RESOURCE
EXAMPLE = ROOT / "contracts" / "region-snapshot.v1.example.json"


def test_packaged_and_published_schemas_are_equivalent() -> None:
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    resource = resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_RESOURCE)
    assert json.loads(resource.read_text("utf-8")) == published
    assert load_snapshot_schema() == published


def test_the_published_example_is_valid_and_sealed() -> None:
    document = read_snapshot_document(EXAMPLE)
    assert content_digest_matches(document)
    assert document["recodings"] == [] and document["code_reassignments"] == []
    assert {item["code"] for item in document["regions"]} == {"002", "019", "142"}


def test_the_build_declares_the_schema_and_the_policy_as_package_data() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]
    assert POLICY_PACKAGE == SCHEMA_PACKAGE
    assert set(package_data[SCHEMA_PACKAGE]) == {SCHEMA_RESOURCE, POLICY_RESOURCE}
