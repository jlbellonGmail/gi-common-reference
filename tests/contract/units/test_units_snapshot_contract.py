"""T3: el contrato publicado para PREP coincide con lo que el paquete usa (RF-41, RF-18)."""

import json
import tomllib
from importlib import resources
from pathlib import Path

from gi_common_reference.units.domain.digest import content_digest_matches
from gi_common_reference.units.infrastructure.policy_reader import (
    POLICY_PACKAGE,
    POLICY_RESOURCE,
)
from gi_common_reference.units.infrastructure.snapshot_reader import (
    SCHEMA_PACKAGE,
    SCHEMA_RESOURCE,
    load_snapshot_schema,
    read_snapshot_document,
)
from tests.fixtures.units import EN, ES, build_snapshot

ROOT = Path(__file__).resolve().parents[3]
PUBLISHED = ROOT / "contracts" / SCHEMA_RESOURCE
EXAMPLE = ROOT / "contracts" / "units-snapshot.v1.example.json"
CATALOG = {
    "mass": ["kg", "g", "mg", "t", "[lb_av]", "[oz_av]"],
    "length": ["m", "mm", "cm", "km", "[in_i]", "[ft_i]", "[mi_i]"],
    "area": ["m2", "cm2", "km2", "har"],
    "volume": ["m3", "cm3", "mL", "L", "[gal_us]"],
    "duration": ["s", "min", "h", "d", "wk"],
    "temperature": ["K", "Cel", "[degF]"],
    "temperature_difference": ["K", "Cel", "[degF]"],
    "speed": ["m/s", "km/h", "[mi_i]/h"],
    "density": ["kg/m3", "g/cm3", "kg/L"],
    "mass_concentration": ["kg/m3", "g/L", "mg/L"],
    "mass_per_area": ["kg/m2", "g/m2", "kg/har", "t/har"],
    "volume_per_area": ["m3/m2", "L/har", "mL/m2"],
    "count": ["{each}"],
    "dimensionless_ratio": ["1", "%", "[ppth]", "[ppm]"],
}


def test_packaged_and_published_schemas_are_equivalent() -> None:
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    resource = resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_RESOURCE)
    assert json.loads(resource.read_text("utf-8")) == published
    assert load_snapshot_schema() == published


def test_the_published_example_is_valid_sealed_and_marked_as_non_production() -> None:
    document = read_snapshot_document(EXAMPLE)
    assert content_digest_matches(document)
    sources = document["provenance"]["sources"]
    assert {s["role"] for s in sources} == {"definitions", "ucum", "names", "unece"}
    assert all("sintético" in s["name"] or "no productivo" in s["location"] for s in sources)
    ucum = next(s for s in sources if s["role"] == "ucum")
    assert ucum["checksum"].endswith(
        "dfccea1b5dc284245ebae97edd1dc03c45864da4e87df55bc9851797b4fd0b61"
    )
    assert ucum["license"] == "UCUM License v1.1"
    assert document["provenance"]["unresolved_conflicts"] == []


def test_the_published_example_is_what_the_fixture_builder_produces() -> None:
    """Regenerar con `python -m tests.fixtures.units` si cambia el builder."""
    assert json.loads(EXAMPLE.read_text(encoding="utf-8")) == build_snapshot()


def test_the_example_is_the_initial_catalog_of_s6() -> None:
    document = read_snapshot_document(EXAMPLE)
    codes = {u["unit_id"]: u["ucum_code"] for u in document["units"]}
    by_kind: dict[str, list[str]] = {}
    for kind in document["quantity_kinds"]:
        members = [
            codes[a["unit_id"]]
            for a in document["quantity_kind_units"]
            if a["quantity_kind_id"] == kind["quantity_kind_id"]
        ]
        by_kind[kind["code"]] = members
        assert codes[kind["reference_unit_id"]] == members[0]
    assert by_kind == CATALOG


def test_the_example_references_are_neutral_and_affine_is_only_temperature() -> None:
    document = read_snapshot_document(EXAMPLE)
    kinds = {k["quantity_kind_id"]: k for k in document["quantity_kinds"]}
    for kind in kinds.values():
        reference = next(
            a
            for a in document["quantity_kind_units"]
            if a["quantity_kind_id"] == kind["quantity_kind_id"]
            and a["unit_id"] == kind["reference_unit_id"]
        )
        assert (reference["factor"], reference["offset"]) == ("1", "0")
    affine = {k["code"] for k in kinds.values() if k["conversion_type"] == "affine"}
    assert affine == {"temperature"}
    for association in document["quantity_kind_units"]:
        if kinds[association["quantity_kind_id"]]["conversion_type"] == "linear":
            assert association["offset"] == "0"


def test_the_example_shares_unit_identities_across_kinds() -> None:
    """D-8, CL-1: °C es una unidad con dos asociaciones; kg/m³ es referencia de dos magnitudes."""
    document = read_snapshot_document(EXAMPLE)
    ids = [u["unit_id"] for u in document["units"]]
    assert len(set(ids)) == len(ids)
    by_ucum = {u["ucum_code"]: u["unit_id"] for u in document["units"]}
    uses = [a for a in document["quantity_kind_units"] if a["unit_id"] == by_ucum["Cel"]]
    assert len(uses) == 2
    refs = [k for k in document["quantity_kinds"] if k["reference_unit_id"] == by_ucum["kg/m3"]]
    assert len(refs) == 2


def test_the_example_carries_en_and_es_names_for_every_kind_and_unit() -> None:
    document = read_snapshot_document(EXAMPLE)
    kinds = {k["quantity_kind_id"] for k in document["quantity_kinds"]}
    units = {u["unit_id"] for u in document["units"]}
    assert {(n["quantity_kind_id"], n["locale_id"]) for n in document["quantity_kind_names"]} == {
        (k, loc) for k in kinds for loc in (EN, ES)
    }
    assert {(n["unit_id"], n["locale_id"]) for n in document["unit_names"]} == {
        (u, loc) for u in units for loc in (EN, ES)
    }


def test_the_example_uses_exact_text_factors_and_codes() -> None:
    document = read_snapshot_document(EXAMPLE)
    factors = {a["factor"] for a in document["quantity_kind_units"]}
    assert {"5/9", "5/18", "0.45359237", "0.028349523125", "0.003785411784"} <= factors
    assert all(isinstance(f, str) for f in factors)
    unece = {u["unece_code"] for u in document["units"]}
    assert {None, "KGM", "23", "28", "59", "C62", "H87", "HM"} <= unece


def test_the_build_declares_the_schema_policy_and_ucum_table_as_package_data() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]
    assert POLICY_PACKAGE == SCHEMA_PACKAGE
    assert set(package_data[SCHEMA_PACKAGE]) == {
        SCHEMA_RESOURCE,
        POLICY_RESOURCE,
        "ucum/ucum-essence.xml",
        "ucum/NOTICE.md",
    }


def test_the_schema_text_is_identical_byte_for_byte_between_both_copies() -> None:
    packaged = resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_RESOURCE).read_bytes()
    assert packaged.replace(b"\r\n", b"\n") == PUBLISHED.read_bytes().replace(b"\r\n", b"\n")
