"""T4: digests canónicos (RF-30, RF-31, S-21). Los vectores los generó un canonicalizador
independiente (Node) y se publican en `contracts/` para que PREP produzca digests idénticos."""

import copy
import json
from typing import Any

import pytest

from gi_common_reference.locales.domain.snapshot import (
    CanonicalizationError,
    canonical_json,
    content_digest,
    content_digest_matches,
    iana_digest,
    iana_digest_matches,
)
from tests.fixtures import contract_json

VECTORS: Any = contract_json("locale-snapshot.v1.vectors.json")
EXAMPLE: Any = contract_json("locale-snapshot.v1.example.json")


def vector_ids(key: str) -> list[str]:
    return [v["name"] for v in VECTORS[key]]


@pytest.mark.parametrize("vector", VECTORS["content_digest"], ids=vector_ids("content_digest"))
def test_content_digest_reproduces_vectors(vector: dict[str, Any]) -> None:
    document = vector["document"]
    without = {k: v for k, v in document.items() if k != "content_digest"}
    assert canonical_json(without).decode("utf-8") == vector["canonical"]
    assert content_digest(document) == vector["digest"]


@pytest.mark.parametrize("vector", VECTORS["iana_digest"], ids=vector_ids("iana_digest"))
def test_iana_digest_reproduces_vectors(vector: dict[str, Any]) -> None:
    assert iana_digest(vector["registry_text"]) == vector["digest"]


def test_iana_digest_does_not_normalize_line_endings() -> None:
    assert iana_digest("a\nb") != iana_digest("a\r\nb")


def test_vectors_publish_the_canonicalization_rules() -> None:
    assert len(VECTORS["rules"]) >= 6


@pytest.mark.parametrize("vector", VECTORS["errors"], ids=vector_ids("errors"))
def test_floats_invalidate_the_document(vector: dict[str, Any]) -> None:
    document = vector.get("document") or json.loads(vector["jsonText"])
    with pytest.raises(CanonicalizationError):
        content_digest(document)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1.5, {"a": [{"b": 2.0}]}])
def test_non_integer_numbers_are_rejected_anywhere(value: Any) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json({"x": value})


@pytest.mark.parametrize("value", [{1: "a"}, {"a": (1, 2)}, {"a": {1, 2}}, {"a": b"x"}])
def test_unsupported_types_are_rejected(value: Any) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json(value)


def test_lone_surrogates_are_rejected() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json({"a": "\ud800"})


def test_booleans_are_not_confused_with_integers() -> None:
    assert canonical_json({"a": True, "b": 1}) == b'{"a":true,"b":1}'


def test_same_document_with_other_key_order_and_whitespace_has_same_digest() -> None:
    reordered = json.loads(json.dumps(EXAMPLE, sort_keys=True, indent=7))
    shuffled = dict(reversed(list(EXAMPLE.items())))
    shuffled["iana"] = dict(reversed(list(EXAMPLE["iana"].items())))
    shuffled["locales"] = [dict(reversed(list(item.items()))) for item in EXAMPLE["locales"]]
    assert content_digest(reordered) == content_digest(EXAMPLE)
    assert content_digest(shuffled) == content_digest(EXAMPLE)


def test_array_order_is_significant() -> None:
    swapped = copy.deepcopy(EXAMPLE)
    swapped["locales"].reverse()
    assert content_digest(swapped) != content_digest(EXAMPLE)


# --- el digest declarado se recalcula y compara ------------------------------------------------


def test_example_digests_match() -> None:
    assert content_digest_matches(EXAMPLE)
    assert iana_digest_matches(EXAMPLE)


def test_content_digest_does_not_depend_on_its_declared_value() -> None:
    """Sin autorreferencia: cambiar el valor declarado no cambia el digest calculado."""
    other = {**EXAMPLE, "content_digest": "sha256:" + "f" * 64}
    assert content_digest(other) == content_digest(EXAMPLE)
    assert not content_digest_matches(other)


def test_wrong_declared_content_digest_is_detected() -> None:
    for wrong in ("sha256:" + "0" * 64, EXAMPLE["content_digest"].upper(), "", "xyz"):
        assert not content_digest_matches({**EXAMPLE, "content_digest": wrong})


def test_any_change_in_content_is_detected() -> None:
    changed = copy.deepcopy(EXAMPLE)
    changed["locales"][0]["status"] = "inactive"
    assert not content_digest_matches(changed)

    changed = copy.deepcopy(EXAMPLE)
    changed["snapshot_version"] += 1
    assert not content_digest_matches(changed)

    changed = copy.deepcopy(EXAMPLE)
    changed["provenance"]["generated_at"] = "2026-09-03T00:00:00Z"
    assert not content_digest_matches(changed)


def test_wrong_declared_iana_digest_is_detected() -> None:
    wrong = copy.deepcopy(EXAMPLE)
    wrong["iana"]["digest"] = "sha256:" + "0" * 64
    assert not iana_digest_matches(wrong)


def test_tampered_registry_text_is_detected_by_both_digests() -> None:
    tampered = copy.deepcopy(EXAMPLE)
    tampered["iana"]["registry_text"] += "%%\nType: language\nSubtag: zz\n"
    assert not iana_digest_matches(tampered)
    assert not content_digest_matches(tampered)


def test_iana_digest_is_covered_by_the_content_digest() -> None:
    swapped = copy.deepcopy(EXAMPLE)
    swapped["iana"]["digest"] = "sha256:" + "1" * 64
    assert not content_digest_matches(swapped)


def test_missing_or_non_string_digests_never_match() -> None:
    without = {k: v for k, v in EXAMPLE.items() if k != "content_digest"}
    assert not content_digest_matches(without)
    assert not content_digest_matches({**EXAMPLE, "content_digest": None})
    assert not iana_digest_matches({**EXAMPLE, "iana": {"registry_text": "x"}})
    assert not iana_digest_matches({**EXAMPLE, "iana": {"digest": "x"}})
