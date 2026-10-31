"""Puertos del dominio de Countries: incorporación, consultas y banderas."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from gi_common_reference.countries.domain.policy import RequiredLocales


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
