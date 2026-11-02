"""T3: contrato del snapshot de Currency (RF-4, RF-41, RF-42): schema, digest y lector."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from gi_common_reference.currencies.domain.digest import (
    CanonicalizationError,
    canonical_json,
    content_digest,
    content_digest_matches,
)
from gi_common_reference.currencies.infrastructure.snapshot_reader import (
    SnapshotFormatError,
    load_snapshot_schema,
    read_snapshot_document,
)
from tests.fixtures.currencies import (
    association,
    build_snapshot,
    currency,
    currency_id,
)

ROOT = Path(__file__).resolve().parents[3]
LOCALE_VECTORS = ROOT / "contracts" / "locale-snapshot.v1.vectors.json"
REQUIRED = [
    "snapshot_version",
    "content_digest",
    "country_snapshot_version",
    "provenance",
    "currencies",
    "currency_names",
    "country_currencies",
]


def write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


# --- digest -------------------------------------------------------------------------------------


def test_canonical_json_reproduces_the_published_locale_vectors() -> None:
    """D2, D21: una sola regla de digest para PREP en todos los catálogos."""
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
    tampered["currencies"][0]["status"] = "inactive"
    assert content_digest_matches(document)
    assert not content_digest_matches(tampered)
    assert not content_digest_matches({**document, "content_digest": 3})
    assert not content_digest_matches({**document, "snapshot_version": 1.5})


def test_the_digest_covers_codes_and_dates_exactly_as_text() -> None:
    """`032` y `32`, `null` y una fecha producen digests distintos: no hay coerción."""
    first = build_snapshot(codes=("ARS",), currencies=[currency("ARS", numeric_code="032")])
    second = build_snapshot(codes=("ARS",), currencies=[currency("ARS", numeric_code="32")])
    assert first["content_digest"] != second["content_digest"]
    open_ = build_snapshot(codes=("HRK",), country_currencies=[association("HR", "HRK")])
    from datetime import date

    closed = build_snapshot(
        codes=("HRK",), country_currencies=[association("HR", "HRK", None, date(2023, 1, 1))]
    )
    assert open_["content_digest"] != closed["content_digest"]


def test_minor_units_null_and_zero_have_different_digests() -> None:
    """CL-1: «no aplicable» no es 0."""
    zero = build_snapshot(codes=("XAU",), currencies=[currency("XAU", minor_units=0)])
    none = build_snapshot(codes=("XAU",), currencies=[currency("XAU", minor_units=None)])
    assert zero["content_digest"] != none["content_digest"]


# --- schema y lector ----------------------------------------------------------------------------


def test_the_default_snapshot_is_read_unchanged(tmp_path: Path) -> None:
    document = build_snapshot()
    assert read_snapshot_document(write(tmp_path, document)) == document


def test_leading_zeros_minor_units_not_applicable_and_open_periods_are_accepted(
    tmp_path: Path,
) -> None:
    """CL-1–CL-3, CL-23: ARS `032`, JPY 0, XAU N.A., período sin extremos."""
    document = build_snapshot()
    read = read_snapshot_document(write(tmp_path, document))
    by_code = {item["alphabetic_code"]: item for item in read["currencies"]}
    assert by_code["ARS"]["numeric_code"] == "032"
    assert by_code["BOB"]["numeric_code"] == "068"
    assert by_code["JPY"]["minor_units"] == 0
    assert by_code["KWD"]["minor_units"] == 3
    assert by_code["CLF"]["minor_units"] == 4
    assert by_code["XAU"]["minor_units"] is None
    assert any(
        item["valid_from"] is None and item["valid_to"] is None
        for item in read["country_currencies"]
    )


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
        ("currencies", "currency_id"),
        ("currencies", "alphabetic_code"),
        ("currencies", "numeric_code"),
        ("currencies", "minor_units"),
        ("currencies", "fund_code"),
        ("currencies", "status"),
        ("currencies", "replacement_currency_ids"),
        ("currency_names", "currency_id"),
        ("currency_names", "locale_id"),
        ("currency_names", "name"),
        ("country_currencies", "country_currency_id"),
        ("country_currencies", "country_id"),
        ("country_currencies", "currency_id"),
        ("country_currencies", "status"),
        ("country_currencies", "valid_from"),
        ("country_currencies", "valid_to"),
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
        (["currencies", 0, "tenant_id"], "x"),
        (["currencies", 0, "name"], "Argentine Peso"),
        (["currencies", 0, "symbol"], "$"),
        (["currencies", 0, "exchange_rate"], 1),
        (["currencies", 0, "is_active"], True),
        (["currencies", 0, "status"], "deprecated"),
        (["currencies", 0, "status"], "not_found"),
        (["currencies", 0, "replacement_currency_ids"], None),
        (["currencies", 0, "replacement_currency_ids"], "uuid"),
        (["currencies", 0, "replacement_currency_ids"], [None]),
        (["currencies", 0, "replacement_currency_ids"], [1]),
        (["currencies", 0, "replacement_currency_id"], None),
        (["currencies", 0, "numeric_code"], 32),
        (["currencies", 0, "numeric_code"], "32"),
        (["currencies", 0, "numeric_code"], "0032"),
        (["currencies", 0, "numeric_code"], None),
        (["currencies", 0, "alphabetic_code"], "ars"),
        (["currencies", 0, "alphabetic_code"], "AR"),
        (["currencies", 0, "alphabetic_code"], "ARS1"),
        (["currencies", 0, "alphabetic_code"], None),
        (["currencies", 0, "minor_units"], "2"),
        (["currencies", 0, "minor_units"], -1),
        (["currencies", 0, "minor_units"], True),
        (["currencies", 0, "fund_code"], "false"),
        (["currencies", 0, "fund_code"], None),
        (["currency_names", 0, "symbol"], "$"),
        (["currency_names", 0, "name"], None),
        (["currency_names", 0, "plural"], "pesos"),
        (["country_currencies", 0, "is_primary"], True),
        (["country_currencies", 0, "status"], "vigente"),
        (["country_currencies", 0, "valid_from"], "2023-1-1"),
        (["country_currencies", 0, "valid_from"], "2023-01-01T00:00:00Z"),
        (["country_currencies", 0, "valid_from"], 20230101),
        (["country_currencies", 0, "valid_to"], "01/01/2023"),
        (["country_currencies", 0, "valid_to"], " 2023-01-01"),
        (["country_currencies", 0, "valid_to"], 2023),
        (["snapshot_version"], 0),
        (["snapshot_version"], -1),
        (["snapshot_version"], "1"),
        (["country_snapshot_version"], 0),
        (["content_digest"], "sha256:abc"),
        (["provenance", "sources", 0, "role"], "classification"),
    ],
)
def test_malformed_values_and_extra_fields_are_rejected(
    tmp_path: Path, path: list[Any], value: Any
) -> None:
    with pytest.raises(SnapshotFormatError):
        read_snapshot_document(write(tmp_path, _mutated(path, value)))


def test_a_float_a_nan_and_a_duplicate_key_are_rejected_by_the_reader(tmp_path: Path) -> None:
    text = json.dumps(build_snapshot(), ensure_ascii=False)
    for broken in (
        text.replace('"minor_units": 2', '"minor_units": 2.0', 1),
        text.replace('"snapshot_version": 1', '"snapshot_version": 1.5', 1),
        text.replace('"snapshot_version": 1', '"snapshot_version": NaN', 1),
        text.replace('{"snapshot_version": 1', '{"snapshot_version": 1, "snapshot_version": 2', 1),
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


def test_the_schema_does_not_model_what_is_out_of_scope() -> None:
    """D-11, RF-8: ni símbolos, ni formato, ni cotizaciones, ni tenant, ni moneda principal."""
    text = json.dumps(load_snapshot_schema())
    properties = {
        name for name in _all_property_names(load_snapshot_schema()) if isinstance(name, str)
    }
    for forbidden in (
        "tenant_id",
        "organization_id",
        "symbol",
        "narrow_symbol",
        "mask",
        "separator",
        "plural",
        "rate",
        "exchange_rate",
        "price",
        "balance",
        "is_primary",
        "is_active",
    ):
        assert forbidden not in properties, forbidden
    assert "tenant" not in text.replace("tenant u organización", "")


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


def test_ids_are_stable_and_independent_from_the_codes() -> None:
    """RF-2: el id de prueba no se deriva del contenido del snapshot."""
    assert currency("ARS")["currency_id"] == currency_id("ARS")
    renumbered = currency("ARS", numeric_code="999")
    assert renumbered["currency_id"] == currency("ARS")["currency_id"]
