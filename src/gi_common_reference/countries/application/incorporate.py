"""Caso de uso: incorporar un snapshot de Countries en una única transacción (RF-20–RF-25, RF-27).

El documento ya pasó el schema. Aquí se aplican, en el orden del plan, el digest y la clasificación
contra el historial, las reglas del catálogo contra el estado vigente, Locale, Regions y la política
de locales obligatorios, y la verificación de los assets de bandera; si todo pasa se escribe en un
orden fijo y se fuerzan las constraints diferidas antes del commit. Una constraint violada es un
rechazo, no un error operativo (D17).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from gi_common_reference.countries.application.flags import verify_flag_declarations
from gi_common_reference.countries.domain.catalog import incoming_from, plan_catalog_changes
from gi_common_reference.countries.domain.errors import ConstraintRejected
from gi_common_reference.countries.domain.model import Violation
from gi_common_reference.countries.domain.policy import RequiredLocales
from gi_common_reference.countries.domain.ports import CountryRepository, FlagStore
from gi_common_reference.countries.domain.snapshot import evaluate_snapshot


class Outcome(StrEnum):
    INCORPORATED = "incorporated"
    NOOP = "noop"  # snapshot ya incorporado (caso A)
    REJECTED = "rejected"


@dataclass(frozen=True)
class IncorporationResult:
    outcome: Outcome
    snapshot_version: int
    violations: tuple[Violation, ...] = ()
    new_countries: int = 0
    updated: int = 0  # países, nombres y banderas actualizados
    recodings: int = 0
    locale_snapshot_version: int | None = None
    region_snapshot_version: int | None = None  # la vigente al incorporar


def incorporate_snapshot(
    document: Mapping[str, Any],
    repository: CountryRepository,
    policy: RequiredLocales,
    flags: FlagStore,
) -> IncorporationResult:
    version: int = document["snapshot_version"]
    try:
        with repository.transaction() as tx:
            decision = evaluate_snapshot(document, tx.history())
            if decision.is_noop:
                return IncorporationResult(Outcome.NOOP, version)
            if decision.rejected:
                return IncorporationResult(Outcome.REJECTED, version, decision.violations)

            locales, regions = tx.locale_catalog(), tx.region_catalog()
            incoming = incoming_from(document)
            plan = plan_catalog_changes(incoming, tx.current_state(), locales, regions, policy)
            violations = list(plan.violations)
            if plan.ok:
                violations += verify_flag_declarations(incoming.flags, flags)
            if violations or locales.snapshot_version is None or regions.snapshot_version is None:
                return IncorporationResult(Outcome.REJECTED, version, tuple(violations))

            tx.insert_snapshot(
                document, locales.snapshot_version, regions.snapshot_version, policy.version
            )
            tx.insert_countries(plan.new_countries, version)
            tx.update_countries(plan.updated_countries, version)
            tx.record_recodings(plan.recodings, version)
            tx.insert_names(plan.new_names)
            tx.update_names(plan.updated_names)
            tx.write_flags(plan.new_flags, plan.updated_flags, version)
            inserted = {c.country_id for c in plan.new_countries}
            changed = {c.country_id for c in plan.updated_countries}
            touched = {n.country_id for n in (*plan.new_names, *plan.updated_names)}
            touched |= {f.country_id for f in (*plan.new_flags, *plan.updated_flags)}
            tx.touch_countries(sorted(touched - inserted - changed), version)
            tx.check_constraints()
    except ConstraintRejected as error:  # la transacción ya se deshizo
        rule = "RF-6" if error.foreign else "RNF-5"
        message = f"la base de datos rechazó el estado final del catálogo: {error}"
        return IncorporationResult(Outcome.REJECTED, version, (Violation(rule, message),))
    return IncorporationResult(
        Outcome.INCORPORATED,
        version,
        new_countries=len(plan.new_countries),
        updated=len(plan.updated_countries) + len(plan.updated_names) + len(plan.updated_flags),
        recodings=len(plan.recodings),
        locale_snapshot_version=locales.snapshot_version,
        region_snapshot_version=regions.snapshot_version,
    )
