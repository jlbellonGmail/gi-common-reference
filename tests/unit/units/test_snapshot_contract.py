"""T3: contrato del snapshot de Units (RF-41, RF-42): schema, digest y lector."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from gi_common_reference.units.domain.digest import (
    CanonicalizationError,
    canonical_json,
    content_digest,
    content_digest_matches,
)
from gi_common_reference.units.infrastructure.snapshot_reader import (
    SnapshotFormatError,
    load_snapshot_schema,
    read_snapshot_document,
)
from tests.fixtures.units import build_snapshot, kind_id, seal, unit, unit_id

ROOT = Path(__file__).resolve().parents[3]
LOCALE_VECTORS = ROOT / "contracts" / "locale-snapshot.v1.vectors.json"
REQUIRED = [
    "snapshot_version",
    "content_digest",
    "provenance",
    "quantity_kinds",
    "units",
    "quantity_kind_units",
    "quantity_kind_names",
    "unit_names",
]


def write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


# --- digest -------------------------------------------------------------------------------------


def test_canonical_json_reproduces_the_published_locale_vectors() -> None:
    """D17: una sola regla de digest para PREP en todos los catálogos."""
    vectors = json.loads(LOCALE_VECTORS.read_text(encoding="utf-8"))
    assert vectors["content_digest"]
    for vector in vectors["content_digest"]:
        body = {k: v for k, v in vector["document"].items() if k != "content_digest"}
        assert canonical_json(body).decode("utf-8") == vector["canonical"], vector["name"]
        assert content_digest(vector["document"]) == vector["digest"], vector["name"]


def test_canonical_json_rejects_what_the_locale_vectors_reject() -> None:
    vectors = json.loads(LOCALE_VECTORS.read_text(encoding="utf-8"))
    assert vectors["errors"]
    for vector in vectors["errors"]:
        document = vector["document"] if "document" in vector else json.loads(vector["jsonText"])
        with pytest.raises(CanonicalizationError):
            content_digest(document)


def test_the_digest_ignores_key_order_and_whitespace(tmp_path: Path) -> None:
    document = build_snapshot()
    reordered = json.loads(json.dumps(dict(reversed(list(document.items())))))
    assert content_digest(reordered) == document["content_digest"]
    path = tmp_path / "pretty.json"
    path.write_text(json.dumps(document, indent=4, ensure_ascii=False), encoding="utf-8")
    assert content_digest_matches(read_snapshot_document(path))


def test_a_wrong_declared_digest_is_detected() -> None:
    document = build_snapshot()
    tampered = copy.deepcopy(document)
    tampered["quantity_kinds"][0]["status"] = "inactive"
    assert content_digest_matches(document)
    assert not content_digest_matches(tampered)
    assert not content_digest_matches({**document, "content_digest": 3})
    assert not content_digest_matches({**document, "snapshot_version": 1.5})


def test_the_digest_distinguishes_text_that_a_number_would_conflate() -> None:
    """RF-13: `0.5` y `0.50` (o `1/2`) son textos distintos; no hay coerción numérica."""
    first = copy.deepcopy(build_snapshot())
    second = copy.deepcopy(first)
    first["quantity_kind_units"][1]["factor"] = "0.5"
    second["quantity_kind_units"][1]["factor"] = "0.50"
    assert seal(first)["content_digest"] != seal(second)["content_digest"]


# --- schema y lector ----------------------------------------------------------------------------


def test_the_default_snapshot_is_read_unchanged(tmp_path: Path) -> None:
    document = build_snapshot()
    assert read_snapshot_document(write(tmp_path, document)) == document


def test_optional_codes_present_as_null_and_exact_strings_are_accepted(tmp_path: Path) -> None:
    read = read_snapshot_document(write(tmp_path, build_snapshot()))
    by_ucum = {item["ucum_code"]: item for item in read["units"]}
    assert by_ucum["har"]["unece_code"] is None
    assert by_ucum["[ppm]"]["unece_code"] == "59"
    assert by_ucum["kg/m3"]["unece_code"] == "KMQ"
    factors = {(i["quantity_kind_id"], i["unit_id"]): i for i in read["quantity_kind_units"]}
    degf = factors[(kind_id("temperature"), unit_id("degF"))]
    assert (degf["factor"], degf["offset"]) == ("5/9", "459.67")
    cel_difference = factors[(kind_id("temperature_difference"), unit_id("Cel"))]
    assert (cel_difference["factor"], cel_difference["offset"]) == ("1", "0")


@pytest.mark.parametrize("field", REQUIRED)
def test_each_required_field_is_enforced(tmp_path: Path, field: str) -> None:
    document = build_snapshot()
    del document[field]
    with pytest.raises(SnapshotFormatError) as error:
        read_snapshot_document(write(tmp_path, document))
    assert any(field in problem for problem in error.value.errors)


@pytest.mark.parametrize(
    ("collection", "field"),
    [
        ("quantity_kinds", "quantity_kind_id"),
        ("quantity_kinds", "code"),
        ("quantity_kinds", "conversion_type"),
        ("quantity_kinds", "reference_unit_id"),
        ("quantity_kinds", "status"),
        ("units", "unit_id"),
        ("units", "ucum_code"),
        ("units", "unece_code"),
        ("units", "symbol"),
        ("units", "status"),
        ("quantity_kind_units", "quantity_kind_id"),
        ("quantity_kind_units", "unit_id"),
        ("quantity_kind_units", "factor"),
        ("quantity_kind_units", "offset"),
        ("quantity_kind_units", "status"),
        ("quantity_kind_names", "quantity_kind_id"),
        ("quantity_kind_names", "locale_id"),
        ("quantity_kind_names", "name"),
        ("unit_names", "unit_id"),
        ("unit_names", "locale_id"),
        ("unit_names", "name"),
        ("unit_names", "plural"),
    ],
)
def test_each_required_item_field_is_enforced(tmp_path: Path, collection: str, field: str) -> None:
    document = build_snapshot()
    del document[collection][0][field]
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(write(tmp_path, document))


def _mutated(path: list[Any], value: Any) -> dict[str, Any]:
    document = build_snapshot()
    target: Any = document
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return document


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["tenant_id"], "x"),
        (["organization_id"], "x"),
        (["extra"], 1),
        (["quantity_kinds", 0, "tenant_id"], "x"),
        (["quantity_kinds", 0, "name"], "Mass"),
        (["quantity_kinds", 0, "is_reference"], True),
        (["quantity_kinds", 0, "status"], "deprecated"),
        (["quantity_kinds", 0, "status"], "not_found"),
        (["quantity_kinds", 0, "conversion_type"], "logarithmic"),
        (["quantity_kinds", 0, "conversion_type"], None),
        (["quantity_kinds", 0, "code"], "Mass"),
        (["quantity_kinds", 0, "code"], "m"),
        (["quantity_kinds", 0, "code"], "1mass"),
        (["quantity_kinds", 0, "code"], None),
        (["quantity_kinds", 0, "reference_unit_id"], None),
        (["units", 0, "name"], "kilogram"),
        (["units", 0, "dimension"], "M"),
        (["units", 0, "ucum_code"], 1),
        (["units", 0, "ucum_code"], ""),
        (["units", 0, "unece_code"], "kgm"),
        (["units", 0, "unece_code"], "K"),
        (["units", 0, "unece_code"], "KGMX"),
        (["units", 0, "unece_code"], 12),
        (["units", 0, "symbol"], ""),
        (["units", 0, "symbol"], None),
        (["units", 0, "status"], "active "),
        (["quantity_kind_units", 0, "factor"], 1),
        (["quantity_kind_units", 0, "factor"], 1.5),
        (["quantity_kind_units", 0, "factor"], None),
        (["quantity_kind_units", 0, "factor"], ""),
        (["quantity_kind_units", 0, "offset"], 0),
        (["quantity_kind_units", 0, "offset"], 273.15),
        (["quantity_kind_units", 0, "offset"], None),
        (["quantity_kind_units", 0, "ratio"], "1"),
        (["quantity_kind_units", 0, "is_reference"], True),
        (["quantity_kind_units", 0, "status"], "vigente"),
        (["quantity_kind_names", 0, "plural"], "masses"),
        (["quantity_kind_names", 0, "name"], None),
        (["quantity_kind_names", 0, "name"], 5),
        (["unit_names", 0, "plural"], 5),
        (["unit_names", 0, "name"], None),
        (["unit_names", 0, "symbol"], "x"),
        (["snapshot_version"], 0),
        (["snapshot_version"], -1),
        (["snapshot_version"], "1"),
        (["snapshot_version"], True),
        (["content_digest"], "sha256:abc"),
        (["content_digest"], "SHA256:" + "a" * 64),
        (["provenance", "sources", 0, "role"], "classification"),
        (["provenance", "sources", 0, "role"], "identity"),
        (["provenance", "unresolved_conflicts"], "none"),
    ],
)
def test_malformed_values_and_extra_fields_are_rejected(
    tmp_path: Path, path: list[Any], value: Any
) -> None:
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(write(tmp_path, _mutated(path, value)))


def test_a_null_plural_is_accepted_and_a_null_unece_is_accepted(tmp_path: Path) -> None:
    document = build_snapshot()
    document["unit_names"][0]["plural"] = None
    document["units"][0]["unece_code"] = None
    document["units"][0]["ucum_code"] = None
    assert read_snapshot_document(write(tmp_path, document)) == document


def test_a_json_number_for_a_factor_or_offset_is_rejected_by_the_reader(tmp_path: Path) -> None:
    text = json.dumps(build_snapshot(), ensure_ascii=False)
    for broken in (
        text.replace('"factor": "0.001"', '"factor": 0.001', 1),
        text.replace('"factor": "1000"', '"factor": 1000', 1),
        text.replace('"offset": "273.15"', '"offset": 273.15', 1),
    ):
        assert broken != text
        path = tmp_path / "broken.json"
        path.write_text(broken, encoding="utf-8")
        with pytest.raises(SnapshotFormatError):
            read_snapshot_document(path)


def test_a_float_a_nan_and_a_duplicate_key_are_rejected_by_the_reader(tmp_path: Path) -> None:
    text = json.dumps(build_snapshot(), ensure_ascii=False)
    for broken in (
        text.replace('"snapshot_version": 1', '"snapshot_version": 1.5', 1),
        text.replace('"snapshot_version": 1', '"snapshot_version": 1.0', 1),
        text.replace('"snapshot_version": 1', '"snapshot_version": 1e0', 1),
        text.replace('"snapshot_version": 1', '"snapshot_version": NaN', 1),
        text.replace('{"snapshot_version": 1', '{"snapshot_version": 1, "snapshot_version": 2', 1),
        text.replace('"factor": "1"', '"factor": "1", "factor": "2"', 1),
    ):
        assert broken != text
        path = tmp_path / "broken.json"
        path.write_text(broken, encoding="utf-8")
        with pytest.raises(SnapshotFormatError):
            read_snapshot_document(path)


def test_non_json_and_non_object_documents_are_rejected(tmp_path: Path) -> None:
    for content in ("", "{", "[]", "null", '"x"', "﻿{}"):
        path = tmp_path / "bad.json"
        path.write_text(content, encoding="utf-8")
        with pytest.raises(SnapshotFormatError):
            read_snapshot_document(path)
    path = tmp_path / "binary.json"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(path)


def _all_property_names(node: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            names |= set(props)
        for value in node.values():
            names |= _all_property_names(value)
    elif isinstance(node, list):
        for item in node:
            names |= _all_property_names(item)
    return names


def test_the_schema_does_not_model_what_is_out_of_scope() -> None:
    """RF-1, RF-9, RF-40: ni tenant, ni formato, ni dimensiones, ni banderas de referencia."""
    properties = _all_property_names(load_snapshot_schema())
    for forbidden in (
        "tenant_id",
        "organization_id",
        "mask",
        "format",
        "dimension",
        "is_reference",
        "is_active",
        "ratio",
        "symbol_localized",
    ):
        assert forbidden not in properties, forbidden
    assert "tenant" not in json.dumps(load_snapshot_schema())


def test_the_schema_declares_every_collection_as_closed_objects() -> None:
    schema = load_snapshot_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(REQUIRED)
    for collection in (
        "quantity_kinds",
        "units",
        "quantity_kind_units",
        "quantity_kind_names",
        "unit_names",
    ):
        item = schema["properties"][collection]["items"]
        assert item["additionalProperties"] is False, collection
        assert set(item["required"]) == set(item["properties"]), collection


def test_ids_are_stable_and_independent_from_the_codes() -> None:
    """RF-2: el id de prueba no se deriva del contenido del snapshot."""
    assert unit("kg")["unit_id"] == unit_id("kg")
    renamed = unit("kg", ucum_code="kg2")
    assert renamed["unit_id"] == unit("kg")["unit_id"]
