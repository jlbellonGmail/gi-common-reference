"""Puertos del dominio de Countries: incorporación, consultas y banderas."""

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from gi_common_reference.countries.domain.model import (
    CatalogState,
    CodeKind,
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


class ReaderUnavailable(Exception):
    """La fuente de lectura no responde (p. ej. la base está caída)."""


@dataclass(frozen=True)
class CountryView:
    """Un Country con sus textos en el locale pedido (`None` si no se pidió o no existen, RF-38)."""

    record: CountryRecord
    name: str | None
    official_name: str | None


class CountrySession(Protocol):
    """Lecturas de una sesión consistente: todas ven el mismo estado del catálogo."""

    def snapshot_version(self) -> int | None: ...

    def locale_exists(self, locale_id: str) -> bool: ...

    def countries(
        self,
        status: str | None,
        region_id: str | None,
        subregion_id: str | None,
        locale_id: str | None,
    ) -> Sequence[CountryView]:
        """Orden determinista por `alpha2` en orden binario y desempate por `country_id`."""
        ...

    def country_by_id(self, country_id: str, locale_id: str | None) -> CountryView | None: ...

    def country_by_code(
        self, kind: CodeKind, code: str, locale_id: str | None
    ) -> CountryView | None:
        """El `active` que posee el código; si no, el `inactive` que lo obtuvo más recientemente."""
        ...

    def flag(self, country_id: str) -> FlagRecord | None: ...


class CountryReader(Protocol):
    def session(self) -> AbstractContextManager[CountrySession]:
        """Una sesión de solo lectura; `snapshot_version` y los datos salen del mismo estado."""
        ...
