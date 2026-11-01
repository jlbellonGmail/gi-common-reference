"""T3: conjunto obligatorio de locales versionado en el repositorio (RF-31, S-7, D9)."""

from typing import Any

import pytest

from gi_common_reference.regions.domain.errors import SchemaLoadError
from gi_common_reference.regions.infrastructure.policy_reader import (
    load_required_locales,
    parse_required_locales,
)
from tests.fixtures.regions import EN, ES


def test_the_packaged_policy_lists_en_and_es_by_locale_id() -> None:
    policy = load_required_locales()
    assert policy.version == 1
    assert policy.locale_ids == frozenset({EN, ES})
    assert {item.code for item in policy.locales} == {"en", "es"}


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"locales": [{"locale_id": EN, "code": "en"}]},
        {"policy_version": 0, "locales": [{"locale_id": EN, "code": "en"}]},
        {"policy_version": True, "locales": [{"locale_id": EN, "code": "en"}]},
        {"policy_version": 1, "locales": []},
        {"policy_version": 1, "locales": [{"locale_id": "en", "code": "en"}]},
        {"policy_version": 1, "locales": [{"locale_id": EN.upper(), "code": "en"}]},
        {"policy_version": 1, "locales": [{"locale_id": EN}]},
        {"policy_version": 1, "locales": ["en"]},
        {
            "policy_version": 1,
            "locales": [{"locale_id": EN, "code": "en"}, {"locale_id": EN, "code": "en"}],
        },
    ],
)
def test_a_malformed_policy_is_an_environment_error(document: Any) -> None:
    with pytest.raises(SchemaLoadError):
        parse_required_locales(document)
