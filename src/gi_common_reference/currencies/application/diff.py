"""Caso de uso: diff de un snapshot propuesto contra el catálogo aplicado (RF-41, D22).

Solo lee: no toma el lock exclusivo ni escribe. Reutiliza el plan de cambios del dominio, así que el
diff y la incorporación coinciden.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from gi_common_reference.currencies.application.incorporate import Outcome
from gi_common_reference.currencies.domain.catalog import incoming_from, plan_catalog_changes
from gi_common_reference.currencies.domain.diff import CatalogDiff, diff_catalog
from gi_common_reference.currencies.domain.model import Violation
from gi_common_reference.currencies.domain.policy import RequiredLocales
from gi_common_reference.currencies.domain.ports import CurrencyRepository, IntegrityViolation
from gi_common_reference.currencies.domain.snapshot import evaluate_snapshot


@dataclass(frozen=True)
class PreviewResult:
    """`INCORPORATED` significa que el snapshot se incorporaría; `NOOP`, que ya lo está."""

    outcome: Outcome
    snapshot_version: int
    violations: tuple[Violation, ...] = ()
    diff: CatalogDiff | None = None


def preview_snapshot(
    document: Mapping[str, Any], repository: CurrencyRepository, policy: RequiredLocales
) -> PreviewResult:
    version: int = document["snapshot_version"]
    with repository.inspect() as view:
        decision = evaluate_snapshot(document, view.history())
        if decision.is_noop:
            return PreviewResult(Outcome.NOOP, version)
        if decision.rejected:
            return PreviewResult(Outcome.REJECTED, version, decision.violations)
        current = view.current_state()
        plan = plan_catalog_changes(
            incoming_from(document),
            current,
            view.locale_catalog(),
            view.country_catalog(),
            policy,
        )
    if not plan.ok:
        return PreviewResult(Outcome.REJECTED, version, plan.violations)
    return PreviewResult(Outcome.INCORPORATED, version, diff=diff_catalog(plan, current))


def check_integrity(repository: CurrencyRepository) -> tuple[IntegrityViolation, ...]:
    """Asociaciones `active` abiertas sobre un Country o una Currency `inactive` (RF-19, S-8)."""
    with repository.inspect() as view:
        return tuple(view.integrity_violations())
