"""T4: lector de snapshots; lee un archivo local y no accede a la red (RNF-2)."""

import ast
import copy
import json
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from gi_common_reference.locales.domain.errors import SchemaLoadError
from gi_common_reference.locales.domain.snapshot import content_digest_matches, iana_digest_matches
from gi_common_reference.locales.infrastructure import snapshot_reader
from gi_common_reference.locales.infrastructure.snapshot_reader import (
    SCHEMA_RESOURCE,
    SnapshotFormatError,
    load_snapshot_schema,
    read_snapshot_document,
)
from tests.fixtures import CONTRACTS, contract_json

EXAMPLE: Any = contract_json("locale-snapshot.v1.example.json")
NETWORK_MODULES = {"socket", "urllib", "http", "httpx", "requests", "ssl", "aiohttp", "ftplib"}


def write(path: Path, document: Any, **options: Any) -> Path:
    path.write_text(json.dumps(document, **options), encoding="utf-8")
    return path


def write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_reads_a_valid_local_file(tmp_path: Path) -> None:
    document = read_snapshot_document(write(tmp_path / "s.json", EXAMPLE))
    assert document == EXAMPLE


def test_reads_the_published_example() -> None:
    document = read_snapshot_document(CONTRACTS / "locale-snapshot.v1.example.json")
    assert content_digest_matches(document) and iana_digest_matches(document)


def test_formatting_and_key_order_do_not_change_the_recalculated_digest(tmp_path: Path) -> None:
    compact = write(tmp_path / "a.json", EXAMPLE, separators=(",", ":"))
    spread = write(tmp_path / "b.json", EXAMPLE, indent=8, sort_keys=True)
    for path in (compact, spread):
        document = read_snapshot_document(path)
        assert content_digest_matches(document)
        assert iana_digest_matches(document)


def test_non_ascii_content_survives_the_roundtrip(tmp_path: Path) -> None:
    document = copy.deepcopy(EXAMPLE)
    document["provenance"]["note"] = "ñandú ✓ 😀"
    path = tmp_path / "s.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    assert read_snapshot_document(path)["provenance"]["note"] == "ñandú ✓ 😀"


def test_incorrect_declared_digest_is_detected_after_reading(tmp_path: Path) -> None:
    document = copy.deepcopy(EXAMPLE)
    document["content_digest"] = "sha256:" + "0" * 64
    read = read_snapshot_document(write(tmp_path / "s.json", document))
    assert not content_digest_matches(read)


def test_schema_violations_are_reported_with_their_location(tmp_path: Path) -> None:
    document = copy.deepcopy(EXAMPLE)
    del document["iana"]["registry_text"]
    del document["locales"][0]["status"]
    with pytest.raises(SnapshotFormatError) as raised:
        read_snapshot_document(write(tmp_path / "s.json", document))
    joined = "\n".join(raised.value.errors)
    assert "iana" in joined and "registry_text" in joined
    assert "locales/0" in joined and "status" in joined


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    document = {k: v for k, v in EXAMPLE.items() if k != "iana"}
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(write(tmp_path / "s.json", document))


@pytest.mark.parametrize("text", ["", "{", "not json", "[]", '"x"', "null"])
def test_documents_that_are_not_a_json_object_are_rejected(tmp_path: Path, text: str) -> None:
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(write_text(tmp_path / "s.json", text))


def test_duplicate_keys_are_rejected(tmp_path: Path) -> None:
    text = json.dumps(EXAMPLE)[:-1] + ', "snapshot_version": 99}'
    with pytest.raises(SnapshotFormatError, match="duplicad"):
        read_snapshot_document(write_text(tmp_path / "s.json", text))


@pytest.mark.parametrize("literal", ["1.5", "1.0", "NaN", "Infinity", "1e3"])
def test_non_integer_numbers_are_rejected(tmp_path: Path, literal: str) -> None:
    text = json.dumps(EXAMPLE)[:-1] + ', "extra": ' + literal + "}"
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(write_text(tmp_path / "s.json", text))


def test_invalid_utf8_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_bytes(b'{"a": "\xff"}')
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(path)


def test_a_url_is_treated_as_a_local_path_and_never_fetched() -> None:
    with pytest.raises(OSError):
        read_snapshot_document(Path("https://example.com/snapshot.json"))


def test_reader_module_has_no_network_imports() -> None:
    tree = ast.parse(Path(snapshot_reader.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    assert not names & NETWORK_MODULES


# --- el schema viaja con el paquete y su fallo no se confunde con el del snapshot (M-1) ---------


def test_the_schema_is_loaded_from_the_package_resources() -> None:
    schema = load_snapshot_schema()
    assert schema["$id"] == "urn:gi:common-reference:locale-snapshot:v1"
    assert snapshot_reader.SCHEMA_PACKAGE == snapshot_reader.__name__.rpartition(".")[0]


def test_a_missing_schema_is_a_schema_load_error_not_an_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshot_reader, "SCHEMA_RESOURCE", "no-existe.schema.json")
    snapshot = write(tmp_path / "s.json", EXAMPLE)
    with pytest.raises(SchemaLoadError, match="no-existe.schema.json") as raised:
        read_snapshot_document(snapshot)
    assert not isinstance(raised.value, OSError | SnapshotFormatError)


@pytest.mark.parametrize(
    "content", ["", "{", "[]", '"x"', '{"type": 12}'], ids=["empty", "broken", "list", "str", "bad"]
)
def test_an_unusable_packaged_schema_is_a_schema_load_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    (tmp_path / SCHEMA_RESOURCE).write_text(content, encoding="utf-8")
    monkeypatch.setattr(resources, "files", lambda package: tmp_path)
    with pytest.raises(SchemaLoadError):
        load_snapshot_schema()


def test_a_schema_failure_does_not_depend_on_the_snapshot_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El entorno roto se informa igual aunque el archivo del snapshot tampoco exista."""
    monkeypatch.setattr(snapshot_reader, "SCHEMA_RESOURCE", "no-existe.schema.json")
    with pytest.raises(SchemaLoadError):
        read_snapshot_document(tmp_path / "tampoco-existe.json")


def test_an_unreadable_snapshot_file_is_an_os_error_and_not_a_schema_error(tmp_path: Path) -> None:
    with pytest.raises(OSError) as raised:
        read_snapshot_document(tmp_path / "no-existe.json")
    assert not isinstance(raised.value, SchemaLoadError)


def test_the_reader_does_not_look_for_the_schema_in_the_source_tree() -> None:
    source = Path(snapshot_reader.__file__).read_text(encoding="utf-8")
    assert "contracts" not in source.replace("`contracts/locale-snapshot.v1.schema.json`", "")
    assert "parents[" not in source
