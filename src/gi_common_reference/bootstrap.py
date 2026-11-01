"""Raíz de composición: conecta las interfaces con los adaptadores concretos.

Vive fuera de las capas de `locales`, `regions`, `countries` y `currencies` a propósito: las
interfaces no dependen de infraestructura.

Es el único módulo, fuera de cada catálogo, autorizado a importar sus internos (puertos del dominio
y adaptadores de infraestructura), porque su función es cablearlos. Cualquier otro código externo
solo puede importar `<catálogo>.interfaces.http` (`architecture.json`). La prueba
`tests/contract/test_composition_root.py` aplica esta regla y fija qué módulos importa esta raíz.
"""

from pathlib import Path
from typing import Any

from gi_common_reference.countries.domain.policy import RequiredLocales as CountryRequiredLocales
from gi_common_reference.countries.domain.ports import CountryReader, CountryRepository, FlagStore
from gi_common_reference.countries.infrastructure.flag_store import packaged_flag_store
from gi_common_reference.countries.infrastructure.policy_reader import (
    load_required_locales as load_country_required_locales,
)
from gi_common_reference.countries.infrastructure.postgres_reader import PostgresCountryReader
from gi_common_reference.countries.infrastructure.postgres_repository import (
    PostgresCountryRepository,
)
from gi_common_reference.countries.infrastructure.snapshot_reader import (
    read_snapshot_document as read_country_snapshot_document,
)
from gi_common_reference.currencies.domain.policy import RequiredLocales as CurrencyRequiredLocales
from gi_common_reference.currencies.domain.ports import CurrencyRepository
from gi_common_reference.currencies.infrastructure.policy_reader import (
    load_required_locales as load_currency_required_locales,
)
from gi_common_reference.currencies.infrastructure.postgres_repository import (
    PostgresCurrencyRepository,
)
from gi_common_reference.currencies.infrastructure.snapshot_reader import (
    read_snapshot_document as read_currency_snapshot_document,
)
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


def postgres_country_repository(conninfo: str) -> CountryRepository:
    return PostgresCountryRepository(conninfo)


def read_country_snapshot(path: Path) -> dict[str, Any]:
    return read_country_snapshot_document(path)


def country_required_locales() -> CountryRequiredLocales:
    return load_country_required_locales()


def country_flag_store() -> FlagStore:
    return packaged_flag_store()


def postgres_country_reader(conninfo: str) -> CountryReader:
    return PostgresCountryReader(conninfo)


def postgres_currency_repository(conninfo: str) -> CurrencyRepository:
    return PostgresCurrencyRepository(conninfo)


def read_currency_snapshot(path: Path) -> dict[str, Any]:
    return read_currency_snapshot_document(path)


def currency_required_locales() -> CurrencyRequiredLocales:
    return load_currency_required_locales()
