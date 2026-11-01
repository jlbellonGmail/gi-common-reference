"""Snapshot: digests canónicos (RF-30, RF-31, S-21) y admisión contra el historial (RF-32).

Las reglas de digest y sus vectores están en `contracts/locale-snapshot.v1.vectors.json`.
`evaluate_snapshot` es una función pura: no toca base de datos ni red.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from gi_common_reference.locales.domain.iana import IanaFormatError, IanaRegistry, parse_registry
from gi_common_reference.locales.domain.model import Violation

DIGEST_PREFIX = "sha256:"
CONTENT_DIGEST_FIELD = "content_digest"


class CanonicalizationError(ValueError):
    """El documento no tiene representación canónica (números no enteros, tipos no JSON...)."""


def canonical_json(value: Any) -> bytes:
    """JSON canónico en UTF-8: claves por punto de código, sin espacios, solo enteros."""
    return _canonical(value).encode("utf-8")


def content_digest(document: Mapping[str, Any]) -> str:
    """Digest del documento sin su `content_digest` de nivel superior (no autorreferente)."""
    body = {key: value for key, value in document.items() if key != CONTENT_DIGEST_FIELD}
    return _digest(canonical_json(body))


def iana_digest(registry_text: str) -> str:
    """Digest de los bytes UTF-8 exactos del artefacto IANA, sin normalizar nada."""
    return _digest(registry_text.encode("utf-8"))


def content_digest_matches(document: Mapping[str, Any]) -> bool:
    declared = document.get(CONTENT_DIGEST_FIELD)
    return isinstance(declared, str) and declared == content_digest(document)


def iana_digest_matches(document: Mapping[str, Any]) -> bool:
    iana = document.get("iana")
    if not isinstance(iana, Mapping):
        return False
    declared, text = iana.get("digest"), iana.get("registry_text")
    return isinstance(declared, str) and isinstance(text, str) and declared == iana_digest(text)


def _digest(data: bytes) -> str:
    return DIGEST_PREFIX + hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise CanonicalizationError(f"clave que no es string: {key!r}")
        items = (f"{_string(key)}:{_canonical(value[key])}" for key in sorted(value))
        return "{" + ",".join(items) + "}"
    raise CanonicalizationError(f"valor no admitido en el JSON canónico: {type(value).__name__}")


def _string(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise CanonicalizationError("string con sustitutos Unicode sin par") from error
    return json.dumps(value, ensure_ascii=False)


class Classification(StrEnum):
    """Resultado de RF-32 contra el historial de snapshots incorporados."""

    A = "A"  # ya incorporado (misma versión y mismo digest): no-op
    B = "B"  # misma versión con otro digest: rechazo
    C = "C"  # versión nueva anterior a la última: rechazo por regresión
    D = "D"  # versión posterior a la última, o primer snapshot: continúa


@dataclass(frozen=True)
class HistoricalSnapshot:
    """Lo que el dominio necesita saber de un snapshot ya incorporado."""

    snapshot_version: int
    content_digest: str
    iana_file_date: date


@dataclass(frozen=True)
class SnapshotDecision:
    """Resultado de admitir un snapshot. `registry` solo viene cuando el snapshot continúa."""

    classification: Classification | None
    violations: tuple[Violation, ...] = ()
    registry: IanaRegistry | None = None

    @property
    def is_noop(self) -> bool:
        return self.classification is Classification.A and not self.violations

    @property
    def rejected(self) -> bool:
        return bool(self.violations)

    @property
    def proceeds(self) -> bool:
        return self.classification is Classification.D and not self.violations


def evaluate_snapshot(
    document: Mapping[str, Any], history: Sequence[HistoricalSnapshot]
) -> SnapshotDecision:
    """Precedencia: RF-31 (digest de contenido) → RF-32 (A/B/C/D) → RF-30 → RF-29.

    El documento ya pasó el schema. Un snapshot ya incorporado (A) es no-op y uno que choca con el
    historial (B, C) se rechaza sin mirar el artefacto IANA.
    """
    if not _content_digest_is_valid(document):
        message = "el digest de contenido declarado no coincide con el recalculado"
        return SnapshotDecision(None, (Violation("RF-31", message),))

    classification, violations = _classify(document, history)
    if classification is not Classification.D:
        return SnapshotDecision(classification, violations)

    registry, violations = _check_iana_artifact(document)
    if registry is None:
        return SnapshotDecision(classification, violations)

    violations = _check_file_date_is_monotonic(registry, history)
    if violations:
        return SnapshotDecision(classification, violations)
    return SnapshotDecision(classification, registry=registry)


def _content_digest_is_valid(document: Mapping[str, Any]) -> bool:
    try:
        return content_digest_matches(document)
    except CanonicalizationError:
        return False


def _classify(
    document: Mapping[str, Any], history: Sequence[HistoricalSnapshot]
) -> tuple[Classification, tuple[Violation, ...]]:
    version, digest = document["snapshot_version"], document["content_digest"]
    known = {item.snapshot_version: item for item in history}
    if version in known:
        if known[version].content_digest == digest:
            return Classification.A, ()
        message = f"la snapshot_version {version} ya existe con otro contenido"
        return Classification.B, (Violation("RF-32", message),)
    if history and version < max(known):
        message = (
            f"la snapshot_version {version} es anterior a la última incorporada ({max(known)})"
        )
        return Classification.C, (Violation("RF-32", message),)
    return Classification.D, ()


def _check_iana_artifact(
    document: Mapping[str, Any],
) -> tuple[IanaRegistry | None, tuple[Violation, ...]]:
    iana = document.get("iana")
    text = iana.get("registry_text") if isinstance(iana, Mapping) else None
    if not isinstance(iana, Mapping) or not isinstance(text, str) or not text:
        return None, (Violation("RF-30", "falta el artefacto IANA de referencia"),)

    violations: list[Violation] = []
    if not iana_digest_matches(document):
        message = "el digest IANA declarado no coincide con el recalculado"
        violations.append(Violation("RF-30", message))
    try:
        registry = parse_registry(text)
    except IanaFormatError as error:
        violations.append(Violation("RF-30", f"artefacto IANA incompleto: {error}"))
        return None, tuple(violations)
    declared = iana.get("file_date")
    if registry.file_date.isoformat() != declared:
        message = (
            f"el File-Date del artefacto ({registry.file_date.isoformat()}) "
            f"no coincide con el declarado ({declared})"
        )
        violations.append(Violation("RF-30", message))
    return (None if violations else registry), tuple(violations)


def _check_file_date_is_monotonic(
    registry: IanaRegistry, history: Sequence[HistoricalSnapshot]
) -> tuple[Violation, ...]:
    if not history:
        return ()
    last = max(history, key=lambda item: item.snapshot_version)
    if registry.file_date >= last.iana_file_date:
        return ()
    message = (
        f"el File-Date {registry.file_date.isoformat()} es anterior al del último snapshot "
        f"incorporado ({last.iana_file_date.isoformat()})"
    )
    return (Violation("RF-29", message),)
