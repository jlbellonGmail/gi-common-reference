"""Puertos del dominio de Currency: incorporación y verificación de integridad (D16, D22)."""

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from gi_common_reference.currencies.domain.errors import SnapshotFormatError
from gi_common_reference.currencies.domain.model import (
    CatalogState,
    CountryCatalog,
    CountryCurrencyRecord,
    CurrencyRecord,
    LocaleCatalog,
    NameRecord,
)
from gi_common_reference.currencies.domain.policy import RequiredLocales
from gi_common_reference.currencies.domain.snapshot import HistoricalSnapshot

__all__ = [
    "AssociationView",
    "CatalogView",
    "Clock",
    "CurrencyReader",
    "CurrencyRepository",
    "CurrencySession",
    "CurrencyView",
    "IncorporationTransaction",
    "IntegrityViolation",
    "PolicyLoader",
    "ReaderUnavailable",
    "SnapshotFormatError",
    "SnapshotReader",
]

SnapshotReader = Callable[[Path], dict[str, Any]]
"""Lee un archivo local de snapshot y devuelve su documento ya validado contra el schema."""

PolicyLoader = Callable[[], RequiredLocales]
"""Carga el conjunto obligatorio de locales versionado en el repositorio (RF-13)."""


@dataclass(frozen=True)
class IntegrityViolation:
    """Asociación `active` de vigencia abierta sobre un Country o una Currency `inactive` (RF-19).

    Puede aparecer entre incorporaciones si Countries retira un país sin conocer Currency (S-8).
    """

    country_currency_id: str
    country_id: str
    currency_id: str
    country_not_active: bool
    currency_not_active: bool


class CatalogView(Protocol):
    """Lo que hace falta leer para validar un snapshot contra el catálogo vigente."""

    def history(self) -> Sequence[HistoricalSnapshot]: ...

    def current_state(self) -> CatalogState: ...

    def locale_catalog(self) -> LocaleCatalog: ...

    def country_catalog(self) -> CountryCatalog: ...

    def integrity_violations(self) -> Sequence[IntegrityViolation]: ...


class IncorporationTransaction(CatalogView, Protocol):
    """Una transacción de incorporación. Las escrituras se llaman en el orden del plan (paso 10)."""

    def insert_snapshot(
        self,
        document: Mapping[str, Any],
        locale_snapshot_version: int,
        country_current_snapshot_version: int,
        policy_version: int,
    ) -> None: ...

    def insert_currencies(self, currencies: Sequence[CurrencyRecord], version: int) -> None: ...

    def update_currencies(self, currencies: Sequence[CurrencyRecord], version: int) -> None: ...

    def insert_names(self, names: Sequence[NameRecord]) -> None: ...

    def update_names(self, names: Sequence[NameRecord]) -> None: ...

    def insert_associations(
        self, associations: Sequence[CountryCurrencyRecord], version: int
    ) -> None: ...

    def update_associations(
        self, associations: Sequence[CountryCurrencyRecord], version: int
    ) -> None: ...

    def touch_currencies(self, currency_ids: Sequence[str], version: int) -> None:
        """Marca el snapshot como el último que cambió el contenido de estas monedas."""
        ...

    def check_constraints(self) -> None:
        """Fuerza las constraints diferidas; una violación sale como `ConstraintRejected`."""
        ...


class CurrencyRepository(Protocol):
    def transaction(self) -> AbstractContextManager[IncorporationTransaction]:
        """Serializa las incorporaciones; confirma al salir sin error y deshace ante cualquiera."""
        ...

    def inspect(self) -> AbstractContextManager[CatalogView]:
        """Una vista de solo lectura del catálogo: no toma el lock exclusivo ni escribe (D22)."""
        ...


class ReaderUnavailable(Exception):
    """La fuente de lectura no responde (p. ej. la base está caída): error técnico (RF-26)."""


class Clock(Protocol):
    """Reloj inyectable: la única dependencia del tiempo es la fecha por defecto (RNF-7, D13)."""

    def today(self) -> date:
        """El día calendario UTC actual (D14)."""
        ...


@dataclass(frozen=True)
class CurrencyView:
    """Una Currency con su nombre en el locale pedido (`None` si no se pidió o no existe, RF-15)."""

    record: CurrencyRecord
    name: str | None


@dataclass(frozen=True)
class AssociationView:
    """Una CountryCurrency con la Currency que referencia (RF-29, RF-50)."""

    association: CountryCurrencyRecord
    currency: CurrencyView


class CurrencySession(Protocol):
    """Lecturas de una sesión consistente: todas ven el mismo estado del catálogo."""

    def snapshot_version(self) -> int | None: ...

    def locale_exists(self, locale_id: str) -> bool: ...

    def country_exists(self, country_id: str) -> bool:
        """El Country existe en el catálogo publicado por 003 (de ninguna manera se redefine)."""
        ...

    def currencies(
        self, include_inactive: bool, exclude_funds: bool, locale_id: str | None
    ) -> Sequence[CurrencyView]:
        """Orden determinista por código alfabético en orden binario y desempate por id."""
        ...

    def currency_by_id(self, currency_id: str, locale_id: str | None) -> CurrencyView | None: ...

    def currency_by_code(self, code: str, locale_id: str | None) -> CurrencyView | None:
        """`code` ya normalizado a mayúsculas."""
        ...

    def associations_of_country(
        self, country_id: str, locale_id: str | None
    ) -> Sequence[AssociationView]:
        """Todas las asociaciones del país (cualquier `status` y vigencia), sin ordenar."""
        ...

    def associations_of_currency(
        self, currency_id: str, locale_id: str | None
    ) -> Sequence[AssociationView]:
        """Todas las asociaciones de la moneda (cualquier `status` y vigencia), sin ordenar."""
        ...


class CurrencyReader(Protocol):
    def session(self) -> AbstractContextManager[CurrencySession]:
        """Una sesión de solo lectura; `snapshot_version` y los datos salen del mismo estado."""
        ...
