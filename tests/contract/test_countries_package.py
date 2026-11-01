"""T1: el directorio de assets de bandera es un paquete y viaja en el wheel (RF-19, RF-50)."""

import importlib
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = "gi_common_reference.countries.assets"


def test_the_assets_package_is_importable_and_documents_its_contract() -> None:
    package = importlib.import_module(ASSETS)
    readme = Path(package.__file__ or "").parent / "flags" / "README.md"
    assert readme.is_file()
    text = readme.read_text(encoding="utf-8")
    assert "sha256" in text and "image/svg+xml" in text


def test_pyproject_ships_flags_and_the_catalog_resources() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = config["tool"]["setuptools"]["package-data"]
    assert package_data[ASSETS] == ["flags/*"]
    infrastructure = package_data["gi_common_reference.countries.infrastructure"]
    assert {"country-snapshot.v1.schema.json", "required-locales.v1.json"} <= set(infrastructure)
