"""Tipos compartidos del dominio de Countries.

Country no lleva textos: los nombres viven en `NameRecord` y se relacionan con el idioma solo por
`locale_id` (RF-31, RF-34). La clasificación se referencia por `region_id` y `subregion_id` de
Region/Subregion (RF-6); no hay códigos ni nombres de región en este módulo.
"""

from dataclasses import dataclass
from typing import Any, Literal

CodeKind = Literal["alpha2", "alpha3", "numeric_code"]
CODE_KINDS: tuple[CodeKind, ...] = ("alpha2", "alpha3", "numeric_code")
STATUSES = ("active", "inactive")


@dataclass(frozen=True)
class Violation:
    """Motivo de rechazo de un snapshot: `rule` es el requisito de la spec (p. ej. `RF-21`)."""

    rule: str
    message: str


@dataclass(frozen=True)
class CodeTriple:
    """Tripleta indivisible de la misma entrada ISO 3166-1 (RF-4)."""

    alpha2: str
    alpha3: str
    numeric_code: str

    def code(self, kind: CodeKind) -> str:
        return {"alpha2": self.alpha2, "alpha3": self.alpha3, "numeric_code": self.numeric_code}[
            kind
        ]


@dataclass(frozen=True)
class CountryRecord:
    """Un Country tal como viaja en un snapshot o como está persistido (sin ningún texto)."""

    country_id: str
    alpha2: str
    alpha3: str
    numeric_code: str
    region_id: str | None
    subregion_id: str | None
    calling_code: str | None
    status: str
    replacement_country_id: str | None

    @property
    def triple(self) -> CodeTriple:
        return CodeTriple(self.alpha2, self.alpha3, self.numeric_code)


@dataclass(frozen=True)
class NameRecord:
    """CountryLocale: `name` y `official_name` de un país en un `locale_id` (RF-31)."""

    country_id: str
    locale_id: str
    name: str
    official_name: str | None


@dataclass(frozen=True)
class FlagDeclaration:
    """Referencia a un asset SVG del repositorio declarada en el snapshot (RF-19, RF-49)."""

    country_id: str
    asset_path: str
    sha256: str
    media_type: str
    source: str


@dataclass(frozen=True)
class FlagException:
    """Un Country `active` declarado sin bandera, con su motivo (RF-19)."""

    country_id: str
    reason: str


@dataclass(frozen=True)
class FlagRecord:
    """Bandera persistida: un asset o una excepción declarada, nunca ambas."""

    country_id: str
    asset_path: str | None
    sha256: str | None
    exception_reason: str | None


@dataclass(frozen=True)
class Recoding:
    """Recodificación declarada: el mismo país cambia su tripleta ISO (RF-41)."""

    country_id: str
    previous: CodeTriple
    new: CodeTriple
    provenance: Any


@dataclass(frozen=True)
class Reassignment:
    """Reasignación declarada: el país recibe un código vigente o histórico de otro (RF-43)."""

    country_id: str
    code_kind: str
    code: str
    provenance: Any


@dataclass(frozen=True)
class LocaleInfo:
    """Lo que Countries necesita saber de un locale publicado en el catálogo de Locale."""

    locale_id: str
    code: str
    status: str


@dataclass(frozen=True)
class LocaleCatalog:
    """Vista del catálogo de Locale contra la que se valida un snapshot (RF-35, RF-36)."""

    snapshot_version: int | None
    locales: tuple[LocaleInfo, ...] = ()


@dataclass(frozen=True)
class RegionInfo:
    region_id: str
    status: str


@dataclass(frozen=True)
class SubregionInfo:
    subregion_id: str
    region_id: str
    status: str


@dataclass(frozen=True)
class RegionCatalog:
    """Vista del catálogo Region/Subregion vigente (RF-47, RF-48).

    `incorporated_versions` son todas las versiones incorporadas; `snapshot_version` es la vigente.
    """

    snapshot_version: int | None
    incorporated_versions: frozenset[int] = frozenset()
    regions: tuple[RegionInfo, ...] = ()
    subregions: tuple[SubregionInfo, ...] = ()


@dataclass(frozen=True)
class CatalogState:
    """Estado vigente del catálogo, con los códigos históricos de cada país (RF-43).

    `historical_codes` son tuplas (tipo de código, código, country_id) que un país tuvo antes de
    una recodificación y ya no tiene vigentes.
    """

    countries: tuple[CountryRecord, ...] = ()
    names: tuple[NameRecord, ...] = ()
    flags: tuple[FlagRecord, ...] = ()
    historical_codes: tuple[tuple[CodeKind, str, str], ...] = ()
