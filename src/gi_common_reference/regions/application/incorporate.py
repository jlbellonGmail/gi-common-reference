"""Caso de uso: incorporar un snapshot de Regions en una única transacción (RF-21, RF-25, RF-26).

El documento ya pasó el schema. Aquí se aplican, en el orden del plan, el digest y la clasificación
contra el historial, las reglas del catálogo contra el estado vigente, Locale y la política de
locales obligatorios; si todo pasa se escribe en un orden fijo y se fuerzan las constraints
diferidas antes del commit. Una constraint violada es un rechazo, no un error operativo (D13).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from gi_common_reference.regions.domain.catalog import incoming_from, plan_catalog_changes
from gi_common_reference.regions.domain.errors import ConstraintRejected
from gi_common_reference.regions.domain.model import Violation
from gi_common_reference.regions.domain.policy import RequiredLocales
from gi_common_reference.regions.domain.ports import RegionRepository
from gi_common_reference.regions.domain.snapshot import evaluate_snapshot


class Outcome(StrEnum):
    INCORPORATED = "incorporated"
    NOOP = "noop"  # snapshot ya incorporado (caso A)
    REJECTED = "rejected"


@dataclass(frozen=True)
class IncorporationResult:
    outcome: Outcome
    snapshot_version: int
    violations: tuple[Violation, ...] = ()
    new_regions: int = 0
    new_subregions: int = 0
    updated: int = 0
    reclassifications: int = 0
    recodings: int = 0
    locale_snapshot_version: int | None = None


def incorporate_snapshot(
    document: Mapping[str, Any], repository: RegionRepository, policy: RequiredLocales
) -> IncorporationResult:
    version: int = document["snapshot_version"]
    try:
        with repository.transaction() as tx:
            decision = evaluate_snapshot(document, tx.history())
            if decision.is_noop:
                return IncorporationResult(Outcome.NOOP, version)
            if decision.rejected:
                return IncorporationResult(Outcome.REJECTED, version, decision.violations)

            locales = tx.locale_catalog()
            plan = plan_catalog_changes(
                incoming_from(document), tx.current_state(), locales, policy
            )
            if not plan.ok or locales.snapshot_version is None:
                return IncorporationResult(Outcome.REJECTED, version, plan.violations)

            tx.insert_snapshot(document, locales.snapshot_version, policy.version)
            tx.insert_regions(plan.new_regions, version)
            tx.update_regions(plan.updated_regions, version)
            tx.insert_subregions(plan.new_subregions, version)
            tx.update_subregions(plan.updated_subregions, version)
            tx.record_reclassifications(plan.reclassifications, version)
            tx.record_recodings(plan.recodings, version)
            tx.insert_names(plan.new_region_names, plan.new_subregion_names)
            tx.update_names(plan.updated_region_names, plan.updated_subregion_names)
            tx.check_constraints()
    except ConstraintRejected as error:  # la transacción ya se deshizo
        rule = "RF-35" if error.foreign else "RNF-3"
        message = f"la base de datos rechazó el estado final del catálogo: {error}"
        return IncorporationResult(Outcome.REJECTED, version, (Violation(rule, message),))
    updated = (
        len(plan.updated_regions)
        + len(plan.updated_subregions)
        + len(plan.updated_region_names)
        + len(plan.updated_subregion_names)
    )
    return IncorporationResult(
        Outcome.INCORPORATED,
        version,
        new_regions=len(plan.new_regions),
        new_subregions=len(plan.new_subregions),
        updated=updated,
        reclassifications=len(plan.reclassifications),
        recodings=len(plan.recodings),
        locale_snapshot_version=locales.snapshot_version,
    )
