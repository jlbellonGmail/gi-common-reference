"""Caso de uso: incorporar un snapshot de Currency en una única transacción (RF-36 a RF-41).

El documento ya pasó el schema. Aquí se aplican, en el orden del plan, el digest y la clasificación
contra el historial, las reglas del catálogo contra el estado vigente, Locale, Countries y la
política de locales obligatorios; si todo pasa se escribe en un orden fijo y se fuerzan las
constraints diferidas antes del commit. Una constraint violada es un rechazo, no un error operativo
(D17).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from gi_common_reference.currencies.domain.catalog import incoming_from, plan_catalog_changes
from gi_common_reference.currencies.domain.errors import ConstraintRejected
from gi_common_reference.currencies.domain.model import Violation
from gi_common_reference.currencies.domain.policy import RequiredLocales
from gi_common_reference.currencies.domain.ports import CurrencyRepository
from gi_common_reference.currencies.domain.snapshot import evaluate_snapshot

# Constraint de la base → requisito de la spec que protege (D17).
RULE_BY_CONSTRAINT = {
    "country_currency_active_no_overlap": "RF-45",
    "country_currency_validity_ordered": "RF-44",
    "country_currency_open_requires_active_targets": "RF-19",
    "currency_inactive_has_open_associations": "RF-19",
    "currency_replacement_acyclic": "RF-6",
    "currency_replacement_exists": "RF-6",
    "currency_numeric_code_active_unique": "RF-3",
    "currency_alphabetic_code_unique": "RF-3",
}


class Outcome(StrEnum):
    INCORPORATED = "incorporated"
    NOOP = "noop"  # snapshot ya incorporado (caso A)
    REJECTED = "rejected"


@dataclass(frozen=True)
class IncorporationResult:
    outcome: Outcome
    snapshot_version: int
    violations: tuple[Violation, ...] = ()
    new_currencies: int = 0
    updated_currencies: int = 0
    names: int = 0  # localizaciones nuevas y actualizadas
    new_associations: int = 0
    updated_associations: int = 0
    locale_snapshot_version: int | None = None
    country_snapshot_version: int | None = None  # la vigente al incorporar


def incorporate_snapshot(
    document: Mapping[str, Any], repository: CurrencyRepository, policy: RequiredLocales
) -> IncorporationResult:
    version: int = document["snapshot_version"]
    try:
        with repository.transaction() as tx:
            decision = evaluate_snapshot(document, tx.history())
            if decision.is_noop:
                return IncorporationResult(Outcome.NOOP, version)
            if decision.rejected:
                return IncorporationResult(Outcome.REJECTED, version, decision.violations)

            locales, countries = tx.locale_catalog(), tx.country_catalog()
            plan = plan_catalog_changes(
                incoming_from(document), tx.current_state(), locales, countries, policy
            )
            if (
                not plan.ok
                or locales.snapshot_version is None
                or countries.snapshot_version is None
            ):
                return IncorporationResult(Outcome.REJECTED, version, plan.violations)

            tx.insert_snapshot(
                document, locales.snapshot_version, countries.snapshot_version, policy.version
            )
            tx.insert_currencies(plan.new_currencies, version)
            tx.update_currencies(plan.updated_currencies, version)
            tx.insert_names(plan.new_names)
            tx.update_names(plan.updated_names)
            tx.insert_associations(plan.new_associations, version)
            tx.update_associations(plan.updated_associations, version)
            changed = {c.currency_id for c in (*plan.new_currencies, *plan.updated_currencies)}
            touched = {n.currency_id for n in (*plan.new_names, *plan.updated_names)}
            tx.touch_currencies(sorted(touched - changed), version)
            tx.check_constraints()
    except ConstraintRejected as error:  # la transacción ya se deshizo
        rule = RULE_BY_CONSTRAINT.get(error.constraint or "", "RNF-5")
        message = f"la base de datos rechazó el estado final del catálogo: {error}"
        return IncorporationResult(Outcome.REJECTED, version, (Violation(rule, message),))
    return IncorporationResult(
        Outcome.INCORPORATED,
        version,
        new_currencies=len(plan.new_currencies),
        updated_currencies=len(plan.updated_currencies),
        names=len(plan.new_names) + len(plan.updated_names),
        new_associations=len(plan.new_associations),
        updated_associations=len(plan.updated_associations),
        locale_snapshot_version=locales.snapshot_version,
        country_snapshot_version=countries.snapshot_version,
    )
