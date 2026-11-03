"""Servicio de conversión: resuelve la versión del catálogo y delega en el dominio (D6, RF-29 a 31).

Cada versión del catálogo es inmutable, así que su `ConversionCatalog` se construye una sola vez
desde `unit_snapshot.artifact` y se conserva en una caché por versión, sin invalidación. Nuevas e
históricas siguen el mismo camino: el resultado de una versión no depende de si esta es la vigente
(RNF-2, RNF-6). El servicio no escribe. Una falla técnica de la fuente de lectura sube como
`ReaderUnavailable` y no se confunde con un rechazo (RF-37); una carga fallida no se cachea.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass

from gi_common_reference.units.domain.conversion import (
    ConversionCatalog,
    ConversionRejection,
    ConversionRequest,
    ConversionSuccess,
    convert,
)
from gi_common_reference.units.domain.ports import UnitsReader, UnitsSession

INVALID_CATALOG_VERSION = "invalid_catalog_version"
CATALOG_VERSION_NOT_AVAILABLE = "catalog_version_not_available"


class CatalogCache:
    """Caché en memoria de catálogos de conversión por versión; segura entre hilos."""

    def __init__(self) -> None:
        self._items: dict[int, ConversionCatalog] = {}
        self._lock = threading.Lock()

    def get_or_load(
        self, version: int, loader: Callable[[], ConversionCatalog | None]
    ) -> ConversionCatalog | None:
        """El catálogo de `version`; `loader` se invoca solo si falta y su resultado `None` (la
        versión no existe) no se guarda."""
        with self._lock:
            cached = self._items.get(version)
            if cached is not None:
                return cached
            loaded = loader()
            if loaded is not None:
                self._items[version] = loaded
            return loaded


@dataclass(frozen=True)
class ConversionResponse:
    """`snapshot_version` es la versión vigente; la usada va en `outcome.catalog_version`."""

    snapshot_version: int | None
    outcome: ConversionSuccess | ConversionRejection


class ConversionService:
    def __init__(self, reader: UnitsReader, cache: CatalogCache | None = None) -> None:
        self._reader = reader
        self._cache = cache if cache is not None else CatalogCache()

    def convert(
        self, request: ConversionRequest, catalog_version: int | None = None
    ) -> ConversionResponse:
        """Convierte contra `catalog_version` o, sin ella, la vigente.

        La versión se resuelve antes de validar el contenido de la solicitud: con un catálogo vacío
        o una versión inexistente la respuesta es `catalog_version_not_available`.
        """
        with self._reader.session() as session:
            current = session.snapshot_version()
            if catalog_version is not None and (
                not isinstance(catalog_version, int)
                or isinstance(catalog_version, bool)
                or catalog_version < 1
            ):
                return ConversionResponse(
                    current,
                    ConversionRejection(
                        INVALID_CATALOG_VERSION, "catalog_version debe ser un entero positivo"
                    ),
                )
            version = current if catalog_version is None else catalog_version
            catalog = None
            if version is not None and current is not None and version <= current:
                catalog = self._cache.get_or_load(version, lambda: _load(session, version))
        if catalog is None:
            return ConversionResponse(
                current,
                ConversionRejection(
                    CATALOG_VERSION_NOT_AVAILABLE,
                    "la versión del catálogo no está disponible"
                    if version is not None
                    else "el catálogo está vacío",
                ),
            )
        return ConversionResponse(current, convert(catalog, request))


def _load(session: UnitsSession, version: int) -> ConversionCatalog | None:
    document = session.artifact(version)
    return None if document is None else ConversionCatalog.from_snapshot(document)
