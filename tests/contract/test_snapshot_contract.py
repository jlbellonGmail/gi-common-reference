"""T4: el snapshot de ejemplo publicado cumple el contrato con PREP (schema y digests)."""

from gi_common_reference.locales.domain.iana import parse_registry
from gi_common_reference.locales.domain.snapshot import content_digest_matches, iana_digest_matches
from gi_common_reference.locales.infrastructure.snapshot_reader import read_snapshot_document
from tests.fixtures import CONTRACTS


def test_published_example_is_valid_and_self_consistent() -> None:
    document = read_snapshot_document(CONTRACTS / "locale-snapshot.v1.example.json")
    assert content_digest_matches(document)
    assert iana_digest_matches(document)


def test_published_example_artifact_declares_its_own_file_date() -> None:
    document = read_snapshot_document(CONTRACTS / "locale-snapshot.v1.example.json")
    registry = parse_registry(document["iana"]["registry_text"])
    assert registry.file_date.isoformat() == document["iana"]["file_date"]
