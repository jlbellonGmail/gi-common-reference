"""T3: conjunto obligatorio de locales de Currency v1 (RF-13, D-19, D9 del plan, S-10)."""

import json
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from gi_common_reference.currencies.domain.errors import SchemaLoadError
from gi_common_reference.currencies.domain.policy import RequiredLocale
from gi_common_reference.currencies.infrastructure.policy_reader import (
    POLICY_PACKAGE,
    POLICY_RESOURCE,
    load_required_locales,
    parse_required_locales,
)
from tests.fixtures.currencies import EN, ES

ID = "1d806402-a823-4580-9f4d-958c6e5a5354"


def test_the_packaged_policy_lists_en_and_es_by_locale_id_with_its_version() -> None:
    policy = load_required_locales()
    assert policy.version == 1
    assert policy.locales == (RequiredLocale(EN, "en"), RequiredLocale(ES, "es"))
    assert policy.locale_ids == {EN, ES}


def test_the_policy_is_a_resource_of_the_currencies_package_not_of_another_catalog() -> None:
    assert POLICY_PACKAGE == "gi_common_reference.currencies.infrastructure"
    text = resources.files(POLICY_PACKAGE).joinpath(POLICY_RESOURCE).read_text("utf-8")
    document = json.loads(text)
    assert document["policy_version"] == 1
    assert "004" in document["description"] and "Currency" in document["description"]


@pytest.mark.parametrize(
    "document",
    [
        [],
        {},
        {"policy_version": 0, "locales": [{"locale_id": ID, "code": "en"}]},
        {"policy_version": True, "locales": [{"locale_id": ID, "code": "en"}]},
        {"policy_version": 1, "locales": []},
        {"policy_version": 1, "locales": "en"},
        {"policy_version": 1, "locales": [{"locale_id": "en", "code": "en"}]},
        {"policy_version": 1, "locales": [{"locale_id": ID.upper(), "code": "en"}]},
        {"policy_version": 1, "locales": [{"locale_id": ID, "code": ""}]},
        {"policy_version": 1, "locales": [{"locale_id": ID}]},
        {
            "policy_version": 1,
            "locales": [{"locale_id": ID, "code": "en"}, {"locale_id": ID, "code": "es"}],
        },
    ],
)
def test_a_malformed_policy_is_an_environment_error(document: Any) -> None:
    with pytest.raises(SchemaLoadError):
        parse_required_locales(document)


def test_a_missing_policy_resource_is_an_environment_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "gi_common_reference.currencies.infrastructure.policy_reader.POLICY_RESOURCE",
        "missing.json",
    )
    with pytest.raises(SchemaLoadError):
        load_required_locales()
