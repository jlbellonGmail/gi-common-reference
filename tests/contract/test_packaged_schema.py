"""M-1: el schema del snapshot viaja dentro del paquete y coincide con la copia publicada."""

import json
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any

from gi_common_reference.locales.infrastructure.snapshot_reader import (
    SCHEMA_PACKAGE,
    SCHEMA_RESOURCE,
    load_snapshot_schema,
)

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = ROOT / "contracts" / SCHEMA_RESOURCE


def _names(requirements: list[str]) -> set[str]:
    return {name.split("[")[0].split(">")[0].split("=")[0].lower() for name in requirements}


def test_packaged_and_published_schemas_are_equivalent() -> None:
    resource = resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_RESOURCE)
    packaged = json.loads(resource.read_text("utf-8"))
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    assert packaged == published


def test_the_loader_returns_the_packaged_schema() -> None:
    assert load_snapshot_schema() == json.loads(PUBLISHED.read_text(encoding="utf-8"))


def test_the_packaged_schema_lives_in_the_source_package_not_in_contracts() -> None:
    resource = resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_RESOURCE)
    assert resource.is_file()
    assert "contracts" not in Path(str(resource)).parts


def test_the_build_declares_the_schema_as_package_data() -> None:
    pyproject: dict[str, Any] = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]
    assert SCHEMA_RESOURCE in package_data[SCHEMA_PACKAGE]


def test_dependencies_imported_directly_are_declared() -> None:
    """L-7: lo que el código importa directamente no puede ser solo una dependencia transitiva."""
    pyproject: dict[str, Any] = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    declared = _names(pyproject["project"]["dependencies"])
    assert {"fastapi", "pydantic", "sqlalchemy", "alembic", "psycopg", "jsonschema"} <= declared
    assert "setuptools" in _names(pyproject["project"]["optional-dependencies"]["dev"])


def test_both_copies_document_the_rule_for_empty_deprecated_and_preferred_value() -> None:
    """T9 (RF-33): el contrato para PREP dice que esos campos no pueden estar vacíos."""
    packaged = json.loads(
        resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_RESOURCE).read_text("utf-8")
    )
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    for schema in (packaged, published):
        text = schema["properties"]["iana"]["properties"]["registry_text"]["description"]
        assert "Deprecated" in text and "Preferred-Value" in text
        assert "no pueden estar vacíos" in text and "RF-33" in text
