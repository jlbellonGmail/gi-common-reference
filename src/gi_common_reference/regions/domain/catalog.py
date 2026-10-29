"""Validación del catálogo de un snapshot contra el estado vigente, Locale y la política.

Función pura (sin base de datos ni red). Sigue los pasos 3 a 7 de la incorporación del plan y se
detiene en el primer paso que falla, informando todas las violaciones de ese paso:

3. Contexto de Locale: RF-31, RF-33, RF-38.
4. Identidad y completitud: RF-2, RF-22, RF-23.
5. Códigos: RF-3, RF-4, RF-22, RF-39, RF-40, RF-41, RF-42.
6. Jerarquía y ciclo de vida: RF-5, RF-7, RF-27, RF-36.
7. Localizaciones: RF-9, RF-10, RF-11, RF-13, RF-28, RF-32, RF-33.

Si todo pasa devuelve el plan de cambios (RF-6, RF-24, RF-34, RF-39).
"""

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from gi_common_reference.regions.domain.codes import is_valid_code
from gi_common_reference.regions.domain.model import (
    STATUSES,
    CatalogState,
    EntityType,
    LocaleCatalog,
    NameRecord,
    Reassignment,
    Reclassification,
    Recoding,
    RegionRecord,
    SubregionRecord,
    Violation,
)
from gi_common_reference.regions.domain.policy import RequiredLocales

UUID_FORMAT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
LABELS: dict[str, str] = {"region": "Region", "subregion": "Subregion"}


@dataclass(frozen=True)
class IncomingCatalog:
    """El contenido de un snapshot ya validado por schema, como tipos del dominio."""

    regions: tuple[RegionRecord, ...] = ()
    subregions: tuple[SubregionRecord, ...] = ()
    region_names: tuple[NameRecord, ...] = ()
    subregion_names: tuple[NameRecord, ...] = ()
    recodings: tuple[Recoding, ...] = ()
    reassignments: tuple[Reassignment, ...] = ()


@dataclass(frozen=True)
class CatalogPlan:
    """Violaciones, o bien los cambios a aplicar en el orden de escritura del plan (paso 8)."""

    violations: tuple[Violation, ...] = ()
    new_regions: tuple[RegionRecord, ...] = ()
    updated_regions: tuple[RegionRecord, ...] = ()
    new_subregions: tuple[SubregionRecord, ...] = ()
    updated_subregions: tuple[SubregionRecord, ...] = ()
    reclassifications: tuple[Reclassification, ...] = ()
    recodings: tuple[Recoding, ...] = ()
    new_region_names: tuple[NameRecord, ...] = ()
    updated_region_names: tuple[NameRecord, ...] = ()
    new_subregion_names: tuple[NameRecord, ...] = ()
    updated_subregion_names: tuple[NameRecord, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def is_empty(self) -> bool:
        """El snapshot no cambia nada respecto del estado vigente (solo cambia la versión)."""
        return self.ok and not any(
            (
                self.new_regions,
                self.updated_regions,
                self.new_subregions,
                self.updated_subregions,
                self.reclassifications,
                self.recodings,
                self.new_region_names,
                self.updated_region_names,
                self.new_subregion_names,
                self.updated_subregion_names,
            )
        )


def incoming_from(document: Mapping[str, Any]) -> IncomingCatalog:
    """Contenido de un documento de snapshot ya validado por schema; lo faltante queda vacío."""
    return IncomingCatalog(
        regions=tuple(
            RegionRecord(
                _text(item.get("region_id")),
                _optional(item.get("code")),
                _text(item.get("status")),
                _optional(item.get("replacement_region_id")),
            )
            for item in document.get("regions", ())
        ),
        subregions=tuple(
            SubregionRecord(
                _text(item.get("subregion_id")),
                _text(item.get("region_id")),
                _optional(item.get("code")),
                _text(item.get("status")),
                _optional(item.get("replacement_subregion_id")),
            )
            for item in document.get("subregions", ())
        ),
        region_names=_names(document.get("region_names", ()), "region_id"),
        subregion_names=_names(document.get("subregion_names", ()), "subregion_id"),
        recodings=tuple(
            Recoding(
                _text(item.get("entity_type")),
                _text(item.get("entity_id")),
                _text(item.get("previous_code")),
                _text(item.get("new_code")),
                item.get("provenance"),
            )
            for item in document.get("recodings", ())
        ),
        reassignments=tuple(
            Reassignment(
                _text(item.get("entity_type")),
                _text(item.get("entity_id")),
                _text(item.get("code")),
                item.get("provenance"),
            )
            for item in document.get("code_reassignments", ())
        ),
    )


@dataclass(frozen=True)
class _Entity:
    """Vista común de Region y Subregion para las reglas que valen para ambas."""

    kind: EntityType
    entity_id: str
    code: str | None
    status: str
    replacement: str | None


@dataclass
class _Context:
    incoming: IncomingCatalog
    current: CatalogState
    locales: LocaleCatalog
    policy: RequiredLocales
    entities: list[_Entity] = field(default_factory=list)
    published: dict[tuple[EntityType, str], _Entity] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.entities = [*map(_region_entity, self.incoming.regions)]
        self.entities += [*map(_subregion_entity, self.incoming.subregions)]
        current = [*map(_region_entity, self.current.regions)]
        current += [*map(_subregion_entity, self.current.subregions)]
        self.published = {(e.kind, e.entity_id): e for e in current}


Check = Callable[[_Context], list[Violation]]


def plan_catalog_changes(
    incoming: IncomingCatalog,
    current: CatalogState,
    locales: LocaleCatalog,
    policy: RequiredLocales,
) -> CatalogPlan:
    context = _Context(incoming, current, locales, policy)
    checks: tuple[Check, ...] = (
        _check_locale_context,
        _check_identity,
        _check_codes,
        _check_hierarchy,
        _check_names,
    )
    for check in checks:
        violations = check(context)
        if violations:
            return CatalogPlan(violations=tuple(violations))
    return _plan(incoming, current)


# --- paso 3: contexto de Locale ---------------------------------------------------------------


def _check_locale_context(context: _Context) -> list[Violation]:
    if context.locales.snapshot_version is None:
        message = "el catálogo de Locale no tiene ningún snapshot incorporado"
        return [Violation("RF-38", message)]
    locales = {item.locale_id: item for item in context.locales.locales}
    violations: list[Violation] = []
    for required in context.policy.locales:
        found = locales.get(required.locale_id)
        if found is None:
            message = (
                f"el locale obligatorio {required.code} ({required.locale_id}) no existe en "
                f"el catálogo de Locale"
            )
            violations.append(Violation("RF-31", message))
        elif found.code != required.code:
            message = (
                f"el locale obligatorio {required.locale_id} tiene el código {found.code} en "
                f"Locale, no {required.code}: la política no coincide con el catálogo"
            )
            violations.append(Violation("RF-31", message))
        elif found.status != "active":
            message = f"el locale obligatorio {required.code} ({required.locale_id}) es inactive"
            violations.append(Violation("RF-33", message))
    return violations


# --- paso 4: identidad y completitud ------------------------------------------------------------


def _check_identity(context: _Context) -> list[Violation]:
    violations: list[Violation] = []
    incoming = context.incoming
    counts = Counter((e.kind, e.entity_id) for e in context.entities)
    for (kind, entity_id), count in sorted(counts.items()):
        if count > 1:
            message = f"el {kind}_id {entity_id!r} está repetido en el snapshot"
            violations.append(Violation("RF-2", message))

    region_ids = {r.region_id for r in incoming.regions}
    subregion_ids = {s.subregion_id for s in incoming.subregions}
    published_ids = {entity_id for _, entity_id in context.published}
    for shared in sorted(region_ids & subregion_ids):
        message = f"el id {shared} se usa a la vez como Region y como Subregion"
        violations.append(Violation("RF-23", message))

    for entity in context.entities:
        if (entity.kind, entity.entity_id) in context.published:
            continue
        if not UUID_FORMAT.fullmatch(entity.entity_id):
            message = (
                f"{LABELS[entity.kind]} nueva con código {entity.code}: su id "
                f"{entity.entity_id!r} no es un UUID en minúsculas"
            )
            violations.append(Violation("RF-23", message))
        elif entity.entity_id in published_ids:
            message = (
                f"{LABELS[entity.kind]} nueva reutiliza el id {entity.entity_id}, ya usado por "
                f"otra entidad del catálogo"
            )
            violations.append(Violation("RF-23", message))

    present = set(counts)
    for kind, entity_id in sorted(context.published):
        if (kind, entity_id) not in present:
            code = context.published[(kind, entity_id)].code
            message = f"falta la {LABELS[kind]} publicada {entity_id} (código {code})"
            violations.append(Violation("RF-22", message))

    for kind, published_names, names in (
        ("region", context.current.region_names, incoming.region_names),
        ("subregion", context.current.subregion_names, incoming.subregion_names),
    ):
        pairs = {(n.entity_id, n.locale_id) for n in names}
        for name in published_names:
            if (name.entity_id, name.locale_id) not in pairs:
                message = (
                    f"falta el nombre publicado de la {LABELS[kind]} {name.entity_id} "
                    f"en el locale {name.locale_id}"
                )
                violations.append(Violation("RF-22", message))
    return violations


# --- paso 5: códigos ----------------------------------------------------------------------------


def _check_codes(context: _Context) -> list[Violation]:
    violations = [
        Violation(
            "RF-3",
            f"{LABELS[e.kind]} {e.entity_id}: el código {e.code!r} no tiene 3 dígitos",
        )
        for e in context.entities
        if e.code is not None and not is_valid_code(e.code)
    ]
    if violations:
        return violations
    violations += _check_recodings(context)
    violations += _check_reassignments(context)
    violations += _check_final_codes(context)
    return violations


def _check_recodings(context: _Context) -> list[Violation]:
    violations: list[Violation] = []
    final: dict[tuple[str, str], _Entity] = {(e.kind, e.entity_id): e for e in context.entities}
    published_by_key: dict[tuple[str, str], _Entity] = dict(context.published.items())
    declared: dict[tuple[str, str], Recoding] = {}
    for item in context.incoming.recodings:
        key = (item.entity_type, item.entity_id)
        label = f"recodificación de {item.entity_type} {item.entity_id}"
        if key in declared:
            violations.append(Violation("RF-39", f"{label}: está declarada más de una vez"))
            continue
        declared[key] = item
        published = published_by_key.get(key)
        if published is None:
            message = f"{label}: el id no es de una {item.entity_type} publicada"
            violations.append(Violation("RF-39", message))
            continue
        if not _has_provenance(item.provenance):
            violations.append(Violation("RF-40", f"{label}: no tiene referencia de provenance"))
        if item.previous_code != published.code:
            message = (
                f"{label}: declara el código anterior {item.previous_code!r}, pero el vigente "
                f"es {published.code!r}"
            )
            violations.append(Violation("RF-40", message))
        if item.previous_code == item.new_code:
            violations.append(Violation("RF-39", f"{label}: no cambia el código"))
        incoming = final.get(key)
        if incoming is not None and incoming.code != item.new_code:
            message = (
                f"{label}: declara el código nuevo {item.new_code!r}, pero el snapshot trae "
                f"{incoming.code!r}"
            )
            violations.append(Violation("RF-39", message))

    for key, published in sorted(context.published.items()):
        incoming = final.get(key)
        if incoming is None or incoming.code == published.code or key in declared:
            continue
        label = f"{LABELS[key[0]]} {key[1]}"
        if published.code is None:
            message = (
                f"{label}: asigna un primer código {incoming.code!r} a un id publicado sin "
                f"código; no es una recodificación y no se admite"
            )
        elif incoming.code is None:
            message = (
                f"{label}: retira su código vigente {published.code!r}; retirar un código no es "
                f"una recodificación y no se admite"
            )
        else:
            message = (
                f"{label}: cambia su código vigente de {published.code!r} a {incoming.code!r} "
                f"sin declarar una recodificación"
            )
        violations.append(Violation("RF-22", message))
    return violations


def _check_reassignments(context: _Context) -> list[Violation]:
    """RF-41: un id solo recibe un código vigente o histórico de otro id si lo declara."""
    holders: dict[str, set[tuple[EntityType, str]]] = {}
    for (kind, entity_id), entity in context.published.items():
        if entity.code is not None:
            holders.setdefault(entity.code, set()).add((kind, entity_id))
    for kind, entity_id, code in context.current.historical_codes:
        holders.setdefault(code, set()).add((kind, entity_id))

    needed: set[tuple[str, str, str]] = set()
    for entity in context.entities:
        key = (entity.kind, entity.entity_id)
        published = context.published.get(key)
        if entity.code is None or (published is not None and published.code == entity.code):
            continue
        if holders.get(entity.code, set()) - {key}:
            needed.add((entity.kind, entity.entity_id, entity.code))

    violations: list[Violation] = []
    declared: set[tuple[str, str, str]] = set()
    for item in context.incoming.reassignments:
        key3 = (item.entity_type, item.entity_id, item.code)
        label = f"reasignación del código {item.code} a {item.entity_type} {item.entity_id}"
        if key3 in declared:
            violations.append(Violation("RF-41", f"{label}: está declarada más de una vez"))
        elif key3 not in needed:
            message = (
                f"{label}: no corresponde (el id no recibe ese código o ningún otro id lo tuvo)"
            )
            violations.append(Violation("RF-41", message))
        elif not _has_provenance(item.provenance):
            violations.append(Violation("RF-41", f"{label}: no tiene referencia de provenance"))
        declared.add(key3)
    for needed_kind, needed_id, code in sorted(needed - declared):
        message = (
            f"{LABELS[needed_kind]} {needed_id} recibe el código {code}, vigente o histórico "
            f"de otro id, sin declarar la reasignación"
        )
        violations.append(Violation("RF-41", message))
    return violations


def _check_final_codes(context: _Context) -> list[Violation]:
    """RF-3, RF-4 sobre el estado final del snapshot completo (RF-42)."""
    violations: list[Violation] = []
    active: dict[EntityType, Counter[str]] = {"region": Counter(), "subregion": Counter()}
    for entity in context.entities:
        if entity.status == "active" and entity.code is not None:
            active[entity.kind][entity.code] += 1
    for kind, counts in active.items():
        for code, count in sorted(counts.items()):
            if count > 1:
                message = f"{count} {LABELS[kind]} active comparten el código {code}"
                violations.append(Violation("RF-3", message))
    for code in sorted(set(active["region"]) & set(active["subregion"])):
        message = f"el código {code} es a la vez de una Region y de una Subregion active"
        violations.append(Violation("RF-4", message))
    return violations


# --- paso 6: jerarquía y ciclo de vida ----------------------------------------------------------


def _check_hierarchy(context: _Context) -> list[Violation]:
    violations: list[Violation] = []
    regions = {r.region_id: r for r in context.incoming.regions}
    for entity in context.entities:
        if entity.status not in STATUSES:
            message = (
                f"{LABELS[entity.kind]} {entity.entity_id}: status {entity.status!r} fuera de "
                f"la convención común ({', '.join(STATUSES)})"
            )
            violations.append(Violation("RF-7", message))
    for sub in context.incoming.subregions:
        parent = regions.get(sub.region_id)
        if parent is None:
            message = f"Subregion {sub.subregion_id}: su Region {sub.region_id} no existe"
            violations.append(Violation("RF-5", message))
        elif sub.status == "active" and parent.status == "inactive":
            message = (
                f"Subregion active {sub.subregion_id} (código {sub.code}) dentro de la Region "
                f"inactive {parent.region_id}"
            )
            violations.append(Violation("RF-36", message))
    violations += _check_replacements(context, "region")
    violations += _check_replacements(context, "subregion")
    return violations


def _check_replacements(context: _Context, kind: EntityType) -> list[Violation]:
    entities = [e for e in context.entities if e.kind == kind]
    same_type = {e.entity_id for e in entities}
    other_type = {e.entity_id for e in context.entities if e.kind != kind}
    label = LABELS[kind]
    violations: list[Violation] = []
    for entity in entities:
        target = entity.replacement
        if target is None:
            continue
        if entity.status == "active":
            message = f"{label} active {entity.entity_id} no puede tener reemplazo"
            violations.append(Violation("RF-27", message))
        if target == entity.entity_id:
            violations.append(Violation("RF-27", f"{label} {entity.entity_id}: reemplazo a sí"))
        elif target in other_type:
            message = f"{label} {entity.entity_id}: el reemplazo {target} es de otro tipo"
            violations.append(Violation("RF-27", message))
        elif target not in same_type:
            message = f"{label} {entity.entity_id}: el reemplazo {target} no existe"
            violations.append(Violation("RF-27", message))
    next_of = {e.entity_id: e.replacement for e in entities}
    reported: set[str] = set()
    for start in sorted(next_of):
        cycle = _cycle_from(start, next_of)
        if cycle and not reported.intersection(cycle):
            reported.update(cycle)
            path = " → ".join([*cycle, cycle[0]])
            violations.append(Violation("RF-27", f"ciclo de reemplazos de {label}: {path}"))
    return violations


def _cycle_from(start: str, next_of: Mapping[str, str | None]) -> list[str]:
    """Ids del ciclo al que llega `start` siguiendo los reemplazos; vacío si no hay ciclo."""
    path: list[str] = []
    node: str | None = start
    while node is not None and node in next_of and node not in path:
        path.append(node)
        node = next_of[node]
    if node is None or node not in path:
        return []
    cycle = path[path.index(node) :]
    return [] if len(cycle) == 1 else cycle  # el reemplazo a sí mismo se reporta aparte


# --- paso 7: localizaciones ---------------------------------------------------------------------


def _check_names(context: _Context) -> list[Violation]:
    violations: list[Violation] = []
    locales = {item.locale_id: item for item in context.locales.locales}
    for kind, names, published, entity_ids in (
        (
            "region",
            context.incoming.region_names,
            context.current.region_names,
            [r.region_id for r in context.incoming.regions],
        ),
        (
            "subregion",
            context.incoming.subregion_names,
            context.current.subregion_names,
            [s.subregion_id for s in context.incoming.subregions],
        ),
    ):
        violations += _check_names_of(kind, names, published, entity_ids, locales, context.policy)
    return violations


def _check_names_of(
    kind: str,
    names: Sequence[NameRecord],
    published: Sequence[NameRecord],
    entity_ids: Iterable[str],
    locales: Mapping[str, Any],
    policy: RequiredLocales,
) -> list[Violation]:
    label = LABELS[kind]
    entities = set(entity_ids)
    published_pairs = {(n.entity_id, n.locale_id) for n in published}
    violations: list[Violation] = []
    for (entity_id, locale_id), count in sorted(
        Counter((n.entity_id, n.locale_id) for n in names).items()
    ):
        if count > 1:
            message = f"{label} {entity_id} tiene {count} nombres para el locale {locale_id}"
            violations.append(Violation("RF-9", message))
    for name in names:
        where = f"nombre de {label} {name.entity_id} en {name.locale_id}"
        if name.entity_id not in entities:
            violations.append(Violation("RF-10", f"{where}: la {label} no está en el snapshot"))
        locale = locales.get(name.locale_id)
        if locale is None:
            violations.append(Violation("RF-28", f"{where}: el locale no existe en Locale"))
        elif locale.status != "active" and (name.entity_id, name.locale_id) not in published_pairs:
            message = f"{where}: nombre nuevo con un locale inactive"
            violations.append(Violation("RF-33", message))
        if not name.name or name.name != name.name.strip():
            message = f"{where}: {name.name!r} está vacío o tiene espacios al inicio o al final"
            violations.append(Violation("RF-11", message))
    pairs = {(n.entity_id, n.locale_id) for n in names}
    for entity_id in sorted(entities):
        for required in policy.locales:
            if (entity_id, required.locale_id) not in pairs:
                message = (
                    f"{label} {entity_id} no tiene nombre en el locale obligatorio "
                    f"{required.code} ({required.locale_id})"
                )
                violations.append(Violation("RF-32", message))
    return violations


# --- plan ---------------------------------------------------------------------------------------


def _plan(incoming: IncomingCatalog, current: CatalogState) -> CatalogPlan:
    regions = {r.region_id: r for r in current.regions}
    subregions = {s.subregion_id: s for s in current.subregions}
    reclassifications = tuple(
        Reclassification(s.subregion_id, subregions[s.subregion_id].region_id, s.region_id)
        for s in incoming.subregions
        if s.subregion_id in subregions and subregions[s.subregion_id].region_id != s.region_id
    )
    new_region_names, updated_region_names = _name_changes(
        incoming.region_names, current.region_names
    )
    new_subregion_names, updated_subregion_names = _name_changes(
        incoming.subregion_names, current.subregion_names
    )
    return CatalogPlan(
        new_regions=tuple(r for r in incoming.regions if r.region_id not in regions),
        updated_regions=tuple(
            r for r in incoming.regions if r.region_id in regions and r != regions[r.region_id]
        ),
        new_subregions=tuple(s for s in incoming.subregions if s.subregion_id not in subregions),
        updated_subregions=tuple(
            s
            for s in incoming.subregions
            if s.subregion_id in subregions and s != subregions[s.subregion_id]
        ),
        reclassifications=reclassifications,
        recodings=incoming.recodings,
        new_region_names=new_region_names,
        updated_region_names=updated_region_names,
        new_subregion_names=new_subregion_names,
        updated_subregion_names=updated_subregion_names,
    )


def _name_changes(
    incoming: Sequence[NameRecord], published: Sequence[NameRecord]
) -> tuple[tuple[NameRecord, ...], tuple[NameRecord, ...]]:
    current = {(n.entity_id, n.locale_id): n.name for n in published}
    new = tuple(n for n in incoming if (n.entity_id, n.locale_id) not in current)
    updated = tuple(
        n
        for n in incoming
        if (n.entity_id, n.locale_id) in current and current[(n.entity_id, n.locale_id)] != n.name
    )
    return new, updated


# --- utilidades ---------------------------------------------------------------------------------


def _region_entity(record: RegionRecord) -> _Entity:
    return _Entity(
        "region", record.region_id, record.code, record.status, record.replacement_region_id
    )


def _subregion_entity(record: SubregionRecord) -> _Entity:
    return _Entity(
        "subregion",
        record.subregion_id,
        record.code,
        record.status,
        record.replacement_subregion_id,
    )


def _has_provenance(provenance: Any) -> bool:
    """RF-40, RF-41, S-11: una referencia a la fuente de autoridad, con `source` no vacío."""
    if not isinstance(provenance, Mapping):
        return False
    source = provenance.get("source")
    return isinstance(source, str) and bool(source.strip())


def _names(items: Iterable[Mapping[str, Any]], key: str) -> tuple[NameRecord, ...]:
    return tuple(
        NameRecord(_text(item.get(key)), _text(item.get("locale_id")), _text(item.get("name")))
        for item in items
    )


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional(value: object) -> str | None:
    return value if isinstance(value, str) else None
