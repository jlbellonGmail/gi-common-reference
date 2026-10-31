"""Puertos del dominio de Countries: incorporación, consultas y banderas."""

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from gi_common_reference.countries.domain.model import (
    CatalogState,
    CountryRecord,
    FlagRecord,
    LocaleCatalog,
    NameRecord,
    Recoding,
    RegionCatalog,
)
from gi_common_reference.countries.domain.policy import RequiredLocales
from gi_common_reference.countries.domain.snapshot import HistoricalSnapshot


class SnapshotFormatError(ValueError):
    """El archivo no es un snapshot estructuralmente válido; `errors` lista cada problema."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


SnapshotReader = Callable[[Path], dict[str, Any]]
"""Lee un archivo local de snapshot y devuelve su documento ya validado contra el schema."""

PolicyLoader = Callable[[], RequiredLocales]
"""Carga el conjunto obligatorio de locales versionado en el repositorio (RF-35)."""


class FlagStore(Protocol):
    """Lee los assets de bandera del repositorio por ruta relativa (RF-49, RF-50)."""

    def read(self, asset_path: str) -> bytes | None:
        """Los bytes exactos del archivo, o `None` si no existe o la ruta no es segura."""
        ...


class CatalogView(Protocol):
    """Lo que hace falta leer para validar un snapshot contra el catálogo vigente."""

    def history(self) -> Sequence[HistoricalSnapshot]: ...

    def current_state(self) -> CatalogState: ...

    def locale_catalog(self) -> LocaleCatalog: ...

    def region_catalog(self) -> RegionCatalog: ...


class IncorporationTransaction(CatalogView, Protocol):
    """Una transacción de incorporación. Las escrituras se llaman en el orden del plan (paso 11)."""

    def insert_snapshot(
        self,
        document: Mapping[str, Any],
        locale_snapshot_version: int,
        region_current_snapshot_version: int,
        policy_version: int,
    ) -> None: ...

    def insert_countries(self, countries: Sequence[CountryRecord], version: int) -> None: ...

    def update_countries(self, countries: Sequence[CountryRecord], version: int) -> None: ...

    def record_recodings(self, recodings: Sequence[Recoding], version: int) -> None: ...

    def insert_names(self, names: Sequence[NameRecord]) -> None: ...

    def update_names(self, names: Sequence[NameRecord]) -> None: ...

    def write_flags(
        self, new: Sequence[FlagRecord], updated: Sequence[FlagRecord], version: int
    ) -> None: ...

    def touch_countries(self, country_ids: Sequence[str], version: int) -> None:
        """Marca el snapshot como el último que cambió el contenido de estos países (RF-51)."""
        ...

    def check_constraints(self) -> None:
        """Fuerza las constraints diferidas; una violación sale como `ConstraintRejected`."""
        ...


class CountryRepository(Protocol):
    def transaction(self) -> AbstractContextManager[IncorporationTransaction]:
        """Serializa las incorporaciones; confirma al salir sin error y deshace ante cualquiera."""
        ...

    def inspect(self) -> AbstractContextManager[CatalogView]:
        """Una vista de solo lectura del catálogo: no toma el lock exclusivo ni escribe (RF-30)."""
        ...
