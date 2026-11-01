"""Aplicación ASGI de gi-common-reference (raíz de composición de la API de solo lectura).

Arranque: `uvicorn --factory gi_common_reference.app:app_from_environment`, con
`REFERENCE_READER_DATABASE_URL` apuntando a la base con el rol `reference_reader`.

La aplicación compone tres APIs con contratos propios (D5 de 002, D14 de 003): `/v1/countries*` y
`/v1/openapi/countries.json` van a la de Countries; `/v1/regions*`, `/v1/subregions*` y
`/v1/openapi/regions.json`, a la de Regions; todo lo demás, a la de Locale, sin cambios (su contrato
sigue en `/v1/openapi.json`).

Contratos OpenAPI: `python -m gi_common_reference.app > contracts/locales-api.v1.openapi.json`,
`python -m gi_common_reference.app regions > contracts/regions-api.v1.openapi.json` y
`python -m gi_common_reference.app countries > contracts/countries-api.v1.openapi.json`.
"""

import json
import os
import sys
from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Any

from fastapi import FastAPI
from starlette.types import Receive, Scope, Send

from gi_common_reference.bootstrap import (
    country_flag_store,
    postgres_country_reader,
    postgres_reader,
    postgres_region_reader,
)
from gi_common_reference.countries.interfaces.http import (
    OPENAPI_URL as COUNTRIES_OPENAPI_URL,
)
from gi_common_reference.countries.interfaces.http import (
    CountryReader,
    CountrySession,
    FlagStore,
)
from gi_common_reference.countries.interfaces.http import (
    create_api as create_countries_api,
)
from gi_common_reference.locales.interfaces.http import LocaleReader, LocaleSession, create_api
from gi_common_reference.regions.interfaces.http import (
    OPENAPI_URL as REGIONS_OPENAPI_URL,
)
from gi_common_reference.regions.interfaces.http import (
    RegionReader,
    RegionSession,
)
from gi_common_reference.regions.interfaces.http import (
    create_api as create_regions_api,
)

READER_DATABASE_URL = "REFERENCE_READER_DATABASE_URL"
REGIONS_PREFIXES = ("/v1/regions", "/v1/subregions")
COUNTRIES_PREFIXES = ("/v1/countries",)


def create_app(reader: LocaleReader) -> FastAPI:
    return create_api(reader)


class CatalogApp:
    """Despacha cada request por su path a la API de Countries, a la de Regions o a la de Locale.

    El ciclo de vida (`lifespan`) va a la de Locale: ninguna de las tres registra eventos de
    arranque ni de cierre.
    """

    def __init__(self, locales: FastAPI, regions: FastAPI, countries: FastAPI) -> None:
        self.locales, self.regions, self.countries = locales, regions, countries

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and belongs_to_countries(scope["path"]):
            await self.countries(scope, receive, send)
        elif scope["type"] in ("http", "websocket") and belongs_to_regions(scope["path"]):
            await self.regions(scope, receive, send)
        else:
            await self.locales(scope, receive, send)


def _under(path: str, openapi_url: str, prefixes: tuple[str, ...]) -> bool:
    if path == openapi_url:
        return True
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)


def belongs_to_regions(path: str) -> bool:
    return _under(path, REGIONS_OPENAPI_URL, REGIONS_PREFIXES)


def belongs_to_countries(path: str) -> bool:
    return _under(path, COUNTRIES_OPENAPI_URL, COUNTRIES_PREFIXES)


def create_catalog_app(
    locale_reader: LocaleReader,
    region_reader: RegionReader,
    country_reader: CountryReader,
    flag_store: FlagStore,
) -> CatalogApp:
    return CatalogApp(
        create_app(locale_reader),
        create_regions_api(region_reader),
        create_countries_api(country_reader, flag_store),
    )


def app_from_environment(environ: Mapping[str, str] | None = None) -> CatalogApp:
    """La API usa solo la URL de lectura: nunca la del cargador."""
    env = os.environ if environ is None else environ
    conninfo = env.get(READER_DATABASE_URL)
    if not conninfo:
        raise RuntimeError(f"falta la variable de entorno {READER_DATABASE_URL}")
    return create_catalog_app(
        postgres_reader(conninfo),
        postgres_region_reader(conninfo),
        postgres_country_reader(conninfo),
        country_flag_store(),
    )


def openapi_document() -> dict[str, Any]:
    reader: LocaleReader = _UnusedLocaleReader()
    return create_app(reader).openapi()


def regions_openapi_document() -> dict[str, Any]:
    reader: RegionReader = _UnusedRegionReader()
    return create_regions_api(reader).openapi()


def countries_openapi_document() -> dict[str, Any]:
    reader: CountryReader = _UnusedCountryReader()
    return create_countries_api(reader, country_flag_store()).openapi()


class _UnusedLocaleReader:
    """Para generar el OpenAPI no hace falta ninguna base."""

    def session(self) -> AbstractContextManager[LocaleSession]:
        raise RuntimeError("este lector no se usa para generar el contrato")


class _UnusedRegionReader:
    def session(self) -> AbstractContextManager[RegionSession]:
        raise RuntimeError("este lector no se usa para generar el contrato")


class _UnusedCountryReader:
    def session(self) -> AbstractContextManager[CountrySession]:
        raise RuntimeError("este lector no se usa para generar el contrato")


if __name__ == "__main__":
    documents = {
        "regions": regions_openapi_document,
        "countries": countries_openapi_document,
    }
    selected = documents.get(sys.argv[1] if sys.argv[1:] else "", openapi_document)
    print(json.dumps(selected(), indent=2, ensure_ascii=False))
