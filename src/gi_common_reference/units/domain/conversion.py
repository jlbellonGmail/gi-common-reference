"""Conversión pura entre unidades de una magnitud (D6 y D7 del plan, RF-21 a RF-30).

`convert(catalog, request)` es una función pura sobre un `ConversionCatalog` inmutable, construido
con el contenido de una versión del snapshot. No lee relojes, entorno ni persistencia (RF-30,
RF-31). La fórmula es `ref = (v + desp_origen) × factor_origen`; `salida = ref / factor_destino −
desp_destino`, con `Fraction` y un único redondeo final (RF-21, RF-27).

Orden de las verificaciones: formato de identidades → formato del valor → existencia de la magnitud
→ existencia de las unidades → magnitud activa → asociaciones existentes (compatibilidad) → unidades
y asociaciones activas → cálculo.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from gi_common_reference.units.domain.numeric import (
    NumericFormatError,
    ResultNotRepresentable,
    format_result,
    parse_canonical_factor,
    parse_canonical_offset,
    parse_value,
)

UUID_FORMAT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

QUANTITY_KIND_REQUIRED = "quantity_kind_required"
INVALID_QUANTITY_KIND_ID = "invalid_quantity_kind_id"
INVALID_UNIT_ID = "invalid_unit_id"
INVALID_VALUE = "invalid_value"
QUANTITY_KIND_NOT_FOUND = "quantity_kind_not_found"
UNIT_NOT_FOUND = "unit_not_found"
INACTIVE_QUANTITY_KIND = "inactive_quantity_kind"
INACTIVE_UNIT = "inactive_unit"
INCOMPATIBLE_UNITS = "incompatible_units"
RESULT_NOT_REPRESENTABLE = "result_not_representable"


@dataclass(frozen=True)
class ConversionAssociation:
    """Transformación de una unidad a la referencia de una magnitud: `(v + offset) × factor`."""

    factor: Fraction
    offset: Fraction
    status: str


@dataclass(frozen=True)
class ConversionRequest:
    quantity_kind_id: str | None
    value: str
    from_unit_id: str
    to_unit_id: str


@dataclass(frozen=True)
class ConversionSuccess:
    result: str
    exact: bool
    unit_id: str
    quantity_kind_id: str
    catalog_version: int


@dataclass(frozen=True)
class ConversionRejection:
    """Rechazo con un código estable (plan, «API pública»)."""

    code: str
    message: str


@dataclass(frozen=True)
class ConversionCatalog:
    """Catálogo inmutable de una versión: estados de magnitudes y unidades y sus asociaciones."""

    snapshot_version: int
    kinds: Mapping[str, str]
    units: Mapping[str, str]
    associations: Mapping[tuple[str, str], ConversionAssociation]

    @classmethod
    def from_content(
        cls,
        snapshot_version: int,
        *,
        quantity_kinds: Iterable[Mapping[str, Any]],
        units: Iterable[Mapping[str, Any]],
        quantity_kind_units: Iterable[Mapping[str, Any]],
    ) -> "ConversionCatalog":
        """Construye el catálogo copiando lo necesario: cambiar el origen después no lo altera."""
        associations: dict[tuple[str, str], ConversionAssociation] = {}
        for row in quantity_kind_units:
            key = (str(row["quantity_kind_id"]), str(row["unit_id"]))
            try:
                factor = parse_canonical_factor(row["factor"])
                offset = parse_canonical_offset(row["offset"])
            except NumericFormatError as error:
                raise ValueError(f"factor u offset no canónico en la asociación {key}") from error
            associations[key] = ConversionAssociation(factor, offset, str(row["status"]))
        return cls(
            snapshot_version,
            MappingProxyType(
                {str(k["quantity_kind_id"]): str(k["status"]) for k in quantity_kinds}
            ),
            MappingProxyType({str(u["unit_id"]): str(u["status"]) for u in units}),
            MappingProxyType(associations),
        )

    @classmethod
    def from_snapshot(cls, document: Mapping[str, Any]) -> "ConversionCatalog":
        return cls.from_content(
            document["snapshot_version"],
            quantity_kinds=document["quantity_kinds"],
            units=document["units"],
            quantity_kind_units=document["quantity_kind_units"],
        )


def transform(
    source: ConversionAssociation, target: ConversionAssociation, value: Fraction
) -> Fraction:
    """Valor exacto en la unidad destino: `((v + o_origen) × f_origen) / f_destino − o_destino`."""
    return (value + source.offset) * source.factor / target.factor - target.offset


def _is_uuid(value: object) -> bool:
    return isinstance(value, str) and UUID_FORMAT.fullmatch(value) is not None


def _reject(code: str, message: str) -> ConversionRejection:
    return ConversionRejection(code, message)


def convert(
    catalog: ConversionCatalog, request: ConversionRequest
) -> ConversionSuccess | ConversionRejection:
    kind_id = request.quantity_kind_id
    if kind_id is None:
        return _reject(QUANTITY_KIND_REQUIRED, "la magnitud es obligatoria y no se infiere")
    if not _is_uuid(kind_id):
        return _reject(INVALID_QUANTITY_KIND_ID, "quantity_kind_id no es un UUID")
    if not _is_uuid(request.from_unit_id):
        return _reject(INVALID_UNIT_ID, "from_unit_id no es un UUID")
    if not _is_uuid(request.to_unit_id):
        return _reject(INVALID_UNIT_ID, "to_unit_id no es un UUID")
    try:
        value = parse_value(request.value)
    except NumericFormatError:
        return _reject(INVALID_VALUE, "el valor no es un decimal admitido")

    kind_status = catalog.kinds.get(kind_id)
    if kind_status is None:
        return _reject(QUANTITY_KIND_NOT_FOUND, "la magnitud no existe en esta versión")
    for unit_id in (request.from_unit_id, request.to_unit_id):
        if unit_id not in catalog.units:
            return _reject(UNIT_NOT_FOUND, f"la unidad {unit_id} no existe en esta versión")
    if kind_status != "active":
        return _reject(INACTIVE_QUANTITY_KIND, "la magnitud está inactive")

    source = catalog.associations.get((kind_id, request.from_unit_id))
    target = catalog.associations.get((kind_id, request.to_unit_id))
    if source is None or target is None:
        return _reject(INCOMPATIBLE_UNITS, "una de las unidades no está asociada a la magnitud")
    for unit_id, association in (
        (request.from_unit_id, source),
        (request.to_unit_id, target),
    ):
        if catalog.units[unit_id] != "active" or association.status != "active":
            return _reject(INACTIVE_UNIT, f"la unidad {unit_id} o su asociación está inactive")

    try:
        text, exact = format_result(transform(source, target, value))
    except ResultNotRepresentable:
        return _reject(RESULT_NOT_REPRESENTABLE, "el resultado no es representable")
    return ConversionSuccess(text, exact, request.to_unit_id, kind_id, catalog.snapshot_version)
