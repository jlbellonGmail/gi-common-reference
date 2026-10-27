"""Snapshot de Regions: admisión contra el historial (RF-21, RF-26)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoricalSnapshot:
    """Lo que el dominio necesita saber de un snapshot ya incorporado."""

    snapshot_version: int
    content_digest: str
