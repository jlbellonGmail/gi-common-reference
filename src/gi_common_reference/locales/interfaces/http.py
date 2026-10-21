"""API pública de solo lectura `/v1/locales` (D1). Es el único contrato público del módulo.

Todas las respuestas de los tres endpoints llevan `snapshot_version` (RF-13): `{snapshot_version,
data}` si hay resultado o `{snapshot_version, error}` si no. Con el catálogo vacío es `null`.
"""

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gi_common_reference.locales.application.queries import (
    STATUSES,
    LocaleLookup,
    LookupStatus,
    get_locale_by_code,
    get_locale_by_id,
    list_locales,
)
from gi_common_reference.locales.domain.model import LocaleRecord
from gi_common_reference.locales.domain.ports import LocaleReader, LocaleSession, ReaderUnavailable

# Superficie pública del módulo (`architecture.json`). Los puertos se reexportan para que la raíz de
# composición (`app.py`) dependa solo de este módulo y no de los internos de `locales`.
__all__ = ["LocaleReader", "LocaleSession", "create_api"]

logger = logging.getLogger(__name__)


class Locale(BaseModel):
    """Un idioma publicado. No contiene textos traducibles (RF-6)."""

    locale_id: str = Field(description="Identidad estable del locale (UUID asignado por PREP).")
    code: str = Field(description="Código publicado: subtag de idioma BCP 47 en minúsculas.")
    status: Literal["active", "inactive"] = Field(
        description="`active`: apto para nuevas referencias; `inactive`: sigue resoluble."
    )
    iana_deprecated: bool = Field(
        description="El registro IANA de referencia declara el código como deprecado."
    )
    replacement_locale_id: str | None = Field(
        description="Locale del Preferred-Value del registro IANA; solo si está deprecado."
    )


class LocaleEnvelope(BaseModel):
    snapshot_version: int = Field(description="Snapshot vigente del catálogo de locales.")
    data: Locale


class LocaleListEnvelope(BaseModel):
    snapshot_version: int | None = Field(
        description="Snapshot vigente; `null` si todavía no se incorporó ninguno."
    )
    data: list[Locale]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    snapshot_version: int | None = Field(description="Snapshot vigente, o `null` si no hay.")
    error: ErrorBody


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "No encontrado, sin fallback a otro locale."},
    422: {"model": ErrorEnvelope, "description": "Parámetro inválido."},
}


def _locale(record: LocaleRecord) -> dict[str, Any]:
    return {
        "locale_id": record.locale_id,
        "code": record.code,
        "status": record.status,
        "iana_deprecated": record.iana_deprecated,
        "replacement_locale_id": record.replacement_locale_id,
    }


def _error(status: int, snapshot_version: int | None, code: str, message: str) -> JSONResponse:
    body = {"snapshot_version": snapshot_version, "error": {"code": code, "message": message}}
    return JSONResponse(status_code=status, content=body)


def _lookup_response(result: LocaleLookup, invalid_code: str) -> Any:
    if result.status is LookupStatus.FOUND and result.locale is not None:
        return {"snapshot_version": result.snapshot_version, "data": _locale(result.locale)}
    if result.status is LookupStatus.INVALID:
        return _error(422, result.snapshot_version, invalid_code, result.detail)
    return _error(404, result.snapshot_version, "not_found", result.detail)


def create_api(reader: LocaleReader) -> FastAPI:
    app = FastAPI(
        title="gi-common-reference: locales",
        version="1.0.0",
        description="Catálogo global de locales (idiomas), versionado y de solo lectura.",
        docs_url=None,
        redoc_url=None,
        openapi_url="/v1/openapi.json",
        redirect_slashes=False,
    )
    router = APIRouter(prefix="/v1/locales", tags=["locales"])

    @router.get(
        "/by-code/{code}",
        operation_id="getLocaleByCode",
        summary="Obtener un locale por su código",
        response_model=LocaleEnvelope,
        responses=ERROR_RESPONSES,
    )
    def by_code(code: str) -> Any:
        """Tolera mayúsculas. Si el código no se publicó pero el registro IANA declara su
        Preferred-Value, devuelve el locale de ese valor. No recorta espacios ni acepta
        separadores: lo que no es un subtag de idioma bien formado es 422."""
        return _lookup_response(get_locale_by_code(reader, code), "invalid_code")

    @router.get(
        "/{locale_id}",
        operation_id="getLocaleById",
        summary="Obtener un locale por su locale_id",
        response_model=LocaleEnvelope,
        responses={404: ERROR_RESPONSES[404]},
    )
    def by_id(locale_id: str) -> Any:
        return _lookup_response(get_locale_by_id(reader, locale_id), "invalid_locale_id")

    @router.get(
        "",
        operation_id="listLocales",
        summary="Listar los locales publicados, ordenados por código",
        response_model=LocaleListEnvelope,
        responses={422: ERROR_RESPONSES[422]},
    )
    def listing(
        status: Annotated[
            str | None,
            Query(
                description="Restringe el resultado a un `status`.",
                json_schema_extra={"enum": list(STATUSES)},
            ),
        ] = None,
    ) -> Any:
        result = list_locales(reader, status)
        if result.status is LookupStatus.INVALID:
            return _error(422, result.snapshot_version, "invalid_status", result.detail)
        return {
            "snapshot_version": result.snapshot_version,
            "data": [_locale(record) for record in result.locales],
        }

    app.include_router(router)

    def openapi() -> dict[str, Any]:
        """El contrato publicado declara solo lo que la API devuelve de verdad."""
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            description=app.description,
            routes=app.routes,
        )
        # Un locale_id mal formado es 404 (no puede existir): FastAPI agregaría un 422 por defecto.
        schema["paths"]["/v1/locales/{locale_id}"]["get"]["responses"].pop("422", None)
        for name in ("HTTPValidationError", "ValidationError"):
            schema["components"]["schemas"].pop(name, None)
        listing_params = schema["paths"]["/v1/locales"]["get"]["parameters"]
        for parameter in listing_params:
            if parameter["name"] == "status":
                parameter["schema"] = {"type": "string", "enum": list(STATUSES)}
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]

    # La causa se registra en el log; al cliente solo llega un mensaje genérico. No se registra la
    # query string ni la cadena de conexión.
    @app.exception_handler(ReaderUnavailable)
    async def unavailable(request: Request, error: ReaderUnavailable) -> JSONResponse:
        logger.error("catálogo no disponible en %s %s: %s", request.method, request.url.path, error)
        return _error(503, None, "unavailable", "el catálogo no está disponible")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        logger.error("error interno en %s %s", request.method, request.url.path, exc_info=error)
        return _error(500, None, "internal_error", "error interno")

    return app
