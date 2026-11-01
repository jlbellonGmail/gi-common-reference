"""Atajos para las pruebas del dominio de Countries: estado vigente a partir de un snapshot."""

from typing import Any

from gi_common_reference.countries.domain.catalog import (
    CatalogPlan,
    incoming_from,
    plan_catalog_changes,
)
from gi_common_reference.countries.domain.model import (
    CatalogState,
    CodeKind,
    FlagRecord,
    LocaleCatalog,
    RegionCatalog,
)
from gi_common_reference.countries.domain.policy import RequiredLocales
from tests.fixtures.countries import POLICY, locale_catalog, region_catalog


def published(
    document: dict[str, Any], history: tuple[tuple[CodeKind, str, str], ...] = ()
) -> CatalogState:
    """Estado vigente tras incorporar `document` (sus declaraciones ya no cuentan)."""
    incoming = incoming_from(document)
    flags = [FlagRecord(f.country_id, f.asset_path, f.sha256, None) for f in incoming.flags]
    flags += [FlagRecord(e.country_id, None, None, e.reason) for e in incoming.flag_exceptions]
    return CatalogState(
        countries=incoming.countries,
        names=incoming.names,
        flags=tuple(flags),
        historical_codes=history,
    )


def plan(
    document: dict[str, Any],
    current: CatalogState | None = None,
    *,
    locales: LocaleCatalog | None = None,
    regions: RegionCatalog | None = None,
    policy: RequiredLocales = POLICY,
) -> CatalogPlan:
    return plan_catalog_changes(
        incoming_from(document),
        current if current is not None else CatalogState(),
        locales if locales is not None else locale_catalog(),
        regions if regions is not None else region_catalog(),
        policy,
    )


def rules(result: CatalogPlan) -> set[str]:
    return {violation.rule for violation in result.violations}


def messages(result: CatalogPlan) -> str:
    return "\n".join(f"{v.rule}: {v.message}" for v in result.violations)
