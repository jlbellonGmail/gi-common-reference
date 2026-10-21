"""Aplicación ASGI de gi-common-reference (raíz de composición de la API de solo lectura).

Arranque: `uvicorn --factory gi_common_reference.app:app_from_environment`, con
`REFERENCE_READER_DATABASE_URL` apuntando a la base con el rol `reference_reader`.

Contrato OpenAPI: `python -m gi_common_reference.app > contracts/locales-api.v1.openapi.json`.
"""

import json
import os
from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Any

from fastapi import FastAPI

from gi_common_reference.bootstrap import postgres_reader
from gi_common_reference.locales.interfaces.http import LocaleReader, LocaleSession, create_api

READER_DATABASE_URL = "REFERENCE_READER_DATABASE_URL"


def create_app(reader: LocaleReader) -> FastAPI:
    return create_api(reader)


def app_from_environment(environ: Mapping[str, str] | None = None) -> FastAPI:
    """La API usa solo la URL de lectura: nunca la del cargador."""
    env = os.environ if environ is None else environ
    conninfo = env.get(READER_DATABASE_URL)
    if not conninfo:
        raise RuntimeError(f"falta la variable de entorno {READER_DATABASE_URL}")
    return create_app(postgres_reader(conninfo))


class _UnusedReader:
    """Para generar el OpenAPI no hace falta ninguna base."""

    def session(self) -> AbstractContextManager[LocaleSession]:
        raise RuntimeError("este lector no se usa para generar el contrato")


def openapi_document() -> dict[str, Any]:
    return create_app(_UnusedReader()).openapi()


if __name__ == "__main__":
    print(json.dumps(openapi_document(), indent=2, ensure_ascii=False))
