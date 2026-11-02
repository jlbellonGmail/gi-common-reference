"""Reglas del catálogo Currency como función pura (D-2, plan «Incorporación», pasos 3 a 9).

`(snapshot ya validado por schema, estado vigente, vista de Locale, vista de Countries, política)
→ plan de cambios | violaciones`. Ante el primer paso que falla se informan todas sus violaciones
(RF-39); si todos pasan se devuelve el plan en el orden de escritura. La base repite las
invariantes estructurales como constraints y triggers (RNF-5).

Pasos: 3 contexto · 4 identidad y completitud · 5 códigos · 6 ciclo de vida y reemplazos ·
7 localizaciones · 8 CountryCurrency (temporal) · 9 procedencia. Los pasos 1 y 2 (schema, digest y
clasificación) los resuelve `snapshot.evaluate_snapshot`.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from gi_common_reference.currencies.domain.codes import (
    is_alphabetic_code,
    is_minor_units,
    is_numeric_code,
    is_trimmed,
    is_uuid,
)
from gi_common_reference.currencies.domain.model import (
    STATUSES,
    CatalogState,
    CountryCatalog,
    CountryCurrencyRecord,
    CurrencyRecord,
    LocaleCatalog,
    NameRecord,
    Violation,
)
from gi_common_reference.currencies.domain.policy import RequiredLocales
from gi_common_reference.currencies.domain.temporal import (
    Period,
    history_violations,
    overlapping_pairs,
    period_of,
)

DAY_FORMAT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
SOURCE_FIELDS = ("name", "edition", "retrieved_at", "location", "checksum", "license")
SOURCE_ROLES = ("identity", "names", "country_currency", "validity")


@dataclass(frozen=True)
class IncomingCatalog:
    """Contenido de un snapshot en términos de dominio."""

    currencies: tuple[CurrencyRecord, ...] = ()
    names: tuple[NameRecord, ...] = ()
    associations: tuple[CountryCurrencyRecord, ...] = ()
    # (country_currency_id, campo, texto) de fechas que pasan el patrón del schema pero no son un
    # día calendario real (p. ej. 2023-02-30): el paso 8 las rechaza (RF-44).
    invalid_dates: tuple[tuple[str, str, str], ...] = ()
    country_snapshot_version: int = 0
    provenance: Any = None


@dataclass(frozen=True)
class CatalogPlan:
    """Violaciones, o bien los cambios a aplicar en el orden de escritura (paso 10)."""

    violations: tuple[Violation, ...] = ()
    new_currencies: tuple[CurrencyRecord, ...] = ()
    updated_currencies: tuple[CurrencyRecord, ...] = ()
    new_names: tuple[NameRecord, ...] = ()
    updated_names: tuple[NameRecord, ...] = ()
    new_associations: tuple[CountryCurrencyRecord, ...] = ()
    updated_associations: tuple[CountryCurrencyRecord, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def is_empty(self) -> bool:
        """El snapshot no cambia nada respecto del estado vigente (solo cambia la versión)."""
        return self.ok and not any(
            (
                self.new_currencies,
                self.updated_currencies,
                self.new_names,
                self.updated_names,
                self.new_associations,
                self.updated_associations,
            )
        )


def incoming_from(document: Mapping[str, Any]) -> IncomingCatalog:
    """Contenido de un documento de snapshot ya validado por schema; lo faltante queda vacío."""
    invalid: list[tuple[str, str, str]] = []
    associations = tuple(
        _association(item, invalid) for item in document.get("country_currencies", ())
    )
    return IncomingCatalog(
        currencies=tuple(
            CurrencyRecord(
                _text(item.get("currency_id")),
                _text(item.get("alphabetic_code")),
                _text(item.get("numeric_code")),
                item.get("minor_units"),
                item.get("fund_code"),
                _text(item.get("status")),
                _successors(item.get("replacement_currency_ids")),
            )
            for item in document.get("currencies", ())
        ),
        names=tuple(
            NameRecord(
                _text(item.get("currency_id")),
                _text(item.get("locale_id")),
                _text(item.get("name")),
            )
            for item in document.get("currency_names", ())
        ),
        associations=associations,
        invalid_dates=tuple(invalid),
        country_snapshot_version=_int(document.get("country_snapshot_version")),
        provenance=document.get("provenance"),
    )


def _association(
    item: Mapping[str, Any], invalid: list[tuple[str, str, str]]
) -> CountryCurrencyRecord:
    key = _text(item.get("country_currency_id"))
    return CountryCurrencyRecord(
        key,
        _text(item.get("country_id")),
        _text(item.get("currency_id")),
        _text(item.get("status")),
        _day(item.get("valid_from"), key, "valid_from", invalid),
        _day(item.get("valid_to"), key, "valid_to", invalid),
    )


def _day(value: Any, key: str, field: str, invalid: list[tuple[str, str, str]]) -> date | None:
    """Día calendario `YYYY-MM-DD` o `None`; un texto que no es una fecha real se registra."""
    if value is None:
        return None
    try:
        if not isinstance(value, str) or DAY_FORMAT.fullmatch(value) is None:
            raise ValueError(value)
        return date.fromisoformat(value)
    except ValueError:
        invalid.append((key, field, str(value)))
        return None


@dataclass
class _Context:
    incoming: IncomingCatalog
    current: CatalogState
    locales: LocaleCatalog
    countries: CountryCatalog
    policy: RequiredLocales


Check = Callable[[_Context], list[Violation]]


def plan_catalog_changes(
    incoming: IncomingCatalog,
    current: CatalogState,
    locales: LocaleCatalog,
    countries: CountryCatalog,
    policy: RequiredLocales,
) -> CatalogPlan:
    context = _Context(incoming, current, locales, countries, policy)
    for check in _CHECKS:
        violations = check(context)
        if violations:
            return CatalogPlan(violations=tuple(violations))
    return _plan(incoming, current)


# --- paso 3: contexto (RF-13, RF-40, RF-41) ------------------------------------------------------


def _check_context(context: _Context) -> list[Violation]:
    return _check_locale_context(context) + _check_countries_context(context)


def _check_locale_context(context: _Context) -> list[Violation]:
    locales, policy = context.locales, context.policy
    if locales.snapshot_version is None:
        return [Violation("RF-13", "no hay una versión vigente del catálogo de Locale")]
    published = {item.locale_id: item for item in locales.locales}
    found: list[Violation] = []
    for required in policy.locales:
        item = published.get(required.locale_id)
        if item is None:
            found.append(
                Violation("RF-13", f"el locale obligatorio {required.locale_id} no existe")
            )
        elif item.status != "active":
            found.append(
                Violation("RF-13", f"el locale obligatorio {required.locale_id} está inactive")
            )
        elif item.code != required.code:
            found.append(
                Violation(
                    "RF-13",
                    f"el locale obligatorio {required.locale_id} es «{item.code}» y la política "
                    f"espera «{required.code}»",
                )
            )
    return found


def _check_countries_context(context: _Context) -> list[Violation]:
    countries, declared = context.countries, context.incoming.country_snapshot_version
    if countries.snapshot_version is None:
        return [Violation("RF-40", "no hay una versión vigente del catálogo Countries")]
    if declared not in countries.incorporated_versions:
        return [
            Violation(
                "RF-41",
                f"la country_snapshot_version {declared} declarada no está incorporada",
            )
        ]
    if declared > countries.snapshot_version:
        return [
            Violation(
                "RF-41",
                f"la country_snapshot_version {declared} es posterior a la vigente "
                f"({countries.snapshot_version})",
            )
        ]
    return []


# --- paso 4: identidad y completitud (RF-2, RF-7, RF-37)


def _check_identity(context: _Context) -> list[Violation]:
    incoming, current = context.incoming, context.current
    found: list[Violation] = []
    seen: set[str] = set()
    for item in incoming.currencies:
        if not is_uuid(item.currency_id):
            found.append(Violation("RF-2", f"currency_id inválido: «{item.currency_id}»"))
        elif item.currency_id in seen:
            found.append(Violation("RF-2", f"currency_id repetido: {item.currency_id}"))
        seen.add(item.currency_id)
    for published in current.currencies:
        if published.currency_id not in seen:
            found.append(
                Violation(
                    "RF-37",
                    f"el snapshot omite la moneda publicada {published.alphabetic_code} "
                    f"({published.currency_id}); un retiro se expresa con status = inactive",
                )
            )
    incoming_pairs = {(n.currency_id, n.locale_id) for n in incoming.names}
    for name in current.names:
        if (name.currency_id, name.locale_id) not in incoming_pairs:
            found.append(
                Violation(
                    "RF-37",
                    f"el snapshot omite la localización publicada ({name.currency_id}, "
                    f"{name.locale_id})",
                )
            )
    found += _check_association_identity(context)
    return found


# --- paso 5: códigos (RF-3, RF-4, RF-5) -----------------------------------------------------------


def _check_codes(context: _Context) -> list[Violation]:
    incoming, current = context.incoming, context.current
    found: list[Violation] = []
    for item in incoming.currencies:
        label = f"{item.alphabetic_code or '?'} ({item.currency_id})"
        if not is_alphabetic_code(item.alphabetic_code):
            found.append(Violation("RF-4", f"código alfabético inválido en {label}"))
        if not is_numeric_code(item.numeric_code):
            found.append(Violation("RF-4", f"código numérico inválido en {label}"))
        if not is_minor_units(item.minor_units):
            found.append(Violation("RF-4", f"unidades menores inválidas en {label}"))
        if not isinstance(item.fund_code, bool):
            found.append(Violation("RF-4", f"el indicador de fondos de {label} no es booleano"))

    published = {c.currency_id: c for c in current.currencies}
    published_alphabetic = {c.alphabetic_code: c.currency_id for c in current.currencies}
    for item in incoming.currencies:
        before = published.get(item.currency_id)
        if before is not None:
            if before.alphabetic_code != item.alphabetic_code:
                found.append(
                    Violation(
                        "RF-5",
                        f"el snapshot cambia el código alfabético de {before.alphabetic_code} "
                        f"a {item.alphabetic_code}; un código nuevo es una moneda nueva (D-6)",
                    )
                )
            if before.numeric_code != item.numeric_code:
                found.append(
                    Violation(
                        "RF-5",
                        f"el snapshot cambia el código numérico de {before.alphabetic_code} "
                        f"de {before.numeric_code} a {item.numeric_code}",
                    )
                )
        owner = published_alphabetic.get(item.alphabetic_code)
        if owner is not None and owner != item.currency_id:
            found.append(
                Violation(
                    "RF-5",
                    f"el snapshot asigna el código alfabético publicado {item.alphabetic_code} "
                    f"a otro currency_id ({item.currency_id})",
                )
            )
    return found + _check_final_codes(incoming.currencies)


def _check_final_codes(currencies: Sequence[CurrencyRecord]) -> list[Violation]:
    """RF-3 sobre el estado final: alfabético único en todo el catálogo, numérico entre activas."""
    found: list[Violation] = []
    alphabetic: dict[str, str] = {}
    numeric: dict[str, str] = {}
    for item in currencies:
        other = alphabetic.setdefault(item.alphabetic_code, item.currency_id)
        if other != item.currency_id:
            found.append(
                Violation("RF-3", f"el código alfabético {item.alphabetic_code} está repetido")
            )
        if item.status == "active":
            holder = numeric.setdefault(item.numeric_code, item.currency_id)
            if holder != item.currency_id:
                found.append(
                    Violation(
                        "RF-3",
                        f"el código numérico {item.numeric_code} está repetido entre monedas "
                        "active",
                    )
                )
    return found


# --- paso 6: ciclo de vida y reemplazos (RF-6, RF-9, RF-10)


def _check_lifecycle(context: _Context) -> list[Violation]:
    found: list[Violation] = []
    for item in context.incoming.currencies:
        if item.status not in STATUSES:
            found.append(
                Violation("RF-9", f"status inválido «{item.status}» en {item.alphabetic_code}")
            )
    return found + _check_replacements(context.incoming.currencies)


def _check_replacements(currencies: Sequence[CurrencyRecord]) -> list[Violation]:
    found: list[Violation] = []
    ids = {item.currency_id for item in currencies}
    graph: dict[str, tuple[str, ...]] = {}
    for item in currencies:
        successors = item.replacement_currency_ids
        label = f"{item.alphabetic_code} ({item.currency_id})"
        if successors and item.status != "inactive":
            found.append(
                Violation("RF-6", f"{label} tiene reemplazos pero no está inactive (RF-10)")
            )
        if len(set(successors)) != len(successors):
            found.append(Violation("RF-6", f"{label} repite un reemplazo"))
        for successor in successors:
            if not successor:
                found.append(Violation("RF-6", f"{label} tiene un reemplazo nulo o vacío"))
            elif not is_uuid(successor):
                found.append(Violation("RF-6", f"{label} tiene un reemplazo inválido: {successor}"))
            elif successor == item.currency_id:
                found.append(Violation("RF-6", f"{label} se reemplaza a sí misma"))
            elif successor not in ids:
                found.append(Violation("RF-6", f"{label} apunta a un reemplazo inexistente"))
        graph[item.currency_id] = tuple(s for s in successors if s in ids and s)
    reported: set[frozenset[str]] = set()
    for start in sorted(graph):
        cycle = _cycle_from(start, graph)
        if cycle and frozenset(cycle) not in reported:
            reported.add(frozenset(cycle))
            found.append(Violation("RF-6", f"el grafo de reemplazos tiene un ciclo: {cycle}"))
    return found


def _cycle_from(start: str, graph: Mapping[str, tuple[str, ...]]) -> list[str]:
    """Un ciclo que pasa por `start`, o vacío. Iterativo: no depende del límite de recursión."""
    stack: list[tuple[str, int]] = [(start, 0)]
    path: list[str] = [start]
    visited: set[str] = set()
    while stack:
        node, index = stack.pop()
        successors = graph.get(node, ())
        if index < len(successors):
            stack.append((node, index + 1))
            nxt = successors[index]
            if nxt == start:
                return [*path, start]
            if nxt not in visited:
                visited.add(nxt)
                path.append(nxt)
                stack.append((nxt, 0))
        else:
            path.pop()
    return []


# --- paso 7: localizaciones (RF-12 a RF-16)


def _check_names(context: _Context) -> list[Violation]:
    incoming, current = context.incoming, context.current
    found: list[Violation] = []
    currency_ids = {c.currency_id for c in incoming.currencies}
    locales = {item.locale_id: item for item in context.locales.locales}
    published = {(n.currency_id, n.locale_id) for n in current.names}
    seen: set[tuple[str, str]] = set()
    for name in incoming.names:
        pair = (name.currency_id, name.locale_id)
        if name.currency_id not in currency_ids:
            found.append(
                Violation("RF-12", f"la localización apunta a una moneda inexistente: {pair}")
            )
        if pair in seen:
            found.append(Violation("RF-12", f"localización repetida para {pair}"))
        seen.add(pair)
        if not is_trimmed(name.name):
            found.append(
                Violation(
                    "RF-16",
                    f"el nombre de {pair} está vacío o tiene espacios al inicio o al final",
                )
            )
        if pair not in published:
            locale = locales.get(name.locale_id)
            if locale is None:
                found.append(
                    Violation("RF-14", f"la localización nueva {pair} usa un locale inexistente")
                )
            elif locale.status != "active":
                found.append(
                    Violation("RF-14", f"la localización nueva {pair} usa un locale inactive")
                )
    for currency in incoming.currencies:
        for required in context.policy.locales:
            if (currency.currency_id, required.locale_id) not in seen:
                found.append(
                    Violation(
                        "RF-13",
                        f"{currency.alphabetic_code} no tiene nombre en el locale obligatorio "
                        f"«{required.code}» ({required.locale_id})",
                    )
                )
    return found


def _check_association_identity(context: _Context) -> list[Violation]:
    """Identidad y completitud de CountryCurrency (RF-7, RF-17, RF-37)."""
    incoming, current = context.incoming, context.current
    found: list[Violation] = []
    seen: set[str] = set()
    for item in incoming.associations:
        if not is_uuid(item.country_currency_id):
            found.append(
                Violation("RF-17", f"country_currency_id inválido: «{item.country_currency_id}»")
            )
        elif item.country_currency_id in seen:
            found.append(
                Violation("RF-17", f"country_currency_id repetido: {item.country_currency_id}")
            )
        seen.add(item.country_currency_id)
    for published in current.associations:
        if published.country_currency_id not in seen:
            found.append(
                Violation(
                    "RF-37",
                    f"el snapshot omite la asociación publicada {published.country_currency_id}; "
                    "un retiro es status = inactive o el cierre de su vigencia, nunca la ausencia",
                )
            )
    return found


# --- paso 8: CountryCurrency temporal (RF-17 a RF-19, RF-38, RF-40, RF-44 a RF-47, RF-52) ------


def _check_associations(context: _Context) -> list[Violation]:
    incoming, current = context.incoming, context.current
    found: list[Violation] = []
    currencies = {c.currency_id: c for c in incoming.currencies}
    countries = {c.country_id: c for c in context.countries.countries}
    published = {a.country_currency_id: a for a in current.associations}

    for key, field, text in incoming.invalid_dates:
        found.append(Violation("RF-44", f"{field} de {key} no es un día calendario real: «{text}»"))

    for item in incoming.associations:
        label = f"la asociación {item.country_currency_id}"
        if item.status not in STATUSES:
            found.append(Violation("RF-9", f"status inválido «{item.status}» en {label}"))
        country = countries.get(item.country_id)
        currency = currencies.get(item.currency_id)
        if country is None:
            found.append(
                Violation(
                    "RF-40", f"{label} referencia un country_id inexistente: {item.country_id}"
                )
            )
        if currency is None:
            found.append(
                Violation("RF-17", f"{label} referencia una moneda inexistente: {item.currency_id}")
            )
        if not period_of(item).is_ordered:
            found.append(
                Violation(
                    "RF-44",
                    f"{label} tiene el inicio ({item.valid_from}) no anterior al fin "
                    f"({item.valid_to})",
                )
            )
        before = published.get(item.country_currency_id)
        if before is not None:
            for reason in history_violations(before, item):
                found.append(Violation("RF-47", f"{label} {reason}"))
        if item.status == "active" and item.valid_to is None:
            if country is not None and country.status != "active":
                found.append(
                    Violation(
                        "RF-19",
                        f"{label} está active y abierta sobre un Country inactive; cierre su "
                        "vigencia (RF-46)",
                    )
                )
            if currency is not None and currency.status != "active":
                found.append(
                    Violation(
                        "RF-19",
                        f"{label} está active y abierta sobre la moneda inactive "
                        f"{currency.alphabetic_code}; al retirarla cierre su vigencia (RF-38)",
                    )
                )

    for first, second in overlapping_pairs(incoming.associations):
        found.append(
            Violation(
                "RF-45",
                f"las asociaciones activas {first.country_currency_id} y "
                f"{second.country_currency_id} del mismo país y moneda se solapan: "
                f"{_show(period_of(first))} y {_show(period_of(second))}",
            )
        )
    return found


def _show(period: Period) -> str:
    return f"[{period.start or '-∞'}, {period.end or '+∞'})"


# --- paso 9: procedencia (RF-41, D-20)


def _check_provenance(context: _Context) -> list[Violation]:
    provenance = context.incoming.provenance
    if not isinstance(provenance, dict):
        return [Violation("RF-41", "el snapshot no declara procedencia")]
    found: list[Violation] = []
    sources = provenance.get("sources")
    roles: set[str] = set()
    if not isinstance(sources, list) or not sources:
        found.append(Violation("RF-41", "la procedencia no lista ninguna fuente"))
        sources = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            found.append(Violation("RF-41", f"la fuente #{index} no es un objeto"))
            continue
        role = source.get("role")
        if role not in SOURCE_ROLES:
            found.append(Violation("RF-41", f"la fuente #{index} tiene un rol desconocido"))
        else:
            roles.add(str(role))
        for field in SOURCE_FIELDS:
            value = source.get(field)
            if not isinstance(value, str) or not value.strip():
                found.append(Violation("RF-41", f"la fuente #{index} no declara «{field}»"))
    for required in _required_roles(context):
        if required not in roles:
            found.append(Violation("RF-41", f"falta la fuente con rol «{required}»"))
    conflicts = provenance.get("unresolved_conflicts")
    if not isinstance(conflicts, list) or conflicts:
        found.append(
            Violation("RF-41", "la procedencia declara conflictos entre fuentes sin resolver")
        )
    return found


def _required_roles(context: _Context) -> tuple[str, ...]:
    """`identity` y `names` siempre; `country_currency` si hay asociaciones y `validity` si
    alguna declara una fecha (D23 del plan)."""
    associations = context.incoming.associations
    roles = ["identity", "names"]
    if associations:
        roles.append("country_currency")
    if any(a.valid_from or a.valid_to for a in associations):
        roles.append("validity")
    return tuple(roles)


# --- plan de cambios ---------------------------------------------------------------------------


def _plan(incoming: IncomingCatalog, current: CatalogState) -> CatalogPlan:
    published = {c.currency_id: c for c in current.currencies}
    new_currencies = tuple(c for c in incoming.currencies if c.currency_id not in published)
    updated_currencies = tuple(
        c
        for c in incoming.currencies
        if c.currency_id in published and published[c.currency_id] != c
    )
    names = {(n.currency_id, n.locale_id): n for n in current.names}
    new_names = tuple(n for n in incoming.names if (n.currency_id, n.locale_id) not in names)
    updated_names = tuple(
        n
        for n in incoming.names
        if (n.currency_id, n.locale_id) in names and names[(n.currency_id, n.locale_id)] != n
    )
    associations = {a.country_currency_id: a for a in current.associations}
    new_associations = tuple(
        a for a in incoming.associations if a.country_currency_id not in associations
    )
    updated_associations = tuple(
        a
        for a in incoming.associations
        if a.country_currency_id in associations and associations[a.country_currency_id] != a
    )
    return CatalogPlan(
        (),
        new_currencies,
        updated_currencies,
        new_names,
        updated_names,
        new_associations,
        updated_associations,
    )


_CHECKS: tuple[Check, ...] = (
    _check_context,
    _check_identity,
    _check_codes,
    _check_lifecycle,
    _check_names,
    _check_associations,
    _check_provenance,
)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _successors(value: Any) -> tuple[str, ...]:
    """Conjunto de sucesoras ordenado ascendente (D-17); un nulo queda como cadena vacía."""
    if not isinstance(value, list):
        return ()
    return tuple(sorted(item if isinstance(item, str) else "" for item in value))
