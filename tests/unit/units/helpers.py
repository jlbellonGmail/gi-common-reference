"""Auxiliares de las pruebas de validación del catálogo de Units (T5)."""

import copy
from collections.abc import Callable
from functools import cache
from typing import Any

from gi_common_reference.units.domain.catalog import (
    CatalogPlan,
    incoming_from,
    plan_catalog_changes,
)
from gi_common_reference.units.domain.model import (
    CatalogState,
    LocaleCatalog,
    LocaleInfo,
    UcumTable,
)
from gi_common_reference.units.domain.policy import RequiredLocale, RequiredLocales
from gi_common_reference.units.infrastructure.ucum_reader import load_ucum_table
from tests.fixtures.units import EN, ES, build_snapshot, kind_id, unit_id

POLICY = RequiredLocales(1, (RequiredLocale(EN, "en"), RequiredLocale(ES, "es")))
FR = "0d7c3c0e-5a63-4d6c-9a39-0a0a5a0b0f01"


@cache
def ucum_table() -> UcumTable:
    return load_ucum_table()


def locale_view(
    *extra: LocaleInfo,
    version: int | None = 1,
    en: str = "active",
    es: str = "active",
    en_code: str = "en",
) -> LocaleCatalog:
    return LocaleCatalog(version, (LocaleInfo(EN, en_code, en), LocaleInfo(ES, "es", es), *extra))


def plan(
    document: dict[str, Any],
    current: CatalogState | None = None,
    locales: LocaleCatalog | None = None,
    policy: RequiredLocales = POLICY,
) -> CatalogPlan:
    return plan_catalog_changes(
        document,
        current if current is not None else CatalogState(),
        locales if locales is not None else locale_view(),
        policy,
        ucum_table(),
    )


def published(document: dict[str, Any]) -> CatalogState:
    """Estado vigente que resulta de haber incorporado `document`."""
    incoming = incoming_from(document)
    return CatalogState(
        quantity_kinds=incoming.quantity_kinds,
        units=incoming.units,
        associations=incoming.associations,
        kind_names=incoming.kind_names,
        unit_names=incoming.unit_names,
    )


def rules(result: CatalogPlan) -> set[str]:
    return {violation.rule for violation in result.violations}


def messages(result: CatalogPlan) -> list[str]:
    return [f"{violation.rule}: {violation.message}" for violation in result.violations]


def edit(document: dict[str, Any], change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Copia profunda de `document` modificada por `change`."""
    clone = copy.deepcopy(document)
    change(clone)
    return clone


def unit_row(document: dict[str, Any], key: str) -> dict[str, Any]:
    return next(row for row in document["units"] if row["unit_id"] == unit_id(key))


def kind_row(document: dict[str, Any], code: str) -> dict[str, Any]:
    return next(row for row in document["quantity_kinds"] if row["code"] == code)


def association_row(document: dict[str, Any], code: str, key: str) -> dict[str, Any]:
    return next(
        row
        for row in document["quantity_kind_units"]
        if row["quantity_kind_id"] == kind_id(code) and row["unit_id"] == unit_id(key)
    )


def snapshot() -> dict[str, Any]:
    return build_snapshot()
