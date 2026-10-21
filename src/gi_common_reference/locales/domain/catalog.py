"""Validación del catálogo de un snapshot contra el estado vigente y el artefacto IANA.

Función pura (sin base de datos ni red). Sigue los pasos 6 a 9 de la incorporación del plan y se
detiene en el primer paso que falla, informando todas las violaciones de ese paso:

1. RF-28: todos los códigos en minúsculas, sin normalizar.
2. Identidad contra el estado vigente: RF-15, RF-16, RF-17, RF-3 y RF-4.
3. Coherencia con el artefacto IANA: RF-5, RF-26, RF-27 (y RF-19, que los aplica).
4. `replacement`: RF-22.
"""

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from gi_common_reference.locales.domain.codes import is_lowercase, publication_violations
from gi_common_reference.locales.domain.iana import IanaRegistry
from gi_common_reference.locales.domain.model import LocaleRecord, Violation

UUID_FORMAT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
STATUSES = frozenset({"active", "inactive"})

Check = Callable[[Sequence[LocaleRecord], Sequence[LocaleRecord], IanaRegistry], list[Violation]]


@dataclass(frozen=True)
class CatalogPlan:
    """Violaciones, o bien los cambios a aplicar: locales nuevos y metadata actualizada."""

    violations: tuple[Violation, ...] = ()
    new_locales: tuple[LocaleRecord, ...] = ()
    metadata_updates: tuple[LocaleRecord, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations


def locale_records(document: Mapping[str, Any]) -> list[LocaleRecord]:
    """Locales de un documento de snapshot ya validado por schema; lo faltante queda vacío."""
    return [
        LocaleRecord(
            locale_id=_text(item.get("locale_id")),
            code=_text(item.get("code")),
            status=_text(item.get("status")),
            iana_deprecated=item.get("iana_deprecated") is True,
            replacement_locale_id=_optional_text(item.get("replacement_locale_id")),
        )
        for item in document["locales"]
    ]


def plan_catalog_changes(
    incoming: Sequence[LocaleRecord],
    current: Sequence[LocaleRecord],
    registry: IanaRegistry,
) -> CatalogPlan:
    checks: tuple[Check, ...] = (
        _check_lowercase,
        _check_identity,
        _check_artifact,
        _check_replacements,
    )
    for check in checks:
        violations = check(incoming, current, registry)
        if violations:
            return CatalogPlan(violations=tuple(violations))

    published = {record.locale_id: record for record in current}
    new = tuple(record for record in incoming if record.locale_id not in published)
    updates = tuple(
        record
        for record in incoming
        if record.locale_id in published
        and _metadata(record) != _metadata(published[record.locale_id])
    )
    return CatalogPlan(new_locales=new, metadata_updates=updates)


def _check_lowercase(
    incoming: Sequence[LocaleRecord], current: Sequence[LocaleRecord], registry: IanaRegistry
) -> list[Violation]:
    return [
        Violation("RF-28", f"el código {record.code!r} no está en minúsculas")
        for record in incoming
        if not is_lowercase(record.code)
    ]


def _check_identity(
    incoming: Sequence[LocaleRecord], current: Sequence[LocaleRecord], registry: IanaRegistry
) -> list[Violation]:
    by_id = {record.locale_id: record for record in current}
    by_code = {record.code: record for record in current}
    incoming_ids = Counter(record.locale_id for record in incoming)
    incoming_codes = Counter(record.code for record in incoming)
    violations: list[Violation] = []

    for record in current:
        if record.locale_id not in incoming_ids:
            message = f"falta el locale publicado {record.code} ({record.locale_id})"
            violations.append(Violation("RF-15", message))

    for record in incoming:
        published = by_id.get(record.locale_id)
        if published is not None:
            if record.code != published.code:
                message = (
                    f"el locale_id {record.locale_id} cambia su código publicado "
                    f"de {published.code} a {record.code}"
                )
                violations.append(Violation("RF-16", message))
                if record.code not in by_code:
                    message = (
                        f"el locale_id {record.locale_id} ya se usó "
                        f"y no puede ser de un locale nuevo"
                    )
                    violations.append(Violation("RF-17", message))
        elif record.code in by_code:
            message = (
                f"asigna el locale_id nuevo {record.locale_id!r} al código publicado {record.code}"
            )
            violations.append(Violation("RF-16", message))
        else:
            violations.extend(_check_new_locale(record))

    for locale_id, count in incoming_ids.items():
        if count > 1:
            rule = "RF-3" if locale_id in by_id else "RF-17"
            violations.append(
                Violation(rule, f"el locale_id {locale_id!r} está repetido en el snapshot")
            )
    for code, count in incoming_codes.items():
        if count > 1:
            rule = "RF-3" if code in by_code else "RF-4"
            violations.append(Violation(rule, f"el código {code} está repetido en el snapshot"))

    return _with_registry_rules(violations, incoming, by_id, registry)


def _check_new_locale(record: LocaleRecord) -> list[Violation]:
    if not UUID_FORMAT.fullmatch(record.locale_id):
        message = f"el locale nuevo {record.code} trae un locale_id ausente o que no es un UUID"
        return [Violation("RF-17", message)]
    return []


def _with_registry_rules(
    violations: list[Violation],
    incoming: Sequence[LocaleRecord],
    by_id: Mapping[str, LocaleRecord],
    registry: IanaRegistry,
) -> list[Violation]:
    """Reglas de publicación (RF-4) de cada código nuevo contra el artefacto IANA."""
    for record in incoming:
        if record.locale_id in by_id:
            continue
        for problem in publication_violations(record.code, registry):
            message = (
                f"el código nuevo {record.code!r} no cumple las reglas de publicación: {problem}"
            )
            violations.append(Violation("RF-4", message))
    return violations


def _check_artifact(
    incoming: Sequence[LocaleRecord], current: Sequence[LocaleRecord], registry: IanaRegistry
) -> list[Violation]:
    id_by_code = {record.code: record.locale_id for record in incoming}
    violations: list[Violation] = []
    for record in incoming:
        if record.status not in STATUSES:
            violations.append(
                Violation("RF-5", f"{record.code}: status inválido {record.status!r}")
            )
        entry = registry.language(record.code)
        if entry is None:
            message = (
                f"el código publicado {record.code} no está registrado como language "
                f"en el artefacto IANA"
            )
            violations.append(Violation("RF-26", message))
            continue

        deprecated = entry.is_deprecated
        if record.iana_deprecated != deprecated:
            message = (
                f"{record.code}: iana_deprecated={record.iana_deprecated} pero el artefacto IANA "
                f"declara {'deprecación' if deprecated else 'ninguna deprecación'}"
            )
            violations.append(Violation("RF-26", message))
        if deprecated and record.status != "inactive":
            message = f"{record.code} está deprecado en el artefacto IANA y debe quedar inactive"
            violations.append(Violation("RF-27", message))

        if deprecated and entry.preferred_value:
            target = id_by_code.get(entry.preferred_value.lower())
            if target is not None and record.replacement_locale_id != target:
                message = (
                    f"{record.code}: replacement debe ser el locale de {entry.preferred_value} "
                    f"(Preferred-Value del artefacto IANA)"
                )
                violations.append(Violation("RF-26", message))
        elif record.replacement_locale_id is not None:
            message = (
                f"{record.code}: el artefacto IANA no declara Preferred-Value, "
                f"no puede tener replacement"
            )
            violations.append(Violation("RF-26", message))
    return violations


def _check_replacements(
    incoming: Sequence[LocaleRecord], current: Sequence[LocaleRecord], registry: IanaRegistry
) -> list[Violation]:
    ids = {record.locale_id for record in incoming}
    codes = {record.code for record in incoming}
    next_of = {record.locale_id: record.replacement_locale_id for record in incoming}
    violations: list[Violation] = []

    for record in incoming:
        entry = registry.language(record.code)
        if entry and entry.is_deprecated and entry.preferred_value:
            preferred = entry.preferred_value.lower()
            if preferred not in codes:
                message = (
                    f"{record.code}: su Preferred-Value {preferred} no está publicado ni incluido "
                    f"en el snapshot"
                )
                violations.append(Violation("RF-22", message))
        target = record.replacement_locale_id
        if target is None:
            continue
        if target == record.locale_id:
            violations.append(
                Violation("RF-22", f"{record.code}: el replacement apunta a sí mismo")
            )
        elif target not in ids:
            message = (
                f"{record.code}: el replacement {target!r} no está publicado ni en el snapshot"
            )
            violations.append(Violation("RF-22", message))

    reported: set[str] = set()
    for start in next_of:
        cycle = _cycle_from(start, next_of)
        if cycle and not reported.intersection(cycle):
            reported.update(cycle)
            codes_by_id = {record.locale_id: record.code for record in incoming}
            path = " → ".join(codes_by_id[locale_id] for locale_id in [*cycle, cycle[0]])
            violations.append(Violation("RF-22", f"ciclo de replacement: {path}"))
    return violations


def _cycle_from(start: str, next_of: Mapping[str, str | None]) -> list[str]:
    """Ids del ciclo al que llega `start` siguiendo los replacement; vacío si no hay ciclo."""
    path: list[str] = []
    node: str | None = start
    while node is not None and node in next_of and node not in path:
        path.append(node)
        node = next_of[node]
    if node is None or node not in path:
        return []
    cycle = path[path.index(node) :]
    return [] if len(cycle) == 1 else cycle  # el replacement a sí mismo se reporta aparte


def _metadata(record: LocaleRecord) -> tuple[str, bool, str | None]:
    return record.status, record.iana_deprecated, record.replacement_locale_id


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None
