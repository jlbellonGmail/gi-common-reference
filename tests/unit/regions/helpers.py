"""Atajos para las pruebas del dominio de Regions: estado vigente a partir de un snapshot."""

from typing import Any

from gi_common_reference.regions.domain.catalog import (
    CatalogPlan,
    incoming_from,
    plan_catalog_changes,
)
from gi_common_reference.regions.domain.model import CatalogState, EntityType, LocaleCatalog
from gi_common_reference.regions.domain.policy import RequiredLocales
from tests.fixtures.regions import POLICY, locale_catalog


def published(
    document: dict[str, Any], history: tuple[tuple[EntityType, str, str], ...] = ()
) -> CatalogState:
    """Estado vigente tras incorporar `document` (sus declaraciones ya no cuentan)."""
    incoming = incoming_from(document)
    return CatalogState(
        regions=incoming.regions,
        subregions=incoming.subregions,
        region_names=incoming.region_names,
        subregion_names=incoming.subregion_names,
        historical_codes=history,
    )


def plan(
    document: dict[str, Any],
    current: CatalogState | None = None,
    *,
    locales: LocaleCatalog | None = None,
    policy: RequiredLocales = POLICY,
) -> CatalogPlan:
    return plan_catalog_changes(
        incoming_from(document),
        current if current is not None else CatalogState(),
        locales if locales is not None else locale_catalog(),
        policy,
    )


def rules(result: CatalogPlan) -> set[str]:
    return {violation.rule for violation in result.violations}


def messages(result: CatalogPlan) -> str:
    return "\n".join(f"{v.rule}: {v.message}" for v in result.violations)
