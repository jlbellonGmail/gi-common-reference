"""Puertos del dominio de Region/Subregion: lo que la incorporación y las consultas necesitan."""

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from gi_common_reference.regions.domain.model import (
    CatalogState,
    LocaleCatalog,
    NameRecord,
    Reclassification,
    Recoding,
    RegionRecord,
    SubregionRecord,
)
from gi_common_reference.regions.domain.policy import RequiredLocales
from gi_common_reference.regions.domain.snapshot import HistoricalSnapshot


class SnapshotFormatError(ValueError):
    """El archivo no es un snapshot estructuralmente válido; `errors` lista cada problema."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


SnapshotReader = Callable[[Path], dict[str, Any]]
"""Lee un archivo local de snapshot y devuelve su documento ya validado contra el schema."""

PolicyLoader = Callable[[], RequiredLocales]
"""Carga el conjunto obligatorio de locales versionado en el repositorio (RF-31)."""


class IncorporationTransaction(Protocol):
    """Una transacción de incorporación. Las escrituras se llaman en el orden del plan (paso 8)."""

    def history(self) -> Sequence[HistoricalSnapshot]: ...

    def current_state(self) -> CatalogState: ...

    def locale_catalog(self) -> LocaleCatalog: ...

    def insert_snapshot(
        self, document: Mapping[str, Any], locale_snapshot_version: int, policy_version: int
    ) -> None: ...

    def insert_regions(self, regions: Sequence[RegionRecord], version: int) -> None: ...

    def update_regions(self, regions: Sequence[RegionRecord], version: int) -> None: ...

    def insert_subregions(self, subregions: Sequence[SubregionRecord], version: int) -> None: ...

    def update_subregions(self, subregions: Sequence[SubregionRecord], version: int) -> None: ...

    def record_reclassifications(
        self, reclassifications: Sequence[Reclassification], version: int
    ) -> None: ...

    def record_recodings(self, recodings: Sequence[Recoding], version: int) -> None: ...

    def insert_names(
        self, region_names: Sequence[NameRecord], subregion_names: Sequence[NameRecord]
    ) -> None: ...

    def update_names(
        self, region_names: Sequence[NameRecord], subregion_names: Sequence[NameRecord]
    ) -> None: ...

    def check_constraints(self) -> None:
        """Fuerza las constraints diferidas; una violación sale como `ConstraintRejected` (D13)."""
        ...


class RegionRepository(Protocol):
    def transaction(self) -> AbstractContextManager[IncorporationTransaction]:
        """Serializa las incorporaciones; confirma al salir sin error y deshace ante cualquiera."""
        ...


class ReaderUnavailable(Exception):
    """La fuente de lectura no responde (p. ej. la base está caída)."""


@dataclass(frozen=True)
class RegionView:
    """Una Region con su nombre en el locale pedido (`None` si no se pidió o no existe)."""

    record: RegionRecord
    name: str | None


@dataclass(frozen=True)
class SubregionView:
    record: SubregionRecord
    name: str | None


class RegionSession(Protocol):
    """Lecturas de una sesión consistente: todas ven el mismo estado del catálogo."""

    def snapshot_version(self) -> int | None: ...

    def locale_exists(self, locale_id: str) -> bool: ...

    def regions(self, status: str | None, locale_id: str | None) -> Sequence[RegionView]: ...

    def region_by_id(self, region_id: str, locale_id: str | None) -> RegionView | None: ...

    def region_by_code(self, code: str, locale_id: str | None) -> RegionView | None: ...

    def subregions(
        self, region_id: str | None, status: str | None, locale_id: str | None
    ) -> Sequence[SubregionView]: ...

    def subregion_by_id(self, subregion_id: str, locale_id: str | None) -> SubregionView | None: ...

    def subregion_by_code(self, code: str, locale_id: str | None) -> SubregionView | None: ...


class RegionReader(Protocol):
    def session(self) -> AbstractContextManager[RegionSession]:
        """Una sesión de solo lectura; `snapshot_version` y los datos salen del mismo estado."""
        ...
