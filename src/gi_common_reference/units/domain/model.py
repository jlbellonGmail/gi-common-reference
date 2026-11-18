"""Tipos compartidos del dominio de Units.

Units no lleva textos en las magnitudes ni en las unidades: los nombres viven en `NameRecord` y se
relacionan con el idioma solo por `locale_id` (RF-18). El símbolo es un texto neutral, no una
traducción. Factores y desplazamientos viajan como texto en forma canónica (RF-13): el dominio
numérico (T4) los interpreta con aritmética exacta; aquí solo se transportan.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

STATUSES = ("active", "inactive")
CONVERSION_TYPES = ("linear", "affine")


@dataclass(frozen=True)
class Violation:
    """Motivo de rechazo de un snapshot: `rule` es el requisito de la spec (p. ej. `RF-41`)."""

    rule: str
    message: str


@dataclass(frozen=True)
class QuantityKindRecord:
    """Una magnitud tal como viaja en un snapshot o como está persistida (sin ningún texto)."""

    quantity_kind_id: str
    code: str
    conversion_type: str
    reference_unit_id: str
    status: str


@dataclass(frozen=True)
class UnitRecord:
    """Una unidad: los códigos UCUM y UNECE son opcionales (`None`) y el símbolo es neutral."""

    unit_id: str
    ucum_code: str | None
    unece_code: str | None
    symbol: str
    status: str


@dataclass(frozen=True)
class AssociationRecord:
    """Asociación magnitud–unidad: `ref = (valor + offset) × factor` (RF-11), ambos como texto."""

    quantity_kind_id: str
    unit_id: str
    factor: str
    offset: str
    status: str


@dataclass(frozen=True)
class KindNameRecord:
    """Nombre de una magnitud en un `locale_id`."""

    quantity_kind_id: str
    locale_id: str
    name: str


@dataclass(frozen=True)
class UnitNameRecord:
    """Nombre de una unidad en un `locale_id`; `plural` es opcional."""

    unit_id: str
    locale_id: str
    name: str
    plural: str | None


@dataclass(frozen=True)
class LocaleInfo:
    """Lo que Units necesita saber de un locale publicado en el catálogo de Locale."""

    locale_id: str
    code: str
    status: str


@dataclass(frozen=True)
class LocaleCatalog:
    """Vista del catálogo de Locale contra la que se valida un snapshot (RF-18, RF-19)."""

    snapshot_version: int | None
    locales: tuple[LocaleInfo, ...] = ()


@dataclass(frozen=True)
class CatalogState:
    """Estado vigente del catálogo Units."""

    quantity_kinds: tuple[QuantityKindRecord, ...] = ()
    units: tuple[UnitRecord, ...] = ()
    associations: tuple[AssociationRecord, ...] = ()
    kind_names: tuple[KindNameRecord, ...] = ()
    unit_names: tuple[UnitNameRecord, ...] = ()


@dataclass(frozen=True)
class UcumPrefix:
    """Prefijo de la tabla UCUM: `value` es el texto del archivo (`1e3`, `1024`)."""

    code: str
    value: str


@dataclass(frozen=True)
class UcumFunction:
    """Función de una unidad especial (`<function name= value= Unit=>`); solo la nombra el XML."""

    name: str
    value: str
    unit: str


@dataclass(frozen=True)
class UcumAtom:
    """Unidad base (`dimension`) o átomo de la tabla UCUM, con su definición en texto.

    `value` y `unit` son los del archivo (`value="5280" Unit="[ft_i]"`); una unidad base no tiene
    definición. Una especial no tiene `value` y sí `function`.
    """

    code: str
    is_metric: bool
    is_special: bool
    is_arbitrary: bool
    dimension: str | None = None
    value: str | None = None
    unit: str | None = None
    function: UcumFunction | None = None


@dataclass(frozen=True)
class UcumTable:
    """Tabla UCUM oficial empaquetada y verificada (D8): prefijos y átomos por código."""

    version: str
    revision_date: str
    sha256: str
    prefixes: Mapping[str, UcumPrefix]
    atoms: Mapping[str, UcumAtom]


Document = dict[str, Any]
