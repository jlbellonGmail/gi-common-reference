"""Puertos del dominio de Units: incorporación y verificación (D12, D13) y lectura (T7)."""

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from gi_common_reference.units.domain.errors import SnapshotFormatError
from gi_common_reference.units.domain.model import (
    AssociationRecord,
    CatalogState,
    KindNameRecord,
    LocaleCatalog,
    QuantityKindRecord,
    UcumTable,
    UnitNameRecord,
    UnitRecord,
)
from gi_common_reference.units.domain.policy import RequiredLocales
from gi_common_reference.units.domain.snapshot import HistoricalSnapshot

__all__ = [
    "CatalogView",
    "IncorporationTransaction",
    "PolicyLoader",
    "SnapshotFormatError",
    "SnapshotReader",
    "UcumLoader",
    "UnitsRepository",
]

SnapshotReader = Callable[[Path], dict[str, Any]]
"""Lee un archivo local de snapshot y devuelve su documento ya validado contra el schema."""

PolicyLoader = Callable[[], RequiredLocales]
"""Carga el conjunto obligatorio de locales versionado en el repositorio (RF-18)."""

UcumLoader = Callable[[], UcumTable]
"""Carga la tabla UCUM empaquetada, verificada contra su sha256 (D8)."""


class CatalogView(Protocol):
    """Lo que hace falta leer para validar un snapshot contra el catálogo vigente."""

    def history(self) -> Sequence[HistoricalSnapshot]: ...

    def current_state(self) -> CatalogState: ...

    def locale_catalog(self) -> LocaleCatalog: ...


class IncorporationTransaction(CatalogView, Protocol):
    """Una transacción de incorporación. Las escrituras se llaman en el orden del plan (paso 11)."""

    def insert_snapshot(
        self,
        document: Mapping[str, Any],
        locale_snapshot_version: int,
        policy_version: int,
        ucum_table_version: str,
    ) -> None:
        """Guarda el documento completo como artefacto inmutable de la versión (D6, D12)."""
        ...

    def insert_units(self, units: Sequence[UnitRecord], version: int) -> None: ...

    def update_units(self, units: Sequence[UnitRecord], version: int) -> None: ...

    def insert_quantity_kinds(self, kinds: Sequence[QuantityKindRecord], version: int) -> None: ...

    def update_quantity_kinds(self, kinds: Sequence[QuantityKindRecord], version: int) -> None: ...

    def insert_associations(
        self, associations: Sequence[AssociationRecord], version: int
    ) -> None: ...

    def update_associations(
        self, associations: Sequence[AssociationRecord], version: int
    ) -> None: ...

    def insert_kind_names(self, names: Sequence[KindNameRecord]) -> None: ...

    def update_kind_names(self, names: Sequence[KindNameRecord]) -> None: ...

    def insert_unit_names(self, names: Sequence[UnitNameRecord]) -> None: ...

    def update_unit_names(self, names: Sequence[UnitNameRecord]) -> None: ...

    def touch_units(self, unit_ids: Sequence[str], version: int) -> None:
        """Marca el snapshot como el último que cambió el contenido de estas unidades."""
        ...

    def touch_quantity_kinds(self, kind_ids: Sequence[str], version: int) -> None:
        """Marca el snapshot como el último que cambió el contenido de estas magnitudes."""
        ...

    def check_constraints(self) -> None:
        """Fuerza las constraints diferidas; una violación sale como `ConstraintRejected`."""
        ...


class UnitsRepository(Protocol):
    def transaction(self) -> AbstractContextManager[IncorporationTransaction]:
        """Serializa las incorporaciones; confirma al salir sin error y deshace ante cualquiera."""
        ...

    def inspect(self) -> AbstractContextManager[CatalogView]:
        """Una vista de solo lectura del catálogo: no toma el lock exclusivo ni escribe."""
        ...
