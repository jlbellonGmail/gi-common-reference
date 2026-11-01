"""Caso de uso: incorporar un snapshot en una única transacción (RF-14, RF-20, RF-21).

El documento ya pasó el schema (RF-31, paso 1). Aquí se aplican, en el orden de la spec, el digest
de contenido, la clasificación contra el historial, el artefacto IANA, el `File-Date` y las reglas
del catálogo; si todo pasa se escribe en un orden fijo.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from gi_common_reference.locales.domain.catalog import locale_records, plan_catalog_changes
from gi_common_reference.locales.domain.model import Violation
from gi_common_reference.locales.domain.ports import LocaleRepository
from gi_common_reference.locales.domain.snapshot import evaluate_snapshot


class Outcome(StrEnum):
    INCORPORATED = "incorporated"
    NOOP = "noop"  # snapshot ya incorporado (caso A de RF-32)
    REJECTED = "rejected"


@dataclass(frozen=True)
class IncorporationResult:
    outcome: Outcome
    snapshot_version: int
    violations: tuple[Violation, ...] = ()
    new_locales: int = 0
    updated_locales: int = 0


def incorporate_snapshot(
    document: Mapping[str, Any], repository: LocaleRepository
) -> IncorporationResult:
    version: int = document["snapshot_version"]
    with repository.transaction() as tx:
        decision = evaluate_snapshot(document, tx.history())
        if decision.is_noop:
            return IncorporationResult(Outcome.NOOP, version)
        if decision.rejected or decision.registry is None:
            return IncorporationResult(Outcome.REJECTED, version, decision.violations)

        plan = plan_catalog_changes(
            locale_records(document), tx.current_locales(), decision.registry
        )
        if not plan.ok:
            return IncorporationResult(Outcome.REJECTED, version, plan.violations)

        tx.insert_snapshot(document)
        tx.insert_locales(plan.new_locales, version)
        tx.update_metadata(plan.metadata_updates)
        tx.replace_aliases(decision.registry.language_aliases())
    return IncorporationResult(
        Outcome.INCORPORATED,
        version,
        new_locales=len(plan.new_locales),
        updated_locales=len(plan.metadata_updates),
    )
