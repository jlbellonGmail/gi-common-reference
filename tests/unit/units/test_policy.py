"""T3: conjunto obligatorio de locales de Units v1 (RF-18, RF-19, D11 del plan)."""

import json
from importlib import resources
from typing import Any

import pytest

from gi_common_reference.currencies.infrastructure.policy_reader import (
    load_required_locales as currency_policy,
)
from gi_common_reference.units.domain.errors import SchemaLoadError
from gi_common_reference.units.domain.policy import RequiredLocale
from gi_common_reference.units.infrastructure.policy_reader import (
    POLICY_PACKAGE,
    POLICY_RESOURCE,
    load_required_locales,
    parse_required_locales,
)
from tests.fixtures.units import EN, ES

ID = "1d806402-a823-4580-9f4d-958c6e5a5354"


def test_the_packaged_policy_lists_en_and_es_by_locale_id_with_its_version() -> None:
    policy = load_required_locales()
    assert policy.version == 1
    assert policy.locales == (RequiredLocale(EN, "en"), RequiredLocale(ES, "es"))
    assert policy.locale_ids == {EN, ES}


def test_the_policy_is_a_resource_of_the_units_package_not_of_another_catalog() -> None:
    assert POLICY_PACKAGE == "gi_common_reference.units.infrastructure"
    text = resources.files(POLICY_PACKAGE).joinpath(POLICY_RESOURCE).read_text("utf-8")
    document = json.loads(text)
    assert document["policy_version"] == 1
    assert "005" in document["description"] and "Units" in document["description"]


def test_the_locale_ids_are_the_same_as_the_ones_published_for_en_and_es() -> None:
    """D11: mismos locale_id que Currency (identidad publicada de Locale), política propia."""
    mine = {(item.locale_id, item.code) for item in load_required_locales().locales}
    theirs = {(item.locale_id, item.code) for item in currency_policy().locales}
    assert mine == theirs


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
