"""Validación del catálogo de un snapshot contra el estado vigente, Locale, Regions y la política.

Función pura (sin base de datos ni red). Sigue los pasos 3 a 10 de la incorporación del plan y se
detiene en el primer paso que falla, informando todas las violaciones de ese paso:

3. Contexto de Locale y de Region/Subregion: RF-35, RF-36, RF-47.
4. Identidad y completitud: RF-2, RF-21, RF-45.
5. Códigos: RF-3, RF-4, RF-5, RF-41, RF-42, RF-43, RF-44.
6. Ciclo de vida: RF-5, RF-39, RF-40.
7. Clasificación: RF-6, RF-48.
8. Localizaciones: RF-31, RF-32, RF-35, RF-36.
9. Procedencia: RF-28, RF-29.
10. Banderas declaradas: RF-19, RF-49.

Los pasos 1 y 2 (digest y clasificación A/B/C/D) los evalúa `snapshot.evaluate_snapshot`. Si todo
pasa devuelve el plan de cambios en el orden de escritura.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from gi_common_reference.countries.domain.codes import is_valid_calling_code, is_valid_code
from gi_common_reference.countries.domain.model import (
    CODE_KINDS,
    STATUSES,
    CatalogState,
    CodeTriple,
    CountryRecord,
    FlagDeclaration,
    FlagException,
    FlagRecord,
    LocaleCatalog,
    NameRecord,
    Reassignment,
    Recoding,
    RegionCatalog,
    Violation,
)
from gi_common_reference.countries.domain.policy import RequiredLocales
from gi_common_reference.countries.domain.svg import SVG_MEDIA_TYPE, is_safe_asset_path

UUID_FORMAT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@dataclass(frozen=True)
class IncomingCatalog:
    """El contenido de un snapshot ya validado por schema, como tipos del dominio."""

    countries: tuple[CountryRecord, ...] = ()
    names: tuple[NameRecord, ...] = ()
    flags: tuple[FlagDeclaration, ...] = ()
    flag_exceptions: tuple[FlagException, ...] = ()
    recodings: tuple[Recoding, ...] = ()
    reassignments: tuple[Reassignment, ...] = ()
    region_snapshot_version: int = 0
    provenance: Any = None


@dataclass(frozen=True)
class CatalogPlan:
    """Violaciones, o bien los cambios a aplicar en el orden de escritura del plan (paso 11)."""

    violations: tuple[Violation, ...] = ()
    new_countries: tuple[CountryRecord, ...] = ()
    updated_countries: tuple[CountryRecord, ...] = ()
    recodings: tuple[Recoding, ...] = ()
    new_names: tuple[NameRecord, ...] = ()
    updated_names: tuple[NameRecord, ...] = ()
    new_flags: tuple[FlagRecord, ...] = ()
    updated_flags: tuple[FlagRecord, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def is_empty(self) -> bool:
        """El snapshot no cambia nada respecto del estado vigente (solo cambia la versión)."""
        return self.ok and not any(
            (
                self.new_countries,
                self.updated_countries,
                self.recodings,
                self.new_names,
                self.updated_names,
                self.new_flags,
                self.updated_flags,
            )
        )


def incoming_from(document: Mapping[str, Any]) -> IncomingCatalog:
    """Contenido de un documento de snapshot ya validado por schema; lo faltante queda vacío."""
    return IncomingCatalog(
        countries=tuple(
            CountryRecord(
                _text(item.get("country_id")),
                _text(item.get("alpha2")),
                _text(item.get("alpha3")),
                _text(item.get("numeric_code")),
                _optional(item.get("region_id")),
                _optional(item.get("subregion_id")),
                _optional(item.get("calling_code")),
                _text(item.get("status")),
                _successors(item.get("replacement_country_ids")),
            )
            for item in document.get("countries", ())
        ),
        names=tuple(
            NameRecord(
                _text(item.get("country_id")),
                _text(item.get("locale_id")),
                _text(item.get("name")),
                _optional(item.get("official_name")),
            )
            for item in document.get("country_names", ())
        ),
        flags=tuple(
            FlagDeclaration(
                _text(item.get("country_id")),
                _text(item.get("asset_path")),
                _text(item.get("sha256")),
                _text(item.get("media_type")),
                _text(item.get("source")),
            )
            for item in document.get("flags", ())
        ),
        flag_exceptions=tuple(
            FlagException(_text(item.get("country_id")), _text(item.get("reason")))
            for item in document.get("flag_exceptions", ())
        ),
        recodings=tuple(
            Recoding(
                _text(item.get("country_id")),
                _triple(item.get("previous")),
                _triple(item.get("new")),
                item.get("provenance"),
            )
            for item in document.get("recodings", ())
        ),
        reassignments=tuple(
            Reassignment(
                _text(item.get("country_id")),
                _text(item.get("code_kind")),
                _text(item.get("code")),
                item.get("provenance"),
            )
            for item in document.get("code_reassignments", ())
        ),
        region_snapshot_version=_integer(document.get("region_snapshot_version")),
        provenance=document.get("provenance"),
    )


@dataclass
class _Context:
    incoming: IncomingCatalog
    current: CatalogState
    locales: LocaleCatalog
    regions: RegionCatalog
    policy: RequiredLocales
    published: dict[str, CountryRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.published = {c.country_id: c for c in self.current.countries}


Check = Callable[[_Context], list[Violation]]


def plan_catalog_changes(
    incoming: IncomingCatalog,
    current: CatalogState,
    locales: LocaleCatalog,
    regions: RegionCatalog,
    policy: RequiredLocales,
) -> CatalogPlan:
    context = _Context(incoming, current, locales, regions, policy)
    checks: tuple[Check, ...] = (
        _check_context,
        _check_identity,
        _check_codes,
        _check_lifecycle,
        _check_classification,
        _check_names,
        _check_provenance,
        _check_flag_declarations,
    )
    for check in checks:
        violations = check(context)
        if violations:
            return CatalogPlan(violations=tuple(violations))
    return _plan(incoming, current)


# --- paso 3: contexto de Locale y de Region/Subregion -------------------------------------------


def _check_context(context: _Context) -> list[Violation]:
    violations = _check_locale_context(context) + _check_regions_context(context)
    return violations


def _check_locale_context(context: _Context) -> list[Violation]:
    if context.locales.snapshot_version is None:
        message = "el catálogo de Locale no tiene ningún snapshot incorporado"
        return [Violation("RF-36", message)]
    locales = {item.locale_id: item for item in context.locales.locales}
    violations: list[Violation] = []
    for required in context.policy.locales:
        found = locales.get(required.locale_id)
        if found is None:
            message = (
                f"el locale obligatorio {required.code} ({required.locale_id}) no existe en "
                f"el catálogo de Locale"
            )
            violations.append(Violation("RF-35", message))
        elif found.code != required.code:
            message = (
                f"el locale obligatorio {required.locale_id} tiene el código {found.code} en "
                f"Locale, no {required.code}: la política no coincide con el catálogo"
            )
            violations.append(Violation("RF-35", message))
        elif found.status != "active":
            message = f"el locale obligatorio {required.code} ({required.locale_id}) es inactive"
            violations.append(Violation("RF-36", message))
    return violations


def _check_regions_context(context: _Context) -> list[Violation]:
    """RF-47: la versión de Region/Subregion declarada está incorporada y no es posterior."""
    regions = context.regions
    declared = context.incoming.region_snapshot_version
    if regions.snapshot_version is None:
        message = "el catálogo Region/Subregion no tiene ningún snapshot incorporado"
        return [Violation("RF-47", message)]
    if declared > regions.snapshot_version:
        message = (
            f"la versión {declared} de Region/Subregion declarada es posterior a la vigente "
            f"({regions.snapshot_version})"
        )
        return [Violation("RF-47", message)]
    if declared not in regions.incorporated_versions:
        message = f"la versión {declared} de Region/Subregion declarada no está incorporada"
        return [Violation("RF-47", message)]
    return []


# --- paso 4: identidad y completitud ------------------------------------------------------------


def _check_identity(context: _Context) -> list[Violation]:
    """RF-2, RF-21. RF-45 (un id nuevo nunca usado antes) la sostiene la persistencia: un país
    publicado no se elimina nunca y `country_id` es su clave, así que un id que no está
    publicado jamás fue usado."""
    violations: list[Violation] = []
    incoming = context.incoming
    counts = Counter(c.country_id for c in incoming.countries)
    for country_id, count in sorted(counts.items()):
        if count > 1:
            message = f"el country_id {country_id!r} está repetido en el snapshot"
            violations.append(Violation("RF-2", message))

    for country in incoming.countries:
        if country.country_id in context.published:
            continue
        if not UUID_FORMAT.fullmatch(country.country_id):
            message = (
                f"país nuevo {country.alpha2}: su country_id {country.country_id!r} no es un "
                f"UUID en minúsculas"
            )
            violations.append(Violation("RF-2", message))

    for country_id, published in sorted(context.published.items()):
        if country_id not in counts:
            message = f"falta el país publicado {country_id} (código {published.alpha2})"
            violations.append(Violation("RF-21", message))

    pairs = {(n.country_id, n.locale_id) for n in incoming.names}
    for name in context.current.names:
        if (name.country_id, name.locale_id) not in pairs:
            message = (
                f"falta el nombre publicado del país {name.country_id} en el locale "
                f"{name.locale_id}"
            )
            violations.append(Violation("RF-21", message))

    declared = {f.country_id for f in incoming.flags} | {
        e.country_id for e in incoming.flag_exceptions
    }
    for flag in context.current.flags:
        if flag.country_id not in declared:
            message = f"falta la bandera (o su excepción) publicada del país {flag.country_id}"
            violations.append(Violation("RF-21", message))
    return violations


# --- paso 5: códigos ----------------------------------------------------------------------------


def _check_codes(context: _Context) -> list[Violation]:
    violations: list[Violation] = []
    for country in context.incoming.countries:
        for kind in CODE_KINDS:
            code = country.triple.code(kind)
            if not is_valid_code(kind, code):
                message = (
                    f"país {country.country_id}: el {kind} {code!r} no tiene el formato ISO 3166-1"
                )
                violations.append(Violation("RF-5", message))
    if violations:
        return violations
    violations += _check_recodings(context)
    violations += _check_reassignments(context)
    violations += _check_final_codes(context)
    return violations


def _check_recodings(context: _Context) -> list[Violation]:
    violations: list[Violation] = []
    final = {c.country_id: c for c in context.incoming.countries}
    declared: set[str] = set()
    for item in context.incoming.recodings:
        label = f"recodificación del país {item.country_id}"
        if item.country_id in declared:
            violations.append(Violation("RF-41", f"{label}: está declarada más de una vez"))
            continue
        declared.add(item.country_id)
        published = context.published.get(item.country_id)
        if published is None:
            violations.append(Violation("RF-42", f"{label}: el país no está publicado"))
            continue
        for side, triple in (("anterior", item.previous), ("nueva", item.new)):
            for kind in CODE_KINDS:
                if not is_valid_code(kind, triple.code(kind)):
                    message = f"{label}: el {kind} de la tripleta {side} no tiene formato válido"
                    violations.append(Violation("RF-5", message))
        if not _has_provenance(item.provenance):
            violations.append(Violation("RF-42", f"{label}: no tiene referencia de provenance"))
        if item.previous != published.triple:
            message = (
                f"{label}: declara la tripleta anterior {_show(item.previous)}, pero la vigente "
                f"es {_show(published.triple)}"
            )
            violations.append(Violation("RF-42", message))
        if item.previous == item.new:
            violations.append(Violation("RF-42", f"{label}: no cambia ningún código"))
        incoming = final.get(item.country_id)
        if incoming is not None and incoming.triple != item.new:
            message = (
                f"{label}: declara la tripleta nueva {_show(item.new)}, pero el snapshot trae "
                f"{_show(incoming.triple)}"
            )
            violations.append(Violation("RF-41", message))

    for country_id, published in sorted(context.published.items()):
        incoming = final.get(country_id)
        if incoming is None or incoming.triple == published.triple or country_id in declared:
            continue
        message = (
            f"país {country_id}: cambia su tripleta vigente {_show(published.triple)} por "
            f"{_show(incoming.triple)} sin declarar una recodificación"
        )
        violations.append(Violation("RF-42", message))
    return violations


def _check_reassignments(context: _Context) -> list[Violation]:
    """RF-43: un país solo recibe un código vigente o histórico de otro si lo declara."""
    holders: dict[tuple[str, str], set[str]] = {}
    for holder in context.published.values():
        for kind in CODE_KINDS:
            holders.setdefault((kind, holder.triple.code(kind)), set()).add(holder.country_id)
    for kind, code, country_id in context.current.historical_codes:
        holders.setdefault((kind, code), set()).add(country_id)

    needed: set[tuple[str, str, str]] = set()
    for country in context.incoming.countries:
        published = context.published.get(country.country_id)
        for kind in CODE_KINDS:
            code = country.triple.code(kind)
            if published is not None and published.triple.code(kind) == code:
                continue
            if holders.get((kind, code), set()) - {country.country_id}:
                needed.add((country.country_id, kind, code))

    violations: list[Violation] = []
    declared: set[tuple[str, str, str]] = set()
    for item in context.incoming.reassignments:
        key = (item.country_id, item.code_kind, item.code)
        label = f"reasignación del {item.code_kind} {item.code} al país {item.country_id}"
        if key in declared:
            violations.append(Violation("RF-43", f"{label}: está declarada más de una vez"))
        elif key not in needed:
            message = f"{label}: no corresponde (el país no recibe ese código o nadie más lo tuvo)"
            violations.append(Violation("RF-43", message))
        elif not _has_provenance(item.provenance):
            violations.append(Violation("RF-43", f"{label}: no tiene referencia de provenance"))
        declared.add(key)
    for country_id, needed_kind, code in sorted(needed - declared):
        message = (
            f"el país {country_id} recibe el {needed_kind} {code}, vigente o histórico de otro "
            f"país, sin declarar la reasignación"
        )
        violations.append(Violation("RF-43", message))
    return violations


def _check_final_codes(context: _Context) -> list[Violation]:
    """RF-3 sobre el estado final del snapshot completo (RF-44)."""
    violations: list[Violation] = []
    for kind in CODE_KINDS:
        counts = Counter(
            c.triple.code(kind) for c in context.incoming.countries if c.status == "active"
        )
        for code, count in sorted(counts.items()):
            if count > 1:
                message = f"{count} países active comparten el {kind} {code}"
                violations.append(Violation("RF-3", message))
    return violations


# --- paso 6: ciclo de vida ----------------------------------------------------------------------


def _check_lifecycle(context: _Context) -> list[Violation]:
    violations: list[Violation] = []
    for country in context.incoming.countries:
        if country.status not in STATUSES:
            message = (
                f"país {country.country_id}: status {country.status!r} fuera de la convención "
                f"común ({', '.join(STATUSES)})"
            )
            violations.append(Violation("RF-39", message))
        if country.calling_code is not None and not is_valid_calling_code(country.calling_code):
            message = f"país {country.country_id}: el calling_code no es un código E.164"
            violations.append(Violation("RF-5", message))
    return violations + _check_replacements(context)


def _check_replacements(context: _Context) -> list[Violation]:
    """RF-40, RF-52: reemplazos 0..N solo en `inactive`, sin repetidos, existentes, sin el propio
    país y sin ciclos en el grafo de sucesión."""
    countries = context.incoming.countries
    ids = {c.country_id for c in countries}
    violations: list[Violation] = []
    for country in countries:
        successors = country.replacement_country_ids
        if not successors:
            continue
        label = f"país {country.country_id}"
        if country.status == "active":
            message = f"país active {country.country_id} no puede tener reemplazos"
            violations.append(Violation("RF-40", message))
        for repeated in sorted({s for s in successors if successors.count(s) > 1}):
            message = f"{label}: el reemplazo {repeated!r} está repetido"
            violations.append(Violation("RF-40", message))
        for target in dict.fromkeys(successors):
            if target == "":
                violations.append(Violation("RF-40", f"{label}: un reemplazo no es un string"))
            elif target == country.country_id:
                violations.append(Violation("RF-40", f"{label}: reemplazo a sí mismo"))
            elif target not in ids:
                message = f"{label}: el reemplazo {target} no existe"
                violations.append(Violation("RF-40", message))
    graph = {c.country_id: tuple(dict.fromkeys(c.replacement_country_ids)) for c in countries}
    reported: set[str] = set()
    for start in sorted(graph):
        cycle = _cycle_from(start, graph)
        if cycle and not reported.intersection(cycle):
            reported.update(cycle)
            path = " → ".join([*cycle, cycle[0]])
            violations.append(Violation("RF-40", f"ciclo de reemplazos: {path}"))
    return violations


def _cycle_from(start: str, graph: Mapping[str, tuple[str, ...]]) -> list[str]:
    """Un ciclo (de dos o más países) alcanzable desde `start` siguiendo los reemplazos; vacío si
    no hay. El reemplazo a sí mismo se reporta aparte."""
    stack: list[str] = []
    done: set[str] = set()

    def visit(node: str) -> list[str]:
        if node in stack:
            cycle = stack[stack.index(node) :]
            return [] if len(cycle) == 1 else cycle
        if node in done or node not in graph:
            return []
        stack.append(node)
        for successor in graph[node]:
            found = visit(successor)
            if found:
                return found
        stack.pop()
        done.add(node)
        return []

    return visit(start)


# --- paso 7: clasificación ----------------------------------------------------------------------


def _check_classification(context: _Context) -> list[Violation]:
    """RF-6, RF-48: referencias a Region/Subregion de 002, coherentes y vigentes para un active."""
    regions = {r.region_id: r for r in context.regions.regions}
    subregions = {s.subregion_id: s for s in context.regions.subregions}
    violations: list[Violation] = []
    for country in context.incoming.countries:
        label = f"país {country.country_id} ({country.alpha2})"
        region = regions.get(country.region_id) if country.region_id is not None else None
        subregion = (
            subregions.get(country.subregion_id) if country.subregion_id is not None else None
        )
        if country.subregion_id is not None and country.region_id is None:
            violations.append(Violation("RF-6", f"{label}: tiene subregion_id sin region_id"))
        if country.region_id is not None and region is None:
            message = f"{label}: la region_id {country.region_id} no existe en Region/Subregion"
            violations.append(Violation("RF-6", message))
        if country.subregion_id is not None and subregion is None:
            message = f"{label}: la subregion_id {country.subregion_id} no existe"
            violations.append(Violation("RF-6", message))
        if (
            subregion is not None
            and country.region_id is not None
            and subregion.region_id != country.region_id
        ):
            message = (
                f"{label}: la subregión {subregion.subregion_id} pertenece a la región "
                f"{subregion.region_id}, no a {country.region_id}"
            )
            violations.append(Violation("RF-6", message))
        if country.status == "active":
            if region is not None and region.status != "active":
                message = f"{label}: active con la región {region.region_id} inactive"
                violations.append(Violation("RF-48", message))
            if subregion is not None and subregion.status != "active":
                message = f"{label}: active con la subregión {subregion.subregion_id} inactive"
                violations.append(Violation("RF-48", message))
    return violations


# --- paso 8: localizaciones ---------------------------------------------------------------------


def _check_names(context: _Context) -> list[Violation]:
    violations: list[Violation] = []
    names = context.incoming.names
    locales = {item.locale_id: item for item in context.locales.locales}
    country_ids = {c.country_id for c in context.incoming.countries}
    published_pairs = {(n.country_id, n.locale_id) for n in context.current.names}

    for (country_id, locale_id), count in sorted(
        Counter((n.country_id, n.locale_id) for n in names).items()
    ):
        if count > 1:
            message = f"el país {country_id} tiene {count} nombres para el locale {locale_id}"
            violations.append(Violation("RF-31", message))
    for name in names:
        where = f"nombre del país {name.country_id} en {name.locale_id}"
        if name.country_id not in country_ids:
            violations.append(Violation("RF-31", f"{where}: el país no está en el snapshot"))
        locale = locales.get(name.locale_id)
        if locale is None:
            violations.append(Violation("RF-36", f"{where}: el locale no existe en Locale"))
        elif locale.status != "active" and (name.country_id, name.locale_id) not in published_pairs:
            violations.append(Violation("RF-36", f"{where}: nombre nuevo con un locale inactive"))
        if not _is_trimmed(name.name):
            message = f"{where}: name {name.name!r} está vacío o tiene espacios al borde"
            violations.append(Violation("RF-32", message))
        if name.official_name is not None and not _is_trimmed(name.official_name):
            message = f"{where}: official_name {name.official_name!r} está vacío o con espacios"
            violations.append(Violation("RF-32", message))

    pairs = {(n.country_id, n.locale_id) for n in names}
    for country_id in sorted(country_ids):
        for required in context.policy.locales:
            if (country_id, required.locale_id) not in pairs:
                message = (
                    f"el país {country_id} no tiene name en el locale obligatorio "
                    f"{required.code} ({required.locale_id})"
                )
                violations.append(Violation("RF-35", message))
    return violations


# --- paso 9: procedencia ------------------------------------------------------------------------

SOURCE_FIELDS = ("role", "name", "edition", "retrieved_at", "location", "checksum", "license")


def _check_provenance(context: _Context) -> list[Violation]:
    """RF-28, RF-29: fuentes completas, roles de los datos usados y sin conflictos abiertos."""
    provenance = context.incoming.provenance
    sources = provenance.get("sources") if isinstance(provenance, Mapping) else None
    if not isinstance(sources, list) or not sources:
        return [Violation("RF-28", "el snapshot no declara ninguna fuente en su procedencia")]
    violations: list[Violation] = []
    roles: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, Mapping):
            violations.append(Violation("RF-28", f"la fuente #{index + 1} no es un objeto"))
            continue
        label = f"fuente #{index + 1} ({source.get('name') or 'sin nombre'})"
        for field_name in SOURCE_FIELDS:
            value = source.get(field_name)
            if not isinstance(value, str) or not value.strip():
                violations.append(Violation("RF-28", f"{label}: falta {field_name}"))
        role = source.get("role")
        if isinstance(role, str) and role.strip():
            roles.add(role)

    incoming = context.incoming
    required = {"identity", "names"}
    if any(c.calling_code is not None for c in incoming.countries):
        required.add("calling_code")
    if any(c.region_id is not None or c.subregion_id is not None for c in incoming.countries):
        required.add("classification")
    if incoming.flags:
        required.add("flags")
    for role in sorted(required - roles):
        message = f"falta la fuente con rol {role}, que declara el origen y la licencia"
        violations.append(Violation("RF-28", message))
    for flag in incoming.flags:
        if flag.source not in roles:
            message = f"la bandera del país {flag.country_id} cita la fuente {flag.source!r}"
            violations.append(Violation("RF-28", f"{message}, que no está declarada"))

    conflicts = provenance.get("unresolved_conflicts") if isinstance(provenance, Mapping) else None
    if not isinstance(conflicts, list):
        violations.append(Violation("RF-28", "la procedencia no declara unresolved_conflicts"))
    elif conflicts:
        message = f"el snapshot declara {len(conflicts)} conflicto(s) entre fuentes sin resolver"
        violations.append(Violation("RF-29", message))
    return violations


# --- paso 10: banderas declaradas ---------------------------------------------------------------


def _check_flag_declarations(context: _Context) -> list[Violation]:
    """RF-19, RF-49: la parte declarativa. El asset en sí lo verifica la aplicación (FlagStore)."""
    incoming = context.incoming
    country_ids = {c.country_id for c in incoming.countries}
    violations: list[Violation] = []
    for flag in incoming.flags:
        where = f"bandera del país {flag.country_id}"
        if flag.country_id not in country_ids:
            violations.append(Violation("RF-19", f"{where}: el país no está en el snapshot"))
        if flag.media_type != SVG_MEDIA_TYPE:
            message = f"{where}: media_type {flag.media_type!r}, debe ser {SVG_MEDIA_TYPE}"
            violations.append(Violation("RF-49", message))
        if not is_safe_asset_path(flag.asset_path):
            message = f"{where}: la ruta {flag.asset_path!r} no es relativa ni segura"
            violations.append(Violation("RF-49", message))
    for exception in incoming.flag_exceptions:
        where = f"excepción de bandera del país {exception.country_id}"
        if exception.country_id not in country_ids:
            violations.append(Violation("RF-19", f"{where}: el país no está en el snapshot"))
        if not _is_trimmed(exception.reason):
            violations.append(Violation("RF-19", f"{where}: el motivo está vacío o con espacios"))

    declarations = Counter(f.country_id for f in incoming.flags)
    declarations.update(e.country_id for e in incoming.flag_exceptions)
    for country_id, count in sorted(declarations.items()):
        if count > 1:
            message = f"el país {country_id} declara {count} veces su bandera o su excepción"
            violations.append(Violation("RF-19", message))
    for country in incoming.countries:
        if country.status == "active" and country.country_id not in declarations:
            message = (
                f"país active {country.country_id} ({country.alpha2}) sin bandera ni excepción"
            )
            violations.append(Violation("RF-19", message))
    return violations


# --- plan ---------------------------------------------------------------------------------------


def _plan(incoming: IncomingCatalog, current: CatalogState) -> CatalogPlan:
    published = {c.country_id: c for c in current.countries}
    new_names, updated_names = _name_changes(incoming.names, current.names)
    new_flags, updated_flags = _flag_changes(incoming, current.flags)
    return CatalogPlan(
        new_countries=tuple(c for c in incoming.countries if c.country_id not in published),
        updated_countries=tuple(
            c
            for c in incoming.countries
            if c.country_id in published and c != published[c.country_id]
        ),
        recodings=incoming.recodings,
        new_names=new_names,
        updated_names=updated_names,
        new_flags=new_flags,
        updated_flags=updated_flags,
    )


def _name_changes(
    incoming: Iterable[NameRecord], published: Iterable[NameRecord]
) -> tuple[tuple[NameRecord, ...], tuple[NameRecord, ...]]:
    current = {(n.country_id, n.locale_id): n for n in published}
    new = tuple(n for n in incoming if (n.country_id, n.locale_id) not in current)
    updated = tuple(
        n
        for n in incoming
        if (n.country_id, n.locale_id) in current and current[(n.country_id, n.locale_id)] != n
    )
    return new, updated


def _flag_changes(
    incoming: IncomingCatalog, published: Iterable[FlagRecord]
) -> tuple[tuple[FlagRecord, ...], tuple[FlagRecord, ...]]:
    declared = [FlagRecord(f.country_id, f.asset_path, f.sha256, None) for f in incoming.flags]
    declared += [FlagRecord(e.country_id, None, None, e.reason) for e in incoming.flag_exceptions]
    current = {f.country_id: f for f in published}
    new = tuple(f for f in declared if f.country_id not in current)
    updated = tuple(f for f in declared if f.country_id in current and current[f.country_id] != f)
    return new, updated


# --- utilidades ---------------------------------------------------------------------------------


def _is_trimmed(text: str) -> bool:
    """No vacío y sin espacios (ni tabulaciones o saltos) al inicio o al final (RF-32)."""
    return bool(text) and text == text.strip()


def _successors(value: object) -> tuple[str, ...]:
    """RF-52: el conjunto de sucesores en orden ascendente de `country_id` (su orden en el snapshot
    no tiene significado). Un elemento que no es string queda como `""` y el dominio lo rechaza."""
    items = value if isinstance(value, list) else []
    return tuple(sorted(item if isinstance(item, str) else "" for item in items))


def _show(triple: CodeTriple) -> str:
    return f"{triple.alpha2}/{triple.alpha3}/{triple.numeric_code}"


def _has_provenance(provenance: Any) -> bool:
    """RF-41, RF-43, S-11: una referencia a la fuente de autoridad, con `source` no vacío."""
    if not isinstance(provenance, Mapping):
        return False
    source = provenance.get("source")
    return isinstance(source, str) and bool(source.strip())


def _triple(value: object) -> CodeTriple:
    item = value if isinstance(value, Mapping) else {}
    return CodeTriple(
        _text(item.get("alpha2")), _text(item.get("alpha3")), _text(item.get("numeric_code"))
    )


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
