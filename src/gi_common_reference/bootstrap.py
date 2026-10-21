"""Raíz de composición: conecta las interfaces con los adaptadores concretos.

Vive fuera de las capas de `locales` a propósito: las interfaces no dependen de infraestructura.

Es el único módulo, fuera de `locales`, autorizado a importar sus internos (puertos del dominio y
adaptadores de infraestructura), porque su función es cablearlos. Cualquier otro código externo solo
puede importar `locales.interfaces.http` (`architecture.json`). La prueba
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


def postgres_repository(conninfo: str) -> LocaleRepository:
    return PostgresLocaleRepository(conninfo)


def read_snapshot(path: Path) -> dict[str, Any]:
    return read_snapshot_document(path)


def postgres_reader(conninfo: str) -> LocaleReader:
    return PostgresLocaleReader(conninfo)
