"""Caso de uso: incorporar un snapshot de Units en una única transacción (RF-42 a RF-46, D13).

El documento ya pasó el schema. Aquí se aplican, en el orden del plan, el digest y la clasificación
contra el historial, las reglas del catálogo contra el estado vigente, Locale, la política de
locales obligatorios y la tabla UCUM empaquetada; si todo pasa se escribe en un orden fijo (snapshot
con su artefacto → unidades → magnitudes → asociaciones → nombres) y se fuerzan las constraints
diferidas antes del commit. Una constraint violada es un rechazo, no un error operativo.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from gi_common_reference.units.domain.catalog import incoming_from, plan_catalog_changes
from gi_common_reference.units.domain.errors import ConstraintRejected
from gi_common_reference.units.domain.model import UcumTable, Violation
from gi_common_reference.units.domain.policy import RequiredLocales
from gi_common_reference.units.domain.ports import UnitsRepository
from gi_common_reference.units.domain.snapshot import evaluate_snapshot

# Constraint de la base → requisito de la spec que protege.
RULE_BY_CONSTRAINT = {
    "quantity_kind_reference_fk": "RF-8",
    "quantity_kind_reference_neutral": "RF-8",
    "quantity_kind_active_requires_active_reference": "RF-8",
    "quantity_kind_unit_linear_offset": "RF-12",
    "quantity_kind_unit_factor_canonical": "RF-13",
    "quantity_kind_unit_offset_canonical": "RF-13",
    "quantity_kind_code_unique": "RF-3",
    "unit_ucum_code_unique": "RF-3",
    "unit_unece_code_unique": "RF-4",
    "unit_ucum_code_immutable": "RF-5",
    "unit_unece_code_immutable": "RF-5",
}
DEFAULT_RULE = "RNF-4"


class Outcome(StrEnum):
    INCORPORATED = "incorporated"
    NOOP = "noop"  # snapshot ya incorporado (caso A)
    REJECTED = "rejected"


@dataclass(frozen=True)
class IncorporationResult:
    outcome: Outcome
    snapshot_version: int
    violations: tuple[Violation, ...] = ()
    new_units: int = 0
    updated_units: int = 0
    new_quantity_kinds: int = 0
    updated_quantity_kinds: int = 0
    new_associations: int = 0
    updated_associations: int = 0
    names: int = 0  # localizaciones nuevas y actualizadas
    locale_snapshot_version: int | None = None
    ucum_table_version: str | None = None


def incorporate_snapshot(
    document: Mapping[str, Any],
    repository: UnitsRepository,
    policy: RequiredLocales,
    ucum_table: UcumTable,
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
                incoming_from(document), tx.current_state(), locales, policy, ucum_table
            )
            if not plan.ok or locales.snapshot_version is None:
                return IncorporationResult(Outcome.REJECTED, version, plan.violations)

            tx.insert_snapshot(
                document, locales.snapshot_version, policy.version, ucum_table.version
            )
            tx.insert_units(plan.new_units, version)
            tx.update_units(plan.updated_units, version)
            tx.insert_quantity_kinds(plan.new_quantity_kinds, version)
            tx.update_quantity_kinds(plan.updated_quantity_kinds, version)
            tx.insert_associations(plan.new_associations, version)
            tx.update_associations(plan.updated_associations, version)
            tx.insert_kind_names(plan.new_kind_names)
            tx.update_kind_names(plan.updated_kind_names)
            tx.insert_unit_names(plan.new_unit_names)
            tx.update_unit_names(plan.updated_unit_names)
            changed_units = {u.unit_id for u in (*plan.new_units, *plan.updated_units)}
            touched_units = {n.unit_id for n in (*plan.new_unit_names, *plan.updated_unit_names)}
            tx.touch_units(sorted(touched_units - changed_units), version)
            changed_kinds = {
                k.quantity_kind_id for k in (*plan.new_quantity_kinds, *plan.updated_quantity_kinds)
            }
            touched_kinds = {
                n.quantity_kind_id for n in (*plan.new_kind_names, *plan.updated_kind_names)
            }
            tx.touch_quantity_kinds(sorted(touched_kinds - changed_kinds), version)
            tx.check_constraints()
    except ConstraintRejected as error:  # la transacción ya se deshizo
        rule = RULE_BY_CONSTRAINT.get(error.constraint or "", DEFAULT_RULE)
        message = f"la base de datos rechazó el estado final del catálogo: {error}"
        return IncorporationResult(Outcome.REJECTED, version, (Violation(rule, message),))
    return IncorporationResult(
        Outcome.INCORPORATED,
        version,
        new_units=len(plan.new_units),
        updated_units=len(plan.updated_units),
        new_quantity_kinds=len(plan.new_quantity_kinds),
        updated_quantity_kinds=len(plan.updated_quantity_kinds),
        new_associations=len(plan.new_associations),
        updated_associations=len(plan.updated_associations),
        names=sum(
            len(group)
            for group in (
                plan.new_kind_names,
                plan.updated_kind_names,
                plan.new_unit_names,
                plan.updated_unit_names,
            )
        ),
        locale_snapshot_version=locales.snapshot_version,
        ucum_table_version=ucum_table.version,
    )
