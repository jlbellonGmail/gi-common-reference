"""Puertos del dominio de Currency: incorporación y verificación de integridad (D16, D22)."""

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
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
    "CatalogView",
    "CurrencyRepository",
    "IncorporationTransaction",
    "IntegrityViolation",
    "PolicyLoader",
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
