"""Aplicación ASGI de gi-common-reference (raíz de composición de la API de solo lectura).

Arranque: `uvicorn --factory gi_common_reference.app:app_from_environment`, con
`REFERENCE_READER_DATABASE_URL` apuntando a la base con el rol `reference_reader`.

La aplicación compone dos APIs con contratos propios (D5 de 002): `/v1/regions*`,
`/v1/subregions*` y `/v1/openapi/regions.json` van a la de Regions; todo lo demás, a la de Locale,
sin cambios (su contrato sigue en `/v1/openapi.json`).

Contratos OpenAPI: `python -m gi_common_reference.app > contracts/locales-api.v1.openapi.json` y
`python -m gi_common_reference.app regions > contracts/regions-api.v1.openapi.json`.
"""

import json
import os
import sys
from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Any

from fastapi import FastAPI
from starlette.types import Receive, Scope, Send

from gi_common_reference.bootstrap import postgres_reader, postgres_region_reader
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


def create_app(reader: LocaleReader) -> FastAPI:
    return create_api(reader)


class CatalogApp:
    """Despacha cada request por su path a la API de Regions o a la de Locale (D5).

    El ciclo de vida (`lifespan`) va a la de Locale: ninguna de las dos registra eventos de
    arranque ni de cierre.
    """

    def __init__(self, locales: FastAPI, regions: FastAPI) -> None:
        self.locales, self.regions = locales, regions

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and belongs_to_regions(scope["path"]):
            await self.regions(scope, receive, send)
        else:
            await self.locales(scope, receive, send)


def belongs_to_regions(path: str) -> bool:
    if path == REGIONS_OPENAPI_URL:
        return True
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in REGIONS_PREFIXES)


def create_catalog_app(locale_reader: LocaleReader, region_reader: RegionReader) -> CatalogApp:
    return CatalogApp(create_app(locale_reader), create_regions_api(region_reader))


def app_from_environment(environ: Mapping[str, str] | None = None) -> CatalogApp:
    """La API usa solo la URL de lectura: nunca la del cargador."""
    env = os.environ if environ is None else environ
    conninfo = env.get(READER_DATABASE_URL)
    if not conninfo:
        raise RuntimeError(f"falta la variable de entorno {READER_DATABASE_URL}")
    return create_catalog_app(postgres_reader(conninfo), postgres_region_reader(conninfo))


def openapi_document() -> dict[str, Any]:
    reader: LocaleReader = _UnusedLocaleReader()
    return create_app(reader).openapi()


def regions_openapi_document() -> dict[str, Any]:
    reader: RegionReader = _UnusedRegionReader()
    return create_regions_api(reader).openapi()


class _UnusedLocaleReader:
    """Para generar el OpenAPI no hace falta ninguna base."""

    def session(self) -> AbstractContextManager[LocaleSession]:
        raise RuntimeError("este lector no se usa para generar el contrato")


class _UnusedRegionReader:
    def session(self) -> AbstractContextManager[RegionSession]:
        raise RuntimeError("este lector no se usa para generar el contrato")


if __name__ == "__main__":
    document = regions_openapi_document() if sys.argv[1:] == ["regions"] else openapi_document()
    print(json.dumps(document, indent=2, ensure_ascii=False))
