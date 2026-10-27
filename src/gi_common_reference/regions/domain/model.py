"""Tipos compartidos del dominio de Region/Subregion.

Ninguna entidad lleva textos: los nombres viven en `NameRecord` y se relacionan con el idioma solo
por `locale_id` (RF-8, RF-12).
"""

from dataclasses import dataclass
from typing import Any, Literal

EntityType = Literal["region", "subregion"]
ENTITY_TYPES: tuple[EntityType, ...] = ("region", "subregion")
STATUSES = ("active", "inactive")


@dataclass(frozen=True)
class Violation:
    """Motivo de rechazo de un snapshot: `rule` es el requisito de la spec (p. ej. `RF-22`)."""

    rule: str
    message: str


@dataclass(frozen=True)
class RegionRecord:
    """Una Region tal como viaja en un snapshot o como está persistida."""

    region_id: str
    code: str | None
    status: str
    replacement_region_id: str | None


@dataclass(frozen=True)
class SubregionRecord:
    """Una Subregion: pertenece a exactamente una Region (`region_id`)."""

    subregion_id: str
    region_id: str
    code: str | None
    status: str
    replacement_subregion_id: str | None


@dataclass(frozen=True)
class NameRecord:
    """Nombre de una entidad (`entity_id`) en un `locale_id` (RegionLocale o SubregionLocale)."""

    entity_id: str
    locale_id: str
    name: str


@dataclass(frozen=True)
class Recoding:
    """Recodificación declarada en un snapshot: mismo id, otro código vigente (RF-39)."""

    entity_type: str
    entity_id: str
    previous_code: str | None
    new_code: str | None
    provenance: Any


@dataclass(frozen=True)
class Reassignment:
    """Reasignación declarada: el id recibe un código vigente o histórico de otro id (RF-41)."""

    entity_type: str
    entity_id: str
    code: str
    provenance: Any


@dataclass(frozen=True)
class Reclassification:
    """Cambio de la Region padre de una Subregion con el mismo id y código (RF-6, RF-34)."""

    subregion_id: str
    previous_region_id: str
    new_region_id: str


@dataclass(frozen=True)
class LocaleInfo:
    """Lo que Regions necesita saber de un locale publicado en el catálogo de Locale."""

    locale_id: str
    code: str
    status: str


@dataclass(frozen=True)
class CatalogState:
    """Estado vigente del catálogo, con los códigos históricos de cada entidad (RF-41)."""

    regions: tuple[RegionRecord, ...] = ()
    subregions: tuple[SubregionRecord, ...] = ()
    region_names: tuple[NameRecord, ...] = ()
    subregion_names: tuple[NameRecord, ...] = ()
    historical_codes: tuple[tuple[EntityType, str, str], ...] = ()  # (tipo, id, código anterior)


@dataclass(frozen=True)
class LocaleCatalog:
    """Vista del catálogo de Locale contra la que se valida un snapshot (RF-28, RF-33, RF-38)."""

    snapshot_version: int | None
    locales: tuple[LocaleInfo, ...] = ()
