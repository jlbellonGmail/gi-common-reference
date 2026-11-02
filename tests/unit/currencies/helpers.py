"""Atajos para las pruebas del dominio de Currency: estado vigente a partir de un snapshot."""

from typing import Any

from gi_common_reference.currencies.domain.catalog import (
    CatalogPlan,
    incoming_from,
    plan_catalog_changes,
)
from gi_common_reference.currencies.domain.model import (
    CatalogState,
    CountryCatalog,
    LocaleCatalog,
)
from gi_common_reference.currencies.domain.policy import RequiredLocales
from tests.fixtures.currencies import POLICY, country_catalog, locale_catalog


def published(document: dict[str, Any]) -> CatalogState:
    """Estado vigente tras incorporar `document`."""
    incoming = incoming_from(document)
    return CatalogState(
        currencies=incoming.currencies,
        names=incoming.names,
        associations=incoming.associations,
    )


def plan(
    document: dict[str, Any],
    current: CatalogState | None = None,
    *,
    locales: LocaleCatalog | None = None,
    countries: CountryCatalog | None = None,
    policy: RequiredLocales = POLICY,
) -> CatalogPlan:
    return plan_catalog_changes(
        incoming_from(document),
        current if current is not None else CatalogState(),
        locales if locales is not None else locale_catalog(),
        countries if countries is not None else country_catalog(),
        policy,
    )


def rules(result: CatalogPlan) -> set[str]:
    return {violation.rule for violation in result.violations}


def messages(result: CatalogPlan) -> str:
    return "\n".join(f"{v.rule}: {v.message}" for v in result.violations)
