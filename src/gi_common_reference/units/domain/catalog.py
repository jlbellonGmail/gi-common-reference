"""Reglas del catálogo Units como función pura (D8, D9 y pasos 3 a 10 del plan «Incorporación»).

`(snapshot ya validado por schema, estado vigente, vista de Locale, política, tabla UCUM) → plan de
cambios | violaciones`. Ante el primer paso que falla se informan todas sus violaciones (RF-45);
si todos pasan se devuelve el plan en el orden de escritura (unidades → magnitudes → asociaciones →
nombres). La base repite las invariantes estructurales como constraints y triggers (RNF-4).

Pasos: 3 contexto · 4 identidad y completitud · 5 códigos · 6 magnitudes · 7 asociaciones ·
8 UCUM y verificación cruzada · 9 localizaciones · 10 procedencia. Los pasos 1 y 2 (schema, digest y
clasificación) los resuelve `snapshot.evaluate_snapshot`.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from gi_common_reference.units.domain.model import (
    CONVERSION_TYPES,
    STATUSES,
    AssociationRecord,
    CatalogState,
    KindNameRecord,
    LocaleCatalog,
    QuantityKindRecord,
    UcumTable,
    UnitNameRecord,
    UnitRecord,
    Violation,
)
from gi_common_reference.units.domain.numeric import (
    NumericFormatError,
    parse_canonical_factor,
    parse_canonical_offset,
)
from gi_common_reference.units.domain.policy import RequiredLocales
from gi_common_reference.units.domain.ucum import UcumError, UcumEvaluator, UcumQuantity

UUID_FORMAT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
KIND_CODE = re.compile(r"[a-z][a-z0-9_]{1,63}")
UNECE_CODE = re.compile(r"[A-Z0-9]{2,3}")
SOURCE_FIELDS = ("name", "edition", "retrieved_at", "location", "checksum", "license")
REQUIRED_ROLES = ("definitions", "ucum", "names")


@dataclass(frozen=True)
class IncomingCatalog:
    """Contenido de un snapshot en términos de dominio."""

    quantity_kinds: tuple[QuantityKindRecord, ...] = ()
    units: tuple[UnitRecord, ...] = ()
    associations: tuple[AssociationRecord, ...] = ()
    kind_names: tuple[KindNameRecord, ...] = ()
    unit_names: tuple[UnitNameRecord, ...] = ()
    provenance: Any = None


@dataclass(frozen=True)
class CatalogPlan:
    """Violaciones, o bien los cambios a aplicar en el orden de escritura."""

    violations: tuple[Violation, ...] = ()
    new_units: tuple[UnitRecord, ...] = ()
    updated_units: tuple[UnitRecord, ...] = ()
    new_quantity_kinds: tuple[QuantityKindRecord, ...] = ()
    updated_quantity_kinds: tuple[QuantityKindRecord, ...] = ()
    new_associations: tuple[AssociationRecord, ...] = ()
    updated_associations: tuple[AssociationRecord, ...] = ()
    new_kind_names: tuple[KindNameRecord, ...] = ()
    updated_kind_names: tuple[KindNameRecord, ...] = ()
    new_unit_names: tuple[UnitNameRecord, ...] = ()
    updated_unit_names: tuple[UnitNameRecord, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def is_empty(self) -> bool:
        """El snapshot no cambia nada respecto del estado vigente (solo cambia la versión)."""
        return self.ok and not any(
            (
                self.new_units,
                self.updated_units,
                self.new_quantity_kinds,
                self.updated_quantity_kinds,
                self.new_associations,
                self.updated_associations,
                self.new_kind_names,
                self.updated_kind_names,
                self.new_unit_names,
                self.updated_unit_names,
            )
        )


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _optional(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def incoming_from(document: Mapping[str, Any]) -> IncomingCatalog:
    """Contenido de un documento de snapshot ya validado por schema; lo faltante queda vacío."""
    return IncomingCatalog(
        quantity_kinds=tuple(
            QuantityKindRecord(
                _text(item.get("quantity_kind_id")),
                _text(item.get("code")),
                _text(item.get("conversion_type")),
                _text(item.get("reference_unit_id")),
                _text(item.get("status")),
            )
            for item in document.get("quantity_kinds", ())
        ),
        units=tuple(
            UnitRecord(
                _text(item.get("unit_id")),
                _optional(item.get("ucum_code")),
                _optional(item.get("unece_code")),
                _text(item.get("symbol")),
                _text(item.get("status")),
            )
            for item in document.get("units", ())
        ),
        associations=tuple(
            AssociationRecord(
                _text(item.get("quantity_kind_id")),
                _text(item.get("unit_id")),
                _text(item.get("factor")),
                _text(item.get("offset")),
                _text(item.get("status")),
            )
            for item in document.get("quantity_kind_units", ())
        ),
        kind_names=tuple(
            KindNameRecord(
                _text(item.get("quantity_kind_id")),
                _text(item.get("locale_id")),
                _text(item.get("name")),
            )
            for item in document.get("quantity_kind_names", ())
        ),
        unit_names=tuple(
            UnitNameRecord(
                _text(item.get("unit_id")),
                _text(item.get("locale_id")),
                _text(item.get("name")),
                _optional(item.get("plural")),
            )
            for item in document.get("unit_names", ())
        ),
        provenance=document.get("provenance"),
    )


def is_uuid(value: Any) -> bool:
    return isinstance(value, str) and UUID_FORMAT.fullmatch(value) is not None


def is_trimmed(text: str) -> bool:
    """No vacío y sin espacios al inicio ni al final."""
    return bool(text) and text == text.strip()


@dataclass
class _Context:
    incoming: IncomingCatalog
    current: CatalogState
    locales: LocaleCatalog
    policy: RequiredLocales
    ucum: UcumEvaluator


Check = Callable[[_Context], list[Violation]]


def plan_catalog_changes(
    snapshot: Mapping[str, Any] | IncomingCatalog,
    current: CatalogState,
    locales: LocaleCatalog,
    policy: RequiredLocales,
    ucum_table: UcumTable,
) -> CatalogPlan:
    incoming = snapshot if isinstance(snapshot, IncomingCatalog) else incoming_from(snapshot)
    context = _Context(incoming, current, locales, policy, UcumEvaluator(ucum_table))
    for check in _CHECKS:
        violations = check(context)
        if violations:
            return CatalogPlan(violations=tuple(violations))
    return _plan(incoming, current)


# --- paso 3: contexto (RF-19) --------------------------------------------------------------------


def _check_context(context: _Context) -> list[Violation]:
    locales, policy = context.locales, context.policy
    if locales.snapshot_version is None:
        return [Violation("RF-19", "no hay una versión vigente del catálogo de Locale")]
    published = {item.locale_id: item for item in locales.locales}
    found: list[Violation] = []
    for required in policy.locales:
        item = published.get(required.locale_id)
        if item is None:
            found.append(
                Violation("RF-19", f"el locale obligatorio {required.locale_id} no existe")
            )
        elif item.status != "active":
            found.append(
                Violation("RF-19", f"el locale obligatorio {required.locale_id} está inactive")
            )
        elif item.code != required.code:
            found.append(
                Violation(
                    "RF-19",
                    f"el locale obligatorio {required.locale_id} es «{item.code}» y la política "
                    f"espera «{required.code}»",
                )
            )
    return found


# --- paso 4: identidad y completitud (RF-2, RF-10, RF-18, RF-43) ---------------------------------


def _repeated[T](items: Sequence[T], key: Callable[[T], Any]) -> list[Any]:
    seen: set[Any] = set()
    repeated: list[Any] = []
    for item in items:
        value = key(item)
        if value in seen and value not in repeated:
            repeated.append(value)
        seen.add(value)
    return repeated


def _check_identity(context: _Context) -> list[Violation]:
    incoming, current = context.incoming, context.current
    found: list[Violation] = []
    for incoming_kind in incoming.quantity_kinds:
        if not is_uuid(incoming_kind.quantity_kind_id):
            found.append(
                Violation("RF-2", f"quantity_kind_id inválido: «{incoming_kind.quantity_kind_id}»")
            )
    for incoming_unit in incoming.units:
        if not is_uuid(incoming_unit.unit_id):
            found.append(Violation("RF-2", f"unit_id inválido: «{incoming_unit.unit_id}»"))
    for value in _repeated(incoming.quantity_kinds, lambda k: k.quantity_kind_id):
        found.append(Violation("RF-2", f"quantity_kind_id repetido: {value}"))
    for value in _repeated(incoming.units, lambda u: u.unit_id):
        found.append(Violation("RF-2", f"unit_id repetido: {value}"))
    for kind_id, unit_id in _repeated(
        incoming.associations, lambda a: (a.quantity_kind_id, a.unit_id)
    ):
        found.append(
            Violation("RF-10", f"asociación repetida: magnitud {kind_id}, unidad {unit_id}")
        )
    for kind_id, locale_id in _repeated(
        incoming.kind_names, lambda n: (n.quantity_kind_id, n.locale_id)
    ):
        found.append(Violation("RF-18", f"localización repetida: magnitud {kind_id}, {locale_id}"))
    for unit_id, locale_id in _repeated(incoming.unit_names, lambda n: (n.unit_id, n.locale_id)):
        found.append(Violation("RF-18", f"localización repetida: unidad {unit_id}, {locale_id}"))

    kind_ids = {k.quantity_kind_id for k in incoming.quantity_kinds}
    for kind in current.quantity_kinds:
        if kind.quantity_kind_id not in kind_ids:
            found.append(
                Violation(
                    "RF-43",
                    f"el snapshot omite la magnitud publicada {kind.code} "
                    f"({kind.quantity_kind_id}); un retiro se expresa con status = inactive",
                )
            )
    unit_ids = {u.unit_id for u in incoming.units}
    for unit in current.units:
        if unit.unit_id not in unit_ids:
            found.append(
                Violation(
                    "RF-43",
                    f"el snapshot omite la unidad publicada {unit.symbol} ({unit.unit_id}); "
                    "un retiro se expresa con status = inactive",
                )
            )
    pairs = {(a.quantity_kind_id, a.unit_id) for a in incoming.associations}
    for association in current.associations:
        if (association.quantity_kind_id, association.unit_id) not in pairs:
            found.append(
                Violation(
                    "RF-43",
                    "el snapshot omite la asociación publicada (magnitud "
                    f"{association.quantity_kind_id}, unidad {association.unit_id})",
                )
            )
    kind_name_pairs = {(n.quantity_kind_id, n.locale_id) for n in incoming.kind_names}
    for kind_name in current.kind_names:
        if (kind_name.quantity_kind_id, kind_name.locale_id) not in kind_name_pairs:
            found.append(
                Violation(
                    "RF-43",
                    "el snapshot omite la localización publicada de la magnitud "
                    f"{kind_name.quantity_kind_id} ({kind_name.locale_id})",
                )
            )
    unit_name_pairs = {(n.unit_id, n.locale_id) for n in incoming.unit_names}
    for unit_name in current.unit_names:
        if (unit_name.unit_id, unit_name.locale_id) not in unit_name_pairs:
            found.append(
                Violation(
                    "RF-43",
                    "el snapshot omite la localización publicada de la unidad "
                    f"{unit_name.unit_id} ({unit_name.locale_id})",
                )
            )
    return found


# --- paso 5: códigos (RF-3, RF-4, RF-5) ----------------------------------------------------------


def _check_codes(context: _Context) -> list[Violation]:
    incoming, current = context.incoming, context.current
    found: list[Violation] = []
    for kind in incoming.quantity_kinds:
        if KIND_CODE.fullmatch(kind.code) is None:
            found.append(
                Violation(
                    "RF-4", f"código de magnitud inválido «{kind.code}» ({kind.quantity_kind_id})"
                )
            )
    for unit in incoming.units:
        label = f"{unit.symbol or '?'} ({unit.unit_id})"
        if not is_trimmed(unit.symbol):
            found.append(
                Violation("RF-4", f"símbolo vacío o con espacios en los bordes en {label}")
            )
        if unit.unece_code is not None and UNECE_CODE.fullmatch(unit.unece_code) is None:
            found.append(Violation("RF-4", f"código UNECE inválido «{unit.unece_code}» en {label}"))
        if unit.ucum_code is not None and not unit.ucum_code:
            found.append(Violation("RF-4", f"código UCUM vacío en {label}"))
    return found + _check_unique_codes(incoming) + _check_published_codes(incoming, current)


def _check_unique_codes(incoming: IncomingCatalog) -> list[Violation]:
    found: list[Violation] = []
    for code in _repeated(incoming.quantity_kinds, lambda k: k.code):
        found.append(Violation("RF-3", f"el código de magnitud {code} está repetido"))
    ucum = [u for u in incoming.units if u.ucum_code]
    for code in _repeated(ucum, lambda u: u.ucum_code):
        found.append(Violation("RF-3", f"el código UCUM {code} está repetido entre unidades"))
    unece = [u for u in incoming.units if u.unece_code]
    for code in _repeated(unece, lambda u: u.unece_code):
        found.append(Violation("RF-3", f"el código UNECE {code} está repetido entre unidades"))
    return found


def _check_published_codes(incoming: IncomingCatalog, current: CatalogState) -> list[Violation]:
    found: list[Violation] = []
    kinds_before = {k.quantity_kind_id: k for k in current.quantity_kinds}
    kind_owner = {k.code: k.quantity_kind_id for k in current.quantity_kinds}
    for kind in incoming.quantity_kinds:
        before = kinds_before.get(kind.quantity_kind_id)
        if before is not None and before.code != kind.code:
            found.append(
                Violation(
                    "RF-5",
                    f"el snapshot cambia el código de la magnitud {before.code} a {kind.code}; "
                    "un código nuevo es una magnitud nueva",
                )
            )
        owner = kind_owner.get(kind.code)
        if owner is not None and owner != kind.quantity_kind_id:
            found.append(
                Violation(
                    "RF-5",
                    f"el snapshot asigna el código publicado {kind.code} a otra magnitud "
                    f"({kind.quantity_kind_id})",
                )
            )
    units_before = {u.unit_id: u for u in current.units}
    ucum_owner = {u.ucum_code: u.unit_id for u in current.units if u.ucum_code}
    unece_owner = {u.unece_code: u.unit_id for u in current.units if u.unece_code}
    for unit in incoming.units:
        before_unit = units_before.get(unit.unit_id)
        for field, before_code, code, owners in (
            ("UCUM", before_unit and before_unit.ucum_code, unit.ucum_code, ucum_owner),
            ("UNECE", before_unit and before_unit.unece_code, unit.unece_code, unece_owner),
        ):
            if before_code is not None and before_code != code:
                found.append(
                    Violation(
                        "RF-5",
                        f"el snapshot cambia el código {field} publicado de la unidad "
                        f"{unit.symbol} de {before_code} a {code or 'nulo'}; solo se completa "
                        "un código ausente, una única vez",
                    )
                )
            owner = owners.get(code) if code else None
            if owner is not None and owner != unit.unit_id:
                found.append(
                    Violation(
                        "RF-5",
                        f"el snapshot asigna el código {field} publicado {code} a otra unidad "
                        f"({unit.unit_id})",
                    )
                )
    return found


# --- paso 6: magnitudes (RF-5, RF-7, RF-8, RF-12) ------------------------------------------------


def _check_kinds(context: _Context) -> list[Violation]:
    incoming, current = context.incoming, context.current
    found: list[Violation] = []
    published = {k.quantity_kind_id: k for k in current.quantity_kinds}
    units = {u.unit_id: u for u in incoming.units}
    pairs = {(a.quantity_kind_id, a.unit_id): a for a in incoming.associations}
    for unit in incoming.units:
        if unit.status not in STATUSES:
            found.append(Violation("RF-7", f"status inválido «{unit.status}» en {unit.symbol}"))
    for kind in incoming.quantity_kinds:
        found += _kind_violations(kind, published.get(kind.quantity_kind_id), units, pairs)
    return found


def _kind_violations(
    kind: QuantityKindRecord,
    before: QuantityKindRecord | None,
    units: Mapping[str, UnitRecord],
    pairs: Mapping[tuple[str, str], AssociationRecord],
) -> list[Violation]:
    found: list[Violation] = []
    if kind.status not in STATUSES:
        found.append(Violation("RF-7", f"status inválido «{kind.status}» en {kind.code}"))
    if kind.conversion_type not in CONVERSION_TYPES:
        found.append(
            Violation(
                "RF-12", f"tipo de conversión inválido «{kind.conversion_type}» en {kind.code}"
            )
        )
    if before is not None:
        if before.conversion_type != kind.conversion_type:
            found.append(
                Violation(
                    "RF-5",
                    f"el snapshot cambia el tipo de conversión de {kind.code} de "
                    f"{before.conversion_type} a {kind.conversion_type}",
                )
            )
        if before.reference_unit_id != kind.reference_unit_id:
            found.append(
                Violation(
                    "RF-5",
                    f"el snapshot cambia la unidad de referencia de {kind.code} de "
                    f"{before.reference_unit_id} a {kind.reference_unit_id}",
                )
            )
    reference = pairs.get((kind.quantity_kind_id, kind.reference_unit_id))
    if reference is None:
        found.append(
            Violation(
                "RF-8",
                f"la unidad de referencia {kind.reference_unit_id} de {kind.code} no es una "
                "asociación de la magnitud",
            )
        )
        return found
    if reference.factor != "1" or reference.offset != "0":
        found.append(
            Violation(
                "RF-8",
                f"la asociación de referencia de {kind.code} debe tener factor 1 y desplazamiento "
                f"0 (tiene {reference.factor} y {reference.offset})",
            )
        )
    if kind.status == "active":
        reference_unit = units.get(kind.reference_unit_id)
        if reference.status == "inactive":
            found.append(
                Violation("RF-8", f"{kind.code} está active y su asociación de referencia inactive")
            )
        if reference_unit is not None and reference_unit.status == "inactive":
            found.append(
                Violation("RF-8", f"{kind.code} está active y su unidad de referencia inactive")
            )
    return found


# --- paso 7: asociaciones (RF-7, RF-10, RF-12, RF-13) --------------------------------------------


def _check_associations(context: _Context) -> list[Violation]:
    incoming = context.incoming
    kinds = {k.quantity_kind_id: k for k in incoming.quantity_kinds}
    unit_ids = {u.unit_id for u in incoming.units}
    found: list[Violation] = []
    for association in incoming.associations:
        label = f"(magnitud {association.quantity_kind_id}, unidad {association.unit_id})"
        kind = kinds.get(association.quantity_kind_id)
        if kind is None:
            found.append(
                Violation("RF-10", f"la asociación {label} apunta a una magnitud inexistente")
            )
        if association.unit_id not in unit_ids:
            found.append(
                Violation("RF-10", f"la asociación {label} apunta a una unidad inexistente")
            )
        if association.status not in STATUSES:
            found.append(Violation("RF-7", f"status inválido «{association.status}» en {label}"))
        try:
            parse_canonical_factor(association.factor)
        except NumericFormatError:
            found.append(
                Violation(
                    "RF-13", f"factor no canónico «{association.factor}» en la asociación {label}"
                )
            )
        try:
            offset = parse_canonical_offset(association.offset)
        except NumericFormatError:
            found.append(
                Violation(
                    "RF-13",
                    f"desplazamiento no canónico «{association.offset}» en la asociación {label}",
                )
            )
        else:
            if kind is not None and kind.conversion_type == "linear" and offset != 0:
                found.append(
                    Violation(
                        "RF-12",
                        f"la magnitud {kind.code} es linear y la asociación {label} tiene "
                        f"desplazamiento {association.offset}",
                    )
                )
    return found


# --- paso 8: UCUM y verificación cruzada (RF-15, RF-16) ------------------------------------------


def _check_ucum(context: _Context) -> list[Violation]:
    incoming, ucum = context.incoming, context.ucum
    found: list[Violation] = []
    quantities: dict[str, UcumQuantity] = {}
    for unit in incoming.units:
        if not unit.ucum_code:
            continue
        try:
            quantities[unit.unit_id] = ucum.evaluate(unit.ucum_code)
        except UcumError as error:
            found.append(
                Violation(
                    "RF-15",
                    f"código UCUM «{unit.ucum_code}» de la unidad {unit.symbol} "
                    f"({unit.unit_id}): {error}",
                )
            )
    kinds = {k.quantity_kind_id: k for k in incoming.quantity_kinds}
    symbols = {u.unit_id: u.symbol for u in incoming.units}
    for association in incoming.associations:
        kind = kinds[association.quantity_kind_id]
        own = quantities.get(association.unit_id)
        reference = quantities.get(kind.reference_unit_id)
        if own is None or reference is None:
            continue
        found += _cross_check(
            association,
            kind,
            own,
            reference,
            f"{kind.code}/{symbols[association.unit_id]}",
        )
    return found


def _fraction_text(value: Fraction) -> str:
    """Forma canónica de `value` (decimal si termina, `p/q` si no) para los mensajes."""
    remainder = value.denominator
    while remainder % 2 == 0:
        remainder //= 2
    while remainder % 5 == 0:
        remainder //= 5
    if remainder != 1:
        return f"{value.numerator}/{value.denominator}"
    places = 0
    while (10**places) % value.denominator:
        places += 1
    scaled = abs(value.numerator) * (10**places // value.denominator)
    digits = str(scaled).rjust(places + 1, "0")
    whole, fraction = digits[: len(digits) - places], digits[len(digits) - places :]
    text = f"{whole}.{fraction}" if fraction else whole
    return "-" + text if value < 0 else text


def _cross_check(
    association: AssociationRecord,
    kind: QuantityKindRecord,
    own: UcumQuantity,
    reference: UcumQuantity,
    label: str,
) -> list[Violation]:
    """D9: dimensiones iguales; `factor = sU/sR`; `offset = oU − oR·sR/sU` (0 en `linear`)."""
    if own.dimension != reference.dimension:
        return [
            Violation(
                "RF-16",
                f"{label}: la dimensión UCUM de la unidad no coincide con la de la referencia",
            )
        ]
    found: list[Violation] = []
    expected_factor = own.scale / reference.scale
    expected_offset = (
        own.offset - reference.offset * reference.scale / own.scale
        if kind.conversion_type == "affine"
        else Fraction(0)
    )
    declared_factor = parse_canonical_factor(association.factor)
    declared_offset = parse_canonical_offset(association.offset)
    if declared_factor != expected_factor:
        found.append(
            Violation(
                "RF-16",
                f"{label}: factor declarado {association.factor} distinto del de UCUM "
                f"{_fraction_text(expected_factor)}",
            )
        )
    if declared_offset != expected_offset:
        found.append(
            Violation(
                "RF-16",
                f"{label}: desplazamiento declarado {association.offset} distinto del de UCUM "
                f"{_fraction_text(expected_offset)}",
            )
        )
    return found


# --- paso 9: localizaciones (RF-18, RF-19) -------------------------------------------------------


def _check_localizations(context: _Context) -> list[Violation]:
    incoming, current, locales, policy = (
        context.incoming,
        context.current,
        context.locales,
        context.policy,
    )
    published = {item.locale_id: item for item in locales.locales}
    known_kind_names = {(n.quantity_kind_id, n.locale_id) for n in current.kind_names}
    known_unit_names = {(n.unit_id, n.locale_id) for n in current.unit_names}
    kind_ids = {k.quantity_kind_id for k in incoming.quantity_kinds}
    unit_ids = {u.unit_id for u in incoming.units}
    found: list[Violation] = []

    def locale_violations(locale_id: str, label: str, is_new: bool) -> list[Violation]:
        item = published.get(locale_id)
        if item is None:
            return [Violation("RF-18", f"{label} usa el locale inexistente {locale_id}")]
        if is_new and item.status != "active":
            return [Violation("RF-19", f"{label} nueva usa el locale inactive {locale_id}")]
        return []

    for kind_name in incoming.kind_names:
        label = (
            f"la localización de la magnitud {kind_name.quantity_kind_id} ({kind_name.locale_id})"
        )
        if kind_name.quantity_kind_id not in kind_ids:
            found.append(Violation("RF-18", f"{label} apunta a una magnitud inexistente"))
        if not is_trimmed(kind_name.name):
            found.append(
                Violation("RF-18", f"{label} tiene un nombre vacío o con espacios en los bordes")
            )
        found += locale_violations(
            kind_name.locale_id,
            label,
            (kind_name.quantity_kind_id, kind_name.locale_id) not in known_kind_names,
        )
    for unit_name in incoming.unit_names:
        label = f"la localización de la unidad {unit_name.unit_id} ({unit_name.locale_id})"
        if unit_name.unit_id not in unit_ids:
            found.append(Violation("RF-18", f"{label} apunta a una unidad inexistente"))
        if not is_trimmed(unit_name.name):
            found.append(
                Violation("RF-18", f"{label} tiene un nombre vacío o con espacios en los bordes")
            )
        if unit_name.plural is not None and not is_trimmed(unit_name.plural):
            found.append(
                Violation("RF-18", f"{label} tiene un plural vacío o con espacios en los bordes")
            )
        found += locale_violations(
            unit_name.locale_id,
            label,
            (unit_name.unit_id, unit_name.locale_id) not in known_unit_names,
        )

    kind_pairs = {(n.quantity_kind_id, n.locale_id) for n in incoming.kind_names}
    unit_pairs = {(n.unit_id, n.locale_id) for n in incoming.unit_names}
    for required in policy.locales:
        for kind in incoming.quantity_kinds:
            if (kind.quantity_kind_id, required.locale_id) not in kind_pairs:
                found.append(
                    Violation(
                        "RF-19",
                        f"la magnitud {kind.code} ({kind.quantity_kind_id}) no tiene nombre en el "
                        f"locale obligatorio {required.code} ({required.locale_id})",
                    )
                )
        for unit in incoming.units:
            if (unit.unit_id, required.locale_id) not in unit_pairs:
                found.append(
                    Violation(
                        "RF-19",
                        f"la unidad {unit.symbol} ({unit.unit_id}) no tiene nombre en el locale "
                        f"obligatorio {required.code} ({required.locale_id})",
                    )
                )
    return found


# --- paso 10: procedencia (RF-41) ----------------------------------------------------------------


def _check_provenance(context: _Context) -> list[Violation]:
    provenance = context.incoming.provenance
    if not isinstance(provenance, Mapping):
        return [Violation("RF-41", "el snapshot no trae procedencia")]
    sources = provenance.get("sources")
    if not isinstance(sources, list):
        return [Violation("RF-41", "la procedencia no trae la lista de fuentes")]
    found: list[Violation] = []
    roles: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping):
            found.append(Violation("RF-41", "una fuente de la procedencia no es un objeto"))
            continue
        role = source.get("role")
        roles.add(role if isinstance(role, str) else "")
        for field in SOURCE_FIELDS:
            value = source.get(field)
            if not isinstance(value, str) or not value.strip():
                found.append(
                    Violation("RF-41", f"la fuente «{role}» no trae {field} (o está vacío)")
                )
    required = list(REQUIRED_ROLES)
    if any(unit.unece_code for unit in context.incoming.units):
        required.append("unece")
    for role in required:
        if role not in roles:
            found.append(Violation("RF-41", f"falta la fuente con rol «{role}» en la procedencia"))
    conflicts = provenance.get("unresolved_conflicts")
    if not isinstance(conflicts, list):
        found.append(Violation("RF-41", "la procedencia no declara unresolved_conflicts"))
    elif conflicts:
        found.append(
            Violation("RF-41", f"la procedencia tiene {len(conflicts)} conflicto(s) sin resolver")
        )
    return found


# --- plan de cambios ------------------------------------------------------------------------------

_CHECKS: tuple[Check, ...] = (
    _check_context,
    _check_identity,
    _check_codes,
    _check_kinds,
    _check_associations,
    _check_ucum,
    _check_localizations,
    _check_provenance,
)


def _split[T](
    items: Sequence[T], key: Callable[[T], Any], before: Mapping[Any, T]
) -> tuple[tuple[T, ...], tuple[T, ...]]:
    new = tuple(item for item in items if key(item) not in before)
    updated = tuple(item for item in items if key(item) in before and before[key(item)] != item)
    return new, updated


def _plan(incoming: IncomingCatalog, current: CatalogState) -> CatalogPlan:
    new_units, updated_units = _split(
        incoming.units, lambda u: u.unit_id, {u.unit_id: u for u in current.units}
    )
    new_kinds, updated_kinds = _split(
        incoming.quantity_kinds,
        lambda k: k.quantity_kind_id,
        {k.quantity_kind_id: k for k in current.quantity_kinds},
    )
    new_associations, updated_associations = _split(
        incoming.associations,
        lambda a: (a.quantity_kind_id, a.unit_id),
        {(a.quantity_kind_id, a.unit_id): a for a in current.associations},
    )
    new_kind_names, updated_kind_names = _split(
        incoming.kind_names,
        lambda n: (n.quantity_kind_id, n.locale_id),
        {(n.quantity_kind_id, n.locale_id): n for n in current.kind_names},
    )
    new_unit_names, updated_unit_names = _split(
        incoming.unit_names,
        lambda n: (n.unit_id, n.locale_id),
        {(n.unit_id, n.locale_id): n for n in current.unit_names},
    )
    return CatalogPlan(
        new_units=new_units,
        updated_units=updated_units,
        new_quantity_kinds=new_kinds,
        updated_quantity_kinds=updated_kinds,
        new_associations=new_associations,
        updated_associations=updated_associations,
        new_kind_names=new_kind_names,
        updated_kind_names=updated_kind_names,
        new_unit_names=new_unit_names,
        updated_unit_names=updated_unit_names,
    )
