"""Constructores de snapshots para pruebas: siempre con digests coherentes salvo que se rompan."""

import copy
import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from gi_common_reference.locales.domain.snapshot import (
    HistoricalSnapshot,
    content_digest,
    iana_digest,
)

NAMESPACE = uuid.UUID("11111111-2222-3333-4444-555555555555")
ENTRY = "Type: language\nSubtag: {code}\nDescription: {code}\nAdded: 2005-10-16\n"


def locale_id(code: str) -> str:
    return str(uuid.uuid5(NAMESPACE, code))


def registry_text(file_date: str = "2026-09-01", codes: Sequence[str] = ("es", "en")) -> str:
    entries = "%%\n".join(ENTRY.format(code=code) for code in codes)
    return f"File-Date: {file_date}\n%%\n{entries}"


def locale(code: str, /, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "locale_id": locale_id(code),
        "code": code,
        "status": "active",
        "iana_deprecated": False,
        "replacement_locale_id": None,
    }
    return {**base, **overrides}


def seal(document: dict[str, Any]) -> dict[str, Any]:
    """Recalcula el digest de contenido tras modificar el documento."""
    sealed = copy.deepcopy(document)
    sealed["content_digest"] = content_digest(sealed)
    return sealed


def build_snapshot(
    version: int = 1,
    *,
    registry: str | None = None,
    file_date: str = "2026-09-01",
    declared_file_date: str | None = None,
    codes: Sequence[str] = ("es", "en"),
    locales: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Snapshot válido y sellado; `declared_file_date` declara otra fecha que la del texto."""
    text = registry if registry is not None else registry_text(file_date, codes)
    document: dict[str, Any] = {
        "snapshot_version": version,
        "content_digest": "",
        "iana": {
            "file_date": declared_file_date or file_date,
            "digest": iana_digest(text),
            "provenance": {"source": "test"},
            "registry_text": text,
        },
        "provenance": {"source": "test"},
        "locales": list(locales) if locales is not None else [locale(code) for code in codes],
    }
    return seal(document)


def history_of(document: dict[str, Any]) -> HistoricalSnapshot:
    return HistoricalSnapshot(
        snapshot_version=document["snapshot_version"],
        content_digest=document["content_digest"],
        iana_file_date=date.fromisoformat(document["iana"]["file_date"]),
    )


def language_entry(
    code: str, deprecated: str | None = None, preferred: str | None = None, scope: str | None = None
) -> str:
    lines = ["Type: language", f"Subtag: {code}", f"Description: {code}", "Added: 2005-10-16"]
    if deprecated:
        lines.append(f"Deprecated: {deprecated}")
    if preferred:
        lines.append(f"Preferred-Value: {preferred}")
    if scope:
        lines.append(f"Scope: {scope}")
    return "\n".join(lines) + "\n"


def iana_text(file_date: str, *entries: str) -> str:
    return f"File-Date: {file_date}\n%%\n" + "%%\n".join(entries)


def iw_scenario() -> tuple[dict[str, Any], dict[str, Any]]:
    """v1: `iw` publicado y activo. v2: el registro depreca `iw` (Preferred-Value `he`)."""
    v1_registry = iana_text(
        "2026-09-01", language_entry("es"), language_entry("en"), language_entry("iw")
    )
    v1 = build_snapshot(
        1,
        registry=v1_registry,
        file_date="2026-09-01",
        locales=[locale("es"), locale("en"), locale("iw")],
    )
    v2_registry = iana_text(
        "2026-10-01",
        language_entry("es"),
        language_entry("en"),
        language_entry("he"),
        language_entry("iw", "1989-01-01", "he"),
    )
    iw_deprecated = locale(
        "iw",
        status="inactive",
        iana_deprecated=True,
        replacement_locale_id=locale_id("he"),
    )
    v2 = build_snapshot(
        2,
        registry=v2_registry,
        file_date="2026-10-01",
        locales=[locale("es"), locale("en"), locale("he"), iw_deprecated],
    )
    return v1, v2
