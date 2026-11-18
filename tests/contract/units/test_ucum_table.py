"""RNF-7, D8: la tabla UCUM se redistribuye sin modificar y con aviso de licencia."""

import hashlib
import tomllib
from importlib import resources
from pathlib import Path

UCUM_SHA256 = "dfccea1b5dc284245ebae97edd1dc03c45864da4e87df55bc9851797b4fd0b61"
ROOT = Path(__file__).resolve().parents[3]
UCUM_DIR = ROOT / "src" / "gi_common_reference" / "units" / "infrastructure" / "ucum"


def test_the_packaged_ucum_essence_is_byte_for_byte_the_official_file() -> None:
    data = (UCUM_DIR / "ucum-essence.xml").read_bytes()
    assert hashlib.sha256(data).hexdigest() == UCUM_SHA256


def test_the_ucum_essence_is_reachable_as_a_package_resource() -> None:
    resource = (
        resources.files("gi_common_reference.units.infrastructure")
        .joinpath("ucum")
        .joinpath("ucum-essence.xml")
    )
    assert hashlib.sha256(resource.read_bytes()).hexdigest() == UCUM_SHA256


def test_the_notice_states_copyright_license_source_version_and_checksum() -> None:
    notice = (UCUM_DIR / "NOTICE.md").read_text(encoding="utf-8")
    for text in (
        "Copyright 1999-2024 Regenstrief Institute, Inc. All rights reserved.",
        "UCUM License, Version 1.1",
        "https://ucum.org/license",
        "https://unitsofmeasure.org/license",
        "AS IS",
        "https://raw.githubusercontent.com/ucum-org/ucum/main/ucum-essence.xml",
        "2.2",
        "2024-06-17",
        UCUM_SHA256,
    ):
        assert text in notice, text


def test_line_endings_of_the_ucum_essence_are_never_converted() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "src/gi_common_reference/units/infrastructure/ucum/ucum-essence.xml -text" in attributes


def test_the_ucum_files_travel_in_the_package_data() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    data = config["tool"]["setuptools"]["package-data"]["gi_common_reference.units.infrastructure"]
    assert "ucum/ucum-essence.xml" in data
    assert "ucum/NOTICE.md" in data
    assert "units-snapshot.v1.schema.json" in data
    assert "required-locales.v1.json" in data
