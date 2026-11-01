"""Almacén de banderas sobre un directorio de assets (RF-50, D11).

En producción el directorio es el recurso empaquetado `countries/assets/flags`; en pruebas, uno
temporal. Solo lee archivos `.svg` por ruta relativa segura y nunca sale de su raíz.
"""

from importlib import resources
from importlib.resources.abc import Traversable

from gi_common_reference.countries.domain.svg import is_safe_asset_path

ASSETS_PACKAGE = "gi_common_reference.countries.assets"
FLAGS_DIRECTORY = "flags"


class DirectoryFlagStore:
    def __init__(self, root: Traversable) -> None:
        self._root = root

    def read(self, asset_path: str) -> bytes | None:
        """Los bytes exactos del archivo, o `None` si la ruta no es segura o no existe."""
        if not is_safe_asset_path(asset_path):
            return None
        node = self._root.joinpath(*asset_path.split("/"))
        try:
            return node.read_bytes() if node.is_file() else None
        except OSError:
            return None


def packaged_flag_store() -> DirectoryFlagStore:
    return DirectoryFlagStore(resources.files(ASSETS_PACKAGE).joinpath(FLAGS_DIRECTORY))
