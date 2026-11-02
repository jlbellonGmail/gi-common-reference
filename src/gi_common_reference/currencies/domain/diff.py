"""Diff legible de un snapshot contra el estado vigente (RF-41, D22).

Función pura sobre el plan de cambios: cada entrada dice qué cambia, en qué moneda y de qué a qué,
para la revisión humana previa a la aprobación. Los cambios de `status` y de vigencia se muestran
por separado porque son informaciones distintas (RF-10, RF-51). No modifica nada.
"""

from dataclasses import dataclass

from gi_common_reference.currencies.domain.catalog import CatalogPlan
from gi_common_reference.currencies.domain.model import (
    CatalogState,
    CountryCurrencyRecord,
    CurrencyRecord,
)


@dataclass(frozen=True)
class DiffEntry:
    category: str  # alta | atributos | estado | reemplazos | nombre | asociación | vigencia
    subject: str  # código alfabético o «país→moneda»
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


def diff_catalog(plan: CatalogPlan, current: CatalogState) -> CatalogDiff:
    published = {c.currency_id: c for c in current.currencies}
    code_of = {c.currency_id: c.alphabetic_code for c in current.currencies}
    code_of.update({c.currency_id: c.alphabetic_code for c in plan.new_currencies})

    entries: list[DiffEntry] = []
    for new in plan.new_currencies:
        units = "N.A." if new.minor_units is None else str(new.minor_units)
        detail = (
            f"{new.alphabetic_code}/{new.numeric_code}, unidades menores {units}, "
            f"fondos {_yes(new.fund_code)}, status {new.status}"
        )
        entries.append(DiffEntry("alta", new.alphabetic_code, new.currency_id, detail))
    for updated in plan.updated_currencies:
        entries += _currency_changes(published[updated.currency_id], updated, code_of)

    previous_names = {(n.currency_id, n.locale_id): n for n in current.names}
    for name in plan.new_names:
        subject = code_of[name.currency_id]
        entries.append(
            DiffEntry("nombre", subject, name.currency_id, f"nuevo [{name.locale_id}] {name.name}")
        )
    for name in plan.updated_names:
        before = previous_names[(name.currency_id, name.locale_id)]
        detail = f"[{name.locale_id}] {before.name} → {name.name}"
        entries.append(DiffEntry("nombre", code_of[name.currency_id], name.currency_id, detail))

    previous = {a.country_currency_id: a for a in current.associations}
    for association in plan.new_associations:
        entries.append(
            DiffEntry(
                "asociación",
                _pair(association, code_of),
                association.country_currency_id,
                f"nueva, status {association.status}, vigencia {_period(association)}",
            )
        )
    for association in plan.updated_associations:
        entries += _association_changes(
            previous[association.country_currency_id], association, code_of
        )
    return CatalogDiff(tuple(entries))


def _currency_changes(
    before: CurrencyRecord, after: CurrencyRecord, code_of: dict[str, str]
) -> list[DiffEntry]:
    entries: list[DiffEntry] = []

    def add(category: str, detail: str) -> None:
        entries.append(DiffEntry(category, after.alphabetic_code, after.currency_id, detail))

    if before.minor_units != after.minor_units:
        add(
            "atributos",
            f"unidades menores {_units(before.minor_units)} → {_units(after.minor_units)}",
        )
    if before.fund_code != after.fund_code:
        add("atributos", f"fondos {_yes(before.fund_code)} → {_yes(after.fund_code)}")
    if before.status != after.status:
        add("estado", f"status {before.status} → {after.status}")
    if before.replacement_currency_ids != after.replacement_currency_ids:
        added = sorted(
            code_of.get(i, i)
            for i in set(after.replacement_currency_ids) - set(before.replacement_currency_ids)
        )
        removed = sorted(
            code_of.get(i, i)
            for i in set(before.replacement_currency_ids) - set(after.replacement_currency_ids)
        )
        add("reemplazos", f"agrega {added or '—'}, quita {removed or '—'}")
    return entries


def _association_changes(
    before: CountryCurrencyRecord, after: CountryCurrencyRecord, code_of: dict[str, str]
) -> list[DiffEntry]:
    entries: list[DiffEntry] = []
    subject = _pair(after, code_of)

    def add(category: str, detail: str) -> None:
        entries.append(DiffEntry(category, subject, after.country_currency_id, detail))

    if before.status != after.status:
        add("estado", f"status {before.status} → {after.status}")
    if (before.valid_from, before.valid_to) != (after.valid_from, after.valid_to):
        add("vigencia", f"{_period(before)} → {_period(after)}")
    return entries


def _pair(association: CountryCurrencyRecord, code_of: dict[str, str]) -> str:
    return (
        f"{association.country_id}→{code_of.get(association.currency_id, association.currency_id)}"
    )


def _period(association: CountryCurrencyRecord) -> str:
    return f"[{association.valid_from or '-∞'}, {association.valid_to or '+∞'})"


def _units(value: int | None) -> str:
    return "N.A." if value is None else str(value)


def _yes(value: bool) -> str:
    return "sí" if value else "no"
