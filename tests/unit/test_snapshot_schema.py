"""T4: el JSON Schema del snapshot rechaza la falta de cada campo obligatorio (RF-31, RF-30)."""

import copy
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.fixtures import contract_json

SCHEMA: Any = contract_json("locale-snapshot.v1.schema.json")
EXAMPLE: Any = contract_json("locale-snapshot.v1.example.json")
VALIDATOR = Draft202012Validator(SCHEMA)

TOP_REQUIRED = ["snapshot_version", "content_digest", "iana", "provenance", "locales"]
IANA_REQUIRED = ["file_date", "digest", "provenance", "registry_text"]
LOCALE_REQUIRED = ["locale_id", "code", "status", "iana_deprecated", "replacement_locale_id"]


def errors(document: Any) -> list[str]:
    return [e.message for e in VALIDATOR.iter_errors(document)]


def test_schema_is_a_valid_draft_2020_12_schema() -> None:
    Draft202012Validator.check_schema(SCHEMA)


def test_example_snapshot_is_valid() -> None:
    assert errors(EXAMPLE) == []


def test_example_covers_every_declared_field() -> None:
    assert sorted(EXAMPLE) == sorted(TOP_REQUIRED)
    assert sorted(EXAMPLE["iana"]) == sorted(IANA_REQUIRED)
    assert sorted(EXAMPLE["locales"][0]) == sorted(LOCALE_REQUIRED)


def test_schema_requires_exactly_the_documented_fields() -> None:
    assert sorted(SCHEMA["required"]) == sorted(TOP_REQUIRED)
    assert sorted(SCHEMA["properties"]["iana"]["required"]) == sorted(IANA_REQUIRED)
    item = SCHEMA["properties"]["locales"]["items"]
    assert sorted(item["required"]) == sorted(LOCALE_REQUIRED)


@pytest.mark.parametrize("field", TOP_REQUIRED)
def test_missing_top_level_field_is_rejected(field: str) -> None:
    document = copy.deepcopy(EXAMPLE)
    del document[field]
    assert errors(document), field


@pytest.mark.parametrize("field", IANA_REQUIRED)
def test_missing_iana_field_is_rejected(field: str) -> None:
    document = copy.deepcopy(EXAMPLE)
    del document["iana"][field]
    assert errors(document), field


@pytest.mark.parametrize("field", LOCALE_REQUIRED)
def test_missing_locale_field_is_rejected(field: str) -> None:
    document = copy.deepcopy(EXAMPLE)
    del document["locales"][0][field]
    assert errors(document), field


def test_missing_provenance_source_is_rejected() -> None:
    for path in (("provenance",), ("iana", "provenance")):
        document = copy.deepcopy(EXAMPLE)
        target = document
        for key in path:
            target = target[key]
        del target["source"]
        assert errors(document), path


def test_extra_properties_are_rejected() -> None:
    for path in ((), ("iana",), ("locales", 0)):
        document = copy.deepcopy(EXAMPLE)
        target = document
        for key in path:
            target = target[key]
        target["name"] = "Spanish"
        assert errors(document), path


@pytest.mark.parametrize("version", [0, -1, "2", 1.5, True, None])
def test_invalid_snapshot_version_is_rejected(version: Any) -> None:
    assert errors({**EXAMPLE, "snapshot_version": version})


@pytest.mark.parametrize("digest", ["", "abc", "sha256:", "sha256:" + "A" * 64, "md5:" + "a" * 64])
def test_malformed_digests_are_rejected(digest: str) -> None:
    assert errors({**EXAMPLE, "content_digest": digest})
    assert errors({**EXAMPLE, "iana": {**EXAMPLE["iana"], "digest": digest}})


@pytest.mark.parametrize("file_date", ["", "2026-9-1", "01/09/2026", "2026-09-01T00:00:00Z"])
def test_malformed_file_date_is_rejected(file_date: str) -> None:
    assert errors({**EXAMPLE, "iana": {**EXAMPLE["iana"], "file_date": file_date}})


def test_empty_registry_text_is_rejected() -> None:
    assert errors({**EXAMPLE, "iana": {**EXAMPLE["iana"], "registry_text": ""}})


@pytest.mark.parametrize("status", ["deprecated", "ACTIVE", "", None])
def test_invalid_status_is_rejected(status: Any) -> None:
    document = copy.deepcopy(EXAMPLE)
    document["locales"][0]["status"] = status
    assert errors(document)


def test_replacement_may_be_null_or_a_string_only() -> None:
    document = copy.deepcopy(EXAMPLE)
    document["locales"][0]["replacement_locale_id"] = 5
    assert errors(document)


def test_types_of_locale_fields_are_enforced() -> None:
    for field, value in (("code", 5), ("locale_id", None), ("iana_deprecated", "no")):
        document = copy.deepcopy(EXAMPLE)
        document["locales"][0][field] = value
        assert errors(document), field


def test_locales_must_be_an_array() -> None:
    assert errors({**EXAMPLE, "locales": {}})


def test_schema_does_not_decide_code_format() -> None:
    """RF-28 y las reglas de publicación son del dominio: el schema solo exige el tipo."""
    document = copy.deepcopy(EXAMPLE)
    document["locales"][0]["code"] = "He"
    assert errors(document) == []
