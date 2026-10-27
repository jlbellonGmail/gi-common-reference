"""Raíz de composición: conecta las interfaces con los adaptadores concretos.

Vive fuera de las capas de `locales` y `regions` a propósito: las interfaces no dependen de
infraestructura.

Es el único módulo, fuera de cada catálogo, autorizado a importar sus internos (puertos del dominio
y adaptadores de infraestructura), porque su función es cablearlos. Cualquier otro código externo
solo puede importar `<catálogo>.interfaces.http` (`architecture.json`). La prueba
`tests/contract/test_composition_root.py` aplica esta regla y fija qué módulos importa esta raíz.
"""

from pathlib import Path
from typing import Any

from gi_common_reference.locales.domain.ports import LocaleReader, LocaleRepository
from gi_common_reference.locales.infrastructure.postgres_reader import PostgresLocaleReader
from gi_common_reference.locales.infrastructure.postgres_repository import (
    PostgresLocaleRepository,
)
from gi_common_reference.locales.infrastructure.snapshot_reader import read_snapshot_document
from gi_common_reference.regions.domain.policy import RequiredLocales
from gi_common_reference.regions.domain.ports import RegionReader, RegionRepository
from gi_common_reference.regions.infrastructure.policy_reader import load_required_locales
from gi_common_reference.regions.infrastructure.postgres_reader import PostgresRegionReader
from gi_common_reference.regions.infrastructure.postgres_repository import (
    PostgresRegionRepository,
)
from gi_common_reference.regions.infrastructure.snapshot_reader import (
    read_snapshot_document as read_region_snapshot_document,
)


def postgres_repository(conninfo: str) -> LocaleRepository:
    return PostgresLocaleRepository(conninfo)


def read_snapshot(path: Path) -> dict[str, Any]:
    return read_snapshot_document(path)


def postgres_reader(conninfo: str) -> LocaleReader:
    return PostgresLocaleReader(conninfo)


def postgres_region_repository(conninfo: str) -> RegionRepository:
    return PostgresRegionRepository(conninfo)


def read_region_snapshot(path: Path) -> dict[str, Any]:
    return read_region_snapshot_document(path)


def required_locales() -> RequiredLocales:
    return load_required_locales()


def postgres_region_reader(conninfo: str) -> RegionReader:
    return PostgresRegionReader(conninfo)
