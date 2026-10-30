"""Snapshot de Regions: digest de contenido (RF-21) y admisión contra el historial (RF-26).

Mismas reglas que Locale (D5 de 001): A ya incorporado (no-op), B misma versión con otro digest,
C versión nueva anterior a la última, D versión posterior o primer snapshot. Función pura.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from gi_common_reference.regions.domain.digest import content_digest_matches
from gi_common_reference.regions.domain.model import Violation


class Classification(StrEnum):
    A = "A"  # ya incorporado (misma versión y mismo digest): no-op
    B = "B"  # misma versión con otro digest: rechazo
    C = "C"  # versión nueva anterior a la última: rechazo por regresión
    D = "D"  # versión posterior a la última, o primer snapshot: continúa


@dataclass(frozen=True)
class HistoricalSnapshot:
    """Lo que el dominio necesita saber de un snapshot ya incorporado."""

    snapshot_version: int
    content_digest: str


@dataclass(frozen=True)
class SnapshotDecision:
    classification: Classification | None
    violations: tuple[Violation, ...] = ()

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
    """Precedencia: digest de contenido → clasificación A/B/C/D. El documento ya pasó el schema."""
    if not content_digest_matches(document):
        message = "el digest de contenido declarado no coincide con el recalculado"
        return SnapshotDecision(None, (Violation("RF-21", message),))

    version, digest = document["snapshot_version"], document["content_digest"]
    known = {item.snapshot_version: item for item in history}
    if version in known:
        if known[version].content_digest == digest:
            return SnapshotDecision(Classification.A)
        message = f"la snapshot_version {version} ya existe con otro contenido"
        return SnapshotDecision(Classification.B, (Violation("RF-26", message),))
    if history and version < max(known):
        message = (
            f"la snapshot_version {version} es anterior a la última incorporada ({max(known)})"
        )
        return SnapshotDecision(Classification.C, (Violation("RF-26", message),))
    return SnapshotDecision(Classification.D)
