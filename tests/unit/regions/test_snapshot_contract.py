"""T3: contrato del snapshot de Regions (RF-21, RF-37, RF-39): schema, digest y lector."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from gi_common_reference.regions.domain.digest import (
    CanonicalizationError,
    canonical_json,
    content_digest,
    content_digest_matches,
)
from gi_common_reference.regions.infrastructure.snapshot_reader import (
    SnapshotFormatError,
    load_snapshot_schema,
    read_snapshot_document,
)
from tests.fixtures.regions import build_snapshot, reassignment, recoding

ROOT = Path(__file__).resolve().parents[3]
LOCALE_VECTORS = ROOT / "contracts" / "locale-snapshot.v1.vectors.json"
REQUIRED = [
    "snapshot_version",
    "content_digest",
    "provenance",
    "regions",
    "subregions",
    "region_names",
    "subregion_names",
    "recodings",
    "code_reassignments",
]


def write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def full_snapshot() -> dict[str, Any]:
    return build_snapshot(
        2,
        recodings=[recoding("subregion", "419", "419", "420")],
        code_reassignments=[reassignment("subregion", "419", "420")],
    )


# --- digest -------------------------------------------------------------------------------------


def test_canonical_json_reproduces_the_published_locale_vectors() -> None:
    """D3, D12: una sola regla de digest para PREP en ambos catálogos."""
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
    path.write_text(json.dumps(document, indent=4), encoding="utf-8")
    assert content_digest_matches(read_snapshot_document(path))


def test_a_wrong_declared_digest_is_detected() -> None:
    document = build_snapshot()
    tampered = copy.deepcopy(document)
    tampered["regions"][0]["status"] = "inactive"
    assert content_digest_matches(document)
    assert not content_digest_matches(tampered)
    assert not content_digest_matches({**document, "content_digest": 3})
    assert not content_digest_matches({**document, "snapshot_version": 1.5})


# --- schema y lector ----------------------------------------------------------------------------


def test_a_complete_snapshot_with_declarations_is_read(tmp_path: Path) -> None:
    document = full_snapshot()
    assert read_snapshot_document(write(tmp_path, document)) == document


@pytest.mark.parametrize("field", REQUIRED)
def test_each_required_field_is_enforced(tmp_path: Path, field: str) -> None:
    document = full_snapshot()
    del document[field]
    with pytest.raises(SnapshotFormatError) as error:
        read_snapshot_document(write(tmp_path, document))
    assert any(field in problem for problem in error.value.errors)


@pytest.mark.parametrize(
    ("collection", "field"),
    [
        ("regions", "region_id"),
        ("regions", "code"),
        ("regions", "status"),
        ("regions", "replacement_region_id"),
        ("subregions", "region_id"),
        ("subregions", "replacement_subregion_id"),
        ("region_names", "locale_id"),
        ("subregion_names", "name"),
        ("recodings", "previous_code"),
        ("recodings", "new_code"),
        ("recodings", "provenance"),
        ("code_reassignments", "code"),
        ("code_reassignments", "provenance"),
    ],
)
def test_each_required_item_field_is_enforced(tmp_path: Path, collection: str, field: str) -> None:
    document = full_snapshot()
    del document[collection][0][field]
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(write(tmp_path, document))


def _mutated(path: list[Any], value: Any) -> dict[str, Any]:
    document = full_snapshot()
    target: Any = document
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return document


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["tenant_id"], "x"),
        (["regions", 0, "name"], "Africa"),
        (["subregions", 0, "status"], "deprecated"),
        (["recodings", 0, "entity_type"], "country"),
        (["recodings", 0, "previous_code"], None),
        (["recodings", 0, "new_code"], None),
        (["recodings", 0, "provenance"], {"source": ""}),
        (["code_reassignments", 0, "provenance"], {}),
        (["snapshot_version"], 0),
        (["regions", 0, "code"], 19),
    ],
)
def test_unknown_fields_and_wrong_types_are_rejected(
    tmp_path: Path, path: list[Any], value: Any
) -> None:
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(write(tmp_path, _mutated(path, value)))


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        '{"snapshot_version": 1, "snapshot_version": 2}',
        '{"snapshot_version": 1.0}',
        '{"snapshot_version": NaN}',
    ],
)
def test_malformed_json_is_a_format_error(tmp_path: Path, text: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(path)


def test_an_unreadable_file_is_an_os_error(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        read_snapshot_document(tmp_path / "missing.json")


def test_the_schema_loads_and_is_draft_2020_12() -> None:
    schema = load_snapshot_schema()
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["required"] == REQUIRED
