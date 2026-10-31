"""Diff legible de un snapshot contra el estado vigente (RF-30).

Función pura sobre el plan de cambios: cada entrada dice qué cambia, en qué país y de qué a
qué, para la revisión humana previa a la aprobación. No modifica nada.
"""

from dataclasses import dataclass

from gi_common_reference.countries.domain.catalog import CatalogPlan
from gi_common_reference.countries.domain.model import CatalogState, CountryRecord, FlagRecord


@dataclass(frozen=True)
class DiffEntry:
    category: str  # alta | códigos | clasificación | atributos | estado | nombre | bandera
    country_id: str
    alpha2: str  # código vigente tras aplicar el snapshot
    detail: str


@dataclass(frozen=True)
class CatalogDiff:
    entries: tuple[DiffEntry, ...]

    def lines(self) -> list[str]:
        return [
            f"{entry.category:<14} {entry.alpha2} ({entry.country_id}): {entry.detail}"
            for entry in self.entries
        ]


def diff_catalog(plan: CatalogPlan, current: CatalogState) -> CatalogDiff:
    published = {c.country_id: c for c in current.countries}
    alpha2_of = {c.country_id: c.alpha2 for c in current.countries}
    alpha2_of.update({c.country_id: c.alpha2 for c in plan.new_countries})
    alpha2_of.update({c.country_id: c.alpha2 for c in plan.updated_countries})

    entries: list[DiffEntry] = []
    for new in plan.new_countries:
        detail = f"{new.alpha2}/{new.alpha3}/{new.numeric_code}, status {new.status}"
        entries.append(DiffEntry("alta", new.country_id, new.alpha2, detail))
    for updated in plan.updated_countries:
        entries += _country_changes(published[updated.country_id], updated)
    for name in plan.new_names:
        detail = f"nuevo [{name.locale_id}] {name.name}"
        entries.append(DiffEntry("nombre", name.country_id, alpha2_of[name.country_id], detail))
    previous_names = {(n.country_id, n.locale_id): n for n in current.names}
    for name in plan.updated_names:
        before = previous_names[(name.country_id, name.locale_id)]
        detail = f"[{name.locale_id}] {_names(before.name, before.official_name)} → " + _names(
            name.name, name.official_name
        )
        entries.append(DiffEntry("nombre", name.country_id, alpha2_of[name.country_id], detail))
    previous_flags = {f.country_id: f for f in current.flags}
    for flag in plan.new_flags:
        entries.append(
            DiffEntry(
                "bandera", flag.country_id, alpha2_of[flag.country_id], f"nueva: {_flag(flag)}"
            )
        )
    for flag in plan.updated_flags:
        detail = f"{_flag(previous_flags[flag.country_id])} → {_flag(flag)}"
        entries.append(DiffEntry("bandera", flag.country_id, alpha2_of[flag.country_id], detail))
    return CatalogDiff(tuple(entries))


def _country_changes(before: CountryRecord, after: CountryRecord) -> list[DiffEntry]:
    entries: list[DiffEntry] = []

    def add(category: str, detail: str) -> None:
        entries.append(DiffEntry(category, after.country_id, after.alpha2, detail))

    if before.triple != after.triple:
        old = f"{before.alpha2}/{before.alpha3}/{before.numeric_code}"
        new = f"{after.alpha2}/{after.alpha3}/{after.numeric_code}"
        add("códigos", f"{old} → {new}")
    if (before.region_id, before.subregion_id) != (after.region_id, after.subregion_id):
        add(
            "clasificación",
            f"region_id {before.region_id} → {after.region_id}; "
            f"subregion_id {before.subregion_id} → {after.subregion_id}",
        )
    if before.calling_code != after.calling_code:
        add("atributos", f"calling_code {before.calling_code} → {after.calling_code}")
    if (before.status, before.replacement_country_ids) != (
        after.status,
        after.replacement_country_ids,
    ):
        added = sorted(set(after.replacement_country_ids) - set(before.replacement_country_ids))
        removed = sorted(set(before.replacement_country_ids) - set(after.replacement_country_ids))
        detail = f"status {before.status} → {after.status}"
        if added or removed:
            detail += f"; reemplazos: agrega {added or '—'}, quita {removed or '—'}"
        add("estado", detail)
    return entries


def _names(name: str, official_name: str | None) -> str:
    return name if official_name is None else f"{name} ({official_name})"


def _flag(flag: FlagRecord) -> str:
    if flag.exception_reason is not None:
        return f"excepción «{flag.exception_reason}»"
    return f"{flag.asset_path} {flag.sha256}"
