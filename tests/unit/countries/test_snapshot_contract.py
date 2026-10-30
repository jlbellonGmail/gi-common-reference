"""T3: contrato del snapshot de Countries (RF-5, RF-27, RF-28): schema, digest y lector."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from gi_common_reference.countries.domain.digest import (
    CanonicalizationError,
    canonical_json,
    content_digest,
    content_digest_matches,
)
from gi_common_reference.countries.infrastructure.snapshot_reader import (
    SnapshotFormatError,
    load_snapshot_schema,
    read_snapshot_document,
)
from tests.fixtures.countries import (
    build_snapshot,
    country,
    names,
    reassignment,
    recoding,
)

ROOT = Path(__file__).resolve().parents[3]
LOCALE_VECTORS = ROOT / "contracts" / "locale-snapshot.v1.vectors.json"
REQUIRED = [
    "snapshot_version",
    "content_digest",
    "region_snapshot_version",
    "provenance",
    "countries",
    "country_names",
    "flags",
    "flag_exceptions",
    "recodings",
    "code_reassignments",
]


def write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def full_snapshot() -> dict[str, Any]:
    """Un documento con todas las colecciones pobladas, incluidas las declaraciones."""
    return build_snapshot(
        2,
        recodings=[recoding("TL", ("TP", "TMP", "626"), ("TL", "TLS", "626"))],
        code_reassignments=[reassignment("AR", "alpha2", "XX")],
    )


# --- digest -------------------------------------------------------------------------------------


def test_canonical_json_reproduces_the_published_locale_vectors() -> None:
    """D2, D16: una sola regla de digest para PREP en todos los catálogos."""
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
    tampered["countries"][0]["status"] = "inactive"
    assert content_digest_matches(document)
    assert not content_digest_matches(tampered)
    assert not content_digest_matches({**document, "content_digest": 3})
    assert not content_digest_matches({**document, "snapshot_version": 1.5})


def test_the_digest_covers_the_codes_exactly_as_text() -> None:
    """`004` y `4` no producen el mismo digest: no hay coerción numérica."""
    first = build_snapshot(countries=[country("AR", numeric_code="004")], keys=("AR",))
    second = build_snapshot(countries=[country("AR", numeric_code="4")], keys=("AR",))
    assert first["content_digest"] != second["content_digest"]


# --- schema y lector ----------------------------------------------------------------------------


def test_a_complete_snapshot_with_declarations_is_read(tmp_path: Path) -> None:
    document = full_snapshot()
    assert read_snapshot_document(write(tmp_path, document)) == document


def test_na_and_leading_zero_codes_and_null_optionals_are_accepted(tmp_path: Path) -> None:
    """CL-2–CL-6: Namibia, `004`, sin región ni código de llamada."""
    document = build_snapshot(
        keys=("NA", "AQ"),
        countries=[
            country("NA"),
            country("AQ", numeric_code="004", region_id=None, subregion_id=None, calling_code=None),
        ],
    )
    read = read_snapshot_document(write(tmp_path, document))
    assert read["countries"][0]["alpha2"] == "NA"
    assert read["countries"][1]["numeric_code"] == "004"
    assert read["countries"][1]["calling_code"] is None


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
        ("countries", "country_id"),
        ("countries", "alpha2"),
        ("countries", "alpha3"),
        ("countries", "numeric_code"),
        ("countries", "region_id"),
        ("countries", "subregion_id"),
        ("countries", "calling_code"),
        ("countries", "status"),
        ("countries", "replacement_country_id"),
        ("country_names", "country_id"),
        ("country_names", "locale_id"),
        ("country_names", "name"),
        ("country_names", "official_name"),
        ("flags", "country_id"),
        ("flags", "asset_path"),
        ("flags", "sha256"),
        ("flags", "media_type"),
        ("flags", "source"),
        ("flag_exceptions", "country_id"),
        ("flag_exceptions", "reason"),
        ("recodings", "country_id"),
        ("recodings", "previous"),
        ("recodings", "new"),
        ("recodings", "provenance"),
        ("code_reassignments", "country_id"),
        ("code_reassignments", "code_kind"),
        ("code_reassignments", "code"),
        ("code_reassignments", "provenance"),
    ],
)
def test_each_required_item_field_is_enforced(tmp_path: Path, collection: str, field: str) -> None:
    document = full_snapshot()
    del document[collection][0][field]
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(write(tmp_path, document))


@pytest.mark.parametrize("field", ["alpha2", "alpha3", "numeric_code"])
def test_each_component_of_the_triple_is_required_in_a_recoding(tmp_path: Path, field: str) -> None:
    for side in ("previous", "new"):
        document = full_snapshot()
        del document["recodings"][0][side][field]
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
        (["countries", 0, "name"], "Argentina"),
        (["countries", 0, "region_name"], "Americas"),
        (["countries", 0, "is_active"], True),
        (["countries", 0, "status"], "deprecated"),
        (["countries", 0, "numeric_code"], 32),
        (["countries", 0, "numeric_code"], 4),
        (["countries", 0, "numeric_code"], "4"),
        (["countries", 0, "numeric_code"], "0032"),
        (["countries", 0, "numeric_code"], None),
        (["countries", 0, "alpha2"], "ar"),
        (["countries", 0, "alpha2"], None),
        (["countries", 0, "alpha2"], "A"),
        (["countries", 0, "alpha3"], "ar1"),
        (["countries", 0, "calling_code"], "+54"),
        (["countries", 0, "calling_code"], "054"),
        (["countries", 0, "calling_code"], 54),
        (["country_names", 0, "locale"], "es"),
        (["country_names", 0, "name"], None),
        (["flags", 0, "media_type"], "image/png"),
        (["flags", 0, "sha256"], "abc"),
        (["flags", 0, "source"], "licencia"),
        (["recodings", 0, "previous"], None),
        (["recodings", 0, "new"], None),
        (["recodings", 0, "previous", "alpha2"], None),
        (["recodings", 0, "new", "numeric_code"], 626),
        (["recodings", 0, "previous", "extra"], "x"),
        (["recodings", 0, "provenance"], {"source": ""}),
        (["code_reassignments", 0, "provenance"], {}),
        (["code_reassignments", 0, "code_kind"], "alpha4"),
        (["code_reassignments", 0, "code"], "xx"),
        (["code_reassignments", 0, "code_kind"], "numeric_code"),
        (["snapshot_version"], 0),
        (["region_snapshot_version"], 0),
        (["content_digest"], "sha256:xyz"),
        (["provenance", "sources"], "ISO"),
        (["provenance", "unresolved_conflicts"], None),
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
        '{"countries": [{"numeric_code": 4.0}]}',
    ],
)
def test_malformed_json_is_a_format_error(tmp_path: Path, text: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(path)


def test_a_duplicate_key_inside_a_country_is_a_format_error(tmp_path: Path) -> None:
    text = json.dumps(full_snapshot(), ensure_ascii=False).replace(
        '"alpha2": "AR"', '"alpha2": "AR", "alpha2": "XX"', 1
    )
    path = tmp_path / "dup.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SnapshotFormatError) as error:
        read_snapshot_document(path)
    assert "duplicada" in str(error.value)


def test_an_unreadable_file_is_an_os_error(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        read_snapshot_document(tmp_path / "missing.json")


def test_the_schema_loads_and_is_draft_2020_12() -> None:
    schema = load_snapshot_schema()
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["required"] == REQUIRED


def test_the_fixture_names_cover_the_required_locales_with_optional_official_names() -> None:
    items = names("CA")
    assert len(items) == 2 and all(item["official_name"] is None for item in items)
