"""Diff legible de un snapshot contra el estado vigente (RF-45).

Función pura sobre el plan de cambios: cada entrada dice qué cambia, en qué entidad y de qué a qué,
para la revisión humana previa a la aprobación: altas, cambios de `status`, de símbolo, códigos
completados, factores y desplazamientos (valor anterior → nuevo) y nombres. No modifica nada.
"""

from collections.abc import Callable
from dataclasses import dataclass

from gi_common_reference.units.domain.catalog import CatalogPlan
from gi_common_reference.units.domain.model import (
    AssociationRecord,
    CatalogState,
    QuantityKindRecord,
    UnitRecord,
)


@dataclass(frozen=True)
class DiffEntry:
    category: (
        str  # alta | estado | símbolo | código | factor | desplazamiento | asociación | nombre
    )
    subject: str  # «unidad kg», «magnitud mass» o «mass/kg»
    identity: str
    detail: str


@dataclass(frozen=True)
class CatalogDiff:
    entries: tuple[DiffEntry, ...]

    def lines(self) -> list[str]:
        return [
            f"{entry.category:<12} {entry.subject} ({entry.identity}): {entry.detail}"
            for entry in self.entries
        ]


def _none(value: str | None) -> str:
    return "—" if value is None else value


def diff_catalog(plan: CatalogPlan, current: CatalogState) -> CatalogDiff:
    symbols = {u.unit_id: u.symbol for u in current.units}
    symbols.update({u.unit_id: u.symbol for u in (*plan.new_units, *plan.updated_units)})
    codes = {k.quantity_kind_id: k.code for k in current.quantity_kinds}
    codes.update(
        {
            k.quantity_kind_id: k.code
            for k in (*plan.new_quantity_kinds, *plan.updated_quantity_kinds)
        }
    )

    def unit_subject(unit_id: str) -> str:
        return f"unidad {symbols.get(unit_id, unit_id)}"

    def kind_subject(kind_id: str) -> str:
        return f"magnitud {codes.get(kind_id, kind_id)}"

    entries: list[DiffEntry] = []
    previous_units = {u.unit_id: u for u in current.units}
    for unit in plan.new_units:
        detail = (
            f"UCUM {_none(unit.ucum_code)}, UNECE {_none(unit.unece_code)}, "
            f"símbolo {unit.symbol}, status {unit.status}"
        )
        entries.append(DiffEntry("alta", f"unidad {unit.symbol}", unit.unit_id, detail))
    for unit in plan.updated_units:
        entries += _unit_changes(previous_units[unit.unit_id], unit)

    previous_kinds = {k.quantity_kind_id: k for k in current.quantity_kinds}
    for kind in plan.new_quantity_kinds:
        detail = (
            f"{kind.conversion_type}, referencia {symbols.get(kind.reference_unit_id, '?')}, "
            f"status {kind.status}"
        )
        entries.append(DiffEntry("alta", f"magnitud {kind.code}", kind.quantity_kind_id, detail))
    for kind in plan.updated_quantity_kinds:
        entries += _kind_changes(previous_kinds[kind.quantity_kind_id], kind)

    def pair(association: AssociationRecord) -> str:
        kind_code = codes.get(association.quantity_kind_id, "?")
        return f"{kind_code}/{symbols.get(association.unit_id, '?')}"

    previous_associations = {(a.quantity_kind_id, a.unit_id): a for a in current.associations}
    for association in plan.new_associations:
        detail = (
            f"nueva, factor {association.factor}, desplazamiento {association.offset}, "
            f"status {association.status}"
        )
        entries.append(
            DiffEntry(
                "asociación",
                pair(association),
                f"{association.quantity_kind_id}, {association.unit_id}",
                detail,
            )
        )
    for association in plan.updated_associations:
        entries += _association_changes(
            previous_associations[(association.quantity_kind_id, association.unit_id)],
            association,
            pair(association),
        )

    entries += _name_entries(plan, current, unit_subject, kind_subject)
    return CatalogDiff(tuple(entries))


def _unit_changes(before: UnitRecord, after: UnitRecord) -> list[DiffEntry]:
    entries: list[DiffEntry] = []
    subject = f"unidad {after.symbol}"

    def add(category: str, detail: str) -> None:
        entries.append(DiffEntry(category, subject, after.unit_id, detail))

    if before.symbol != after.symbol:
        add("símbolo", f"símbolo {before.symbol} → {after.symbol}")
    if before.ucum_code != after.ucum_code:
        add("código", f"ucum_code {_none(before.ucum_code)} → {_none(after.ucum_code)}")
    if before.unece_code != after.unece_code:
        add("código", f"unece_code {_none(before.unece_code)} → {_none(after.unece_code)}")
    if before.status != after.status:
        add("estado", f"status {before.status} → {after.status}")
    return entries


def _kind_changes(before: QuantityKindRecord, after: QuantityKindRecord) -> list[DiffEntry]:
    entries: list[DiffEntry] = []
    subject = f"magnitud {after.code}"
    if before.status != after.status:
        entries.append(
            DiffEntry(
                "estado",
                subject,
                after.quantity_kind_id,
                f"status {before.status} → {after.status}",
            )
        )
    return entries


def _association_changes(
    before: AssociationRecord, after: AssociationRecord, subject: str
) -> list[DiffEntry]:
    entries: list[DiffEntry] = []
    identity = f"{after.quantity_kind_id}, {after.unit_id}"

    def add(category: str, detail: str) -> None:
        entries.append(DiffEntry(category, subject, identity, detail))

    if before.factor != after.factor:
        add("factor", f"factor {before.factor} → {after.factor}")
    if before.offset != after.offset:
        add("desplazamiento", f"desplazamiento {before.offset} → {after.offset}")
    if before.status != after.status:
        add("estado", f"status {before.status} → {after.status}")
    return entries


def _name_entries(
    plan: CatalogPlan,
    current: CatalogState,
    unit_subject: Callable[[str], str],
    kind_subject: Callable[[str], str],
) -> list[DiffEntry]:
    entries: list[DiffEntry] = []
    previous_kind_names = {(n.quantity_kind_id, n.locale_id): n for n in current.kind_names}
    for kind_name in plan.new_kind_names:
        entries.append(
            DiffEntry(
                "nombre",
                kind_subject(kind_name.quantity_kind_id),
                kind_name.quantity_kind_id,
                f"nuevo [{kind_name.locale_id}] {kind_name.name}",
            )
        )
    for kind_name in plan.updated_kind_names:
        old = previous_kind_names[(kind_name.quantity_kind_id, kind_name.locale_id)]
        entries.append(
            DiffEntry(
                "nombre",
                kind_subject(kind_name.quantity_kind_id),
                kind_name.quantity_kind_id,
                f"[{kind_name.locale_id}] {old.name} → {kind_name.name}",
            )
        )
    previous_unit_names = {(n.unit_id, n.locale_id): n for n in current.unit_names}
    for unit_name in plan.new_unit_names:
        plural = "" if unit_name.plural is None else f", plural {unit_name.plural}"
        entries.append(
            DiffEntry(
                "nombre",
                unit_subject(unit_name.unit_id),
                unit_name.unit_id,
                f"nuevo [{unit_name.locale_id}] {unit_name.name}{plural}",
            )
        )
    for unit_name in plan.updated_unit_names:
        old_unit = previous_unit_names[(unit_name.unit_id, unit_name.locale_id)]
        detail = f"[{unit_name.locale_id}] {old_unit.name} → {unit_name.name}"
        if old_unit.plural != unit_name.plural:
            detail += f", plural {_none(old_unit.plural)} → {_none(unit_name.plural)}"
        entries.append(
            DiffEntry("nombre", unit_subject(unit_name.unit_id), unit_name.unit_id, detail)
        )
    return entries
