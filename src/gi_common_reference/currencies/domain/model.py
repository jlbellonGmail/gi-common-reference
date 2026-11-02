"""Tipos compartidos del dominio de Currency.

Currency no lleva textos: los nombres viven en `NameRecord` y se relacionan con el idioma solo por
`locale_id` (RF-12, D-4). CountryCurrency referencia a Country solo por `country_id` (RF-20); no
hay ningún dato de país en este módulo. `status` y vigencia son independientes (RF-51).
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

STATUSES = ("active", "inactive")


@dataclass(frozen=True)
class Violation:
    """Motivo de rechazo de un snapshot: `rule` es el requisito de la spec (p. ej. `RF-37`)."""

    rule: str
    message: str


@dataclass(frozen=True)
class CurrencyRecord:
    """Una Currency tal como viaja en un snapshot o como está persistida (sin ningún texto).

    `minor_units` es `None` para «no aplicable» (ISO N.A.), distinto de `0` (CL-1).
    """

    currency_id: str
    alphabetic_code: str
    numeric_code: str
    minor_units: int | None
    fund_code: bool
    status: str
    replacement_currency_ids: tuple[str, ...]  # 0..N sucesoras, ascendente por currency_id (D-17)


@dataclass(frozen=True)
class NameRecord:
    """CurrencyLocale: nombre de una Currency en un `locale_id` (RF-12). Solo el nombre (D-11)."""

    currency_id: str
    locale_id: str
    name: str


@dataclass(frozen=True)
class CountryCurrencyRecord:
    """Asociación Country–Currency con `status` y vigencia temporal propios (D-18).

    La vigencia es el período semiabierto `[valid_from, valid_to)` de días calendario; `None` es un
    extremo no acotado (RF-44).
    """

    country_currency_id: str
    country_id: str
    currency_id: str
    status: str
    valid_from: date | None
    valid_to: date | None


@dataclass(frozen=True)
class LocaleInfo:
    """Lo que Currency necesita saber de un locale publicado en el catálogo de Locale."""

    locale_id: str
    code: str
    status: str


@dataclass(frozen=True)
class LocaleCatalog:
    """Vista del catálogo de Locale contra la que se valida un snapshot (RF-13, RF-14)."""

    snapshot_version: int | None
    locales: tuple[LocaleInfo, ...] = ()


@dataclass(frozen=True)
class CountryInfo:
    """Lo que Currency necesita saber de un Country publicado por 003 (RF-19, RF-40)."""

    country_id: str
    status: str


@dataclass(frozen=True)
class CountryCatalog:
    """Vista del catálogo Countries vigente (RF-40, RF-41).

    `incorporated_versions` son todas las versiones incorporadas; `snapshot_version` es la vigente.
    """

    snapshot_version: int | None
    incorporated_versions: frozenset[int] = frozenset()
    countries: tuple[CountryInfo, ...] = ()


@dataclass(frozen=True)
class CatalogState:
    """Estado vigente del catálogo Currency."""

    currencies: tuple[CurrencyRecord, ...] = ()
    names: tuple[NameRecord, ...] = ()
    associations: tuple[CountryCurrencyRecord, ...] = ()


Document = dict[str, Any]
