"""Validación del catálogo de un snapshot contra el estado vigente, Locale, Regions y la política.

Función pura (sin base de datos ni red). Sigue los pasos 3 a 10 de la incorporación del plan y se
detiene en el primer paso que falla, informando todas las violaciones de ese paso:

3. Contexto de Locale y de Region/Subregion: RF-35, RF-36, RF-47.
4. Identidad y completitud: RF-2, RF-21, RF-45.

Los pasos 1 y 2 (digest y clasificación A/B/C/D) los evalúa `snapshot.evaluate_snapshot`. Si todo
pasa devuelve el plan de cambios en el orden de escritura.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from gi_common_reference.countries.domain.model import (
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
                _optional(item.get("replacement_country_id")),
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
    checks: tuple[Check, ...] = (_check_context, _check_identity)
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
