"""API pública de solo lectura `/v1/countries` (D13). Es el único contrato público del módulo
`countries`.

Todas las respuestas llevan `snapshot_version`, la versión vigente del catálogo Countries (RF-16):
`{snapshot_version, data}` si hay resultado o `{snapshot_version, error}` si no. Con el catálogo
vacío es `null`. Los errores llevan códigos estables sin traducir (RNF-9, D-19). El contrato OpenAPI
propio se sirve en `/v1/openapi/countries.json`.
"""

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gi_common_reference.countries.application.queries import (
    STATUS_FILTERS,
    FlagStatus,
    Listing,
    Lookup,
    LookupStatus,
    get_country_by_code,
    get_country_by_id,
    get_flag,
    list_countries,
)
from gi_common_reference.countries.domain.model import CodeKind
from gi_common_reference.countries.domain.ports import (
    CountryReader,
    CountrySession,
    CountryView,
    FlagStore,
    ReaderUnavailable,
)

# Superficie pública del módulo (`architecture.json`). Los puertos se reexportan para que la
# composición (`app.py`) dependa solo de este módulo y no de los internos de `countries`.
__all__ = [
    "OPENAPI_URL",
    "CountryReader",
    "CountrySession",
    "FlagStore",
    "create_api",
]

OPENAPI_URL = "/v1/openapi/countries.json"
SVG = "image/svg+xml"
logger = logging.getLogger(__name__)

LocaleQuery = Annotated[
    str | None,
    Query(
        description=(
            "Devuelve `name` y `official_name` en este locale (UUID del catálogo de Locale). Sin "
            "traducción son `null`: no hay fallback a otro locale."
        )
    ),
]


class Country(BaseModel):
    """País o área ISO 3166-1. La identidad es `country_id`; los códigos son claves de resolución.

    Sin ningún texto propio (los nombres son de `CountryLocale`) ni códigos de región (RF-34, RF-6).
    """

    country_id: str = Field(description="Identidad estable del país (UUID de Reference).")
    alpha2: str = Field(description="ISO 3166-1 alpha-2 vigente (`NA` es Namibia).")
    alpha3: str = Field(description="ISO 3166-1 alpha-3 vigente.")
    numeric_code: str = Field(description="ISO 3166-1 numérico vigente, con ceros (`004`).")
    status: Literal["active", "inactive"] = Field(
        description="`active`: apto para nuevas referencias; `inactive`: sigue resoluble."
    )
    replacement_country_ids: list[str] = Field(
        description=(
            "Países sucesores (0..N), en orden ascendente de `country_id`; vacío si no hay "
            "sucesión declarada o si el país es `active`."
        )
    )
    region_id: str | None = Field(description="Region de Region/Subregion, o `null`.")
    subregion_id: str | None = Field(description="Subregion de Region/Subregion, o `null`.")
    calling_code: str | None = Field(description="Código de país E.164 sin `+`, o `null`.")
    name: str | None = Field(description="Nombre en el `locale_id` pedido, o `null`.")
    official_name: str | None = Field(description="Nombre formal en el `locale_id`, o `null`.")


class CountryEnvelope(BaseModel):
    snapshot_version: int = Field(description="Snapshot vigente del catálogo Countries.")
    data: Country


class CountryListEnvelope(BaseModel):
    snapshot_version: int | None = Field(
        description="Snapshot vigente; `null` si todavía no se incorporó ninguno."
    )
    data: list[Country]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    snapshot_version: int | None = Field(description="Snapshot vigente, o `null` si no hay.")
    error: ErrorBody


NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "No encontrado."}
}
INVALID: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorEnvelope, "description": "Parámetro inválido (distinto de 404)."}
}
# Si un consumidor navega a la URL, el SVG no debe ejecutar ni cargar nada (defensa en profundidad).
FLAG_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
}
FLAG_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "El asset SVG de la bandera; `ETag` es su suma de verificación.",
        "content": {SVG: {"schema": {"type": "string", "format": "binary"}}},
        "headers": {
            "ETag": {"schema": {"type": "string"}, "description": '`"sha256:…"`'},
            "X-Content-Type-Options": {"schema": {"type": "string"}, "description": "`nosniff`"},
            "Content-Security-Policy": {
                "schema": {"type": "string"},
                "description": "Sin recursos externos ni scripts: el SVG se trata como datos.",
            },
        },
    },
    404: {
        "model": ErrorEnvelope,
        "description": "`country_not_found`, o `flag_not_declared` si el país no tiene bandera.",
    },
    500: {"model": ErrorEnvelope, "description": "`flag_integrity_error`: el asset no coincide."},
}


def _country(view: CountryView) -> dict[str, Any]:
    record = view.record
    return {
        "country_id": record.country_id,
        "alpha2": record.alpha2,
        "alpha3": record.alpha3,
        "numeric_code": record.numeric_code,
        "status": record.status,
        "replacement_country_ids": list(record.replacement_country_ids),
        "region_id": record.region_id,
        "subregion_id": record.subregion_id,
        "calling_code": record.calling_code,
        "name": view.name,
        "official_name": view.official_name,
    }


def _error(status: int, snapshot_version: int | None, code: str, message: str) -> JSONResponse:
    body = {"snapshot_version": snapshot_version, "error": {"code": code, "message": message}}
    return JSONResponse(status_code=status, content=body)


def _lookup(result: Lookup[CountryView]) -> Any:
    if result.status is LookupStatus.FOUND and result.item is not None:
        return {"snapshot_version": result.snapshot_version, "data": _country(result.item)}
    if result.status is LookupStatus.INVALID:
        return _error(422, result.snapshot_version, result.error, result.detail)
    return _error(404, result.snapshot_version, result.error, result.detail)


def _listing(result: Listing[CountryView]) -> Any:
    if result.status is LookupStatus.INVALID:
        return _error(422, result.snapshot_version, result.error, result.detail)
    return {
        "snapshot_version": result.snapshot_version,
        "data": [_country(item) for item in result.items],
    }


def create_api(reader: CountryReader, flags: FlagStore) -> FastAPI:
    app = FastAPI(
        title="gi-common-reference: countries",
        version="1.0.0",
        description=(
            "Catálogo global de países ISO 3166-1, versionado y de solo lectura: identidad "
            "`country_id`, códigos de resolución, clasificación por `region_id`/`subregion_id`, "
            "nombres por `locale_id` y bandera SVG."
        ),
        docs_url=None,
        redoc_url=None,
        openapi_url=OPENAPI_URL,
        redirect_slashes=False,
    )
    router = APIRouter(prefix="/v1/countries", tags=["countries"])

    def by_code(kind: CodeKind, code: str, locale_id: str | None) -> Any:
        return _lookup(get_country_by_code(reader, kind, code, locale_id))

    # Las rutas `by-*` se declaran antes que `{country_id}`: gana la más específica.
    @router.get(
        "/by-alpha2/{code}",
        operation_id="getCountryByAlpha2",
        summary="Obtener un país por su código ISO alpha-2 vigente",
        response_model=CountryEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def country_by_alpha2(code: str, locale_id: LocaleQuery = None) -> Any:
        """Sin distinguir mayúsculas. El `active` que lo posee; si ninguno, el `inactive` que lo
        obtuvo más recientemente. Un código mal formado es 422; uno histórico, 404."""
        return by_code("alpha2", code, locale_id)

    @router.get(
        "/by-alpha3/{code}",
        operation_id="getCountryByAlpha3",
        summary="Obtener un país por su código ISO alpha-3 vigente",
        response_model=CountryEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def country_by_alpha3(code: str, locale_id: LocaleQuery = None) -> Any:
        return by_code("alpha3", code, locale_id)

    @router.get(
        "/by-numeric/{code}",
        operation_id="getCountryByNumeric",
        summary="Obtener un país por su código ISO numérico vigente",
        response_model=CountryEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def country_by_numeric(code: str, locale_id: LocaleQuery = None) -> Any:
        """Texto exacto de 3 dígitos (`004`); `4` es 422."""
        return by_code("numeric_code", code, locale_id)

    @router.get(
        "/{country_id}/flag",
        operation_id="getCountryFlag",
        summary="Obtener la bandera SVG de un país",
        response_class=Response,
        responses=FLAG_RESPONSES,
    )
    def country_flag(country_id: str) -> Any:
        result = get_flag(reader, flags, country_id)
        version = result.snapshot_version
        if result.status is FlagStatus.FOUND and result.content is not None:
            return Response(
                content=result.content,
                media_type=SVG,
                headers={"ETag": f'"{result.sha256}"', **FLAG_SECURITY_HEADERS},
            )
        if result.status is FlagStatus.COUNTRY_NOT_FOUND:
            return _error(404, version, "country_not_found", "no encontrado")
        if result.status is FlagStatus.NOT_DECLARED:
            return _error(404, version, "flag_not_declared", "el país no tiene bandera declarada")
        return _error(500, version, "flag_integrity_error", "el asset de la bandera no es íntegro")

    @router.get(
        "/{country_id}",
        operation_id="getCountryById",
        summary="Obtener un país por su country_id, cualquiera sea su status",
        response_model=CountryEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def country_by_id(country_id: str, locale_id: LocaleQuery = None) -> Any:
        """Un `country_id` mal formado es "no encontrado" (404), no un error de validación."""
        return _lookup(get_country_by_id(reader, country_id, locale_id))

    @router.get(
        "",
        operation_id="listCountries",
        summary="Listar los países, ordenados por alpha2",
        response_model=CountryListEnvelope,
        responses=INVALID,
    )
    def country_listing(
        status: Annotated[
            str | None,
            Query(
                description="`active` (por defecto), `inactive` o `all` para incluir ambos.",
            ),
        ] = None,
        region_id: Annotated[
            str | None, Query(description="Restringe el resultado a una Region.")
        ] = None,
        subregion_id: Annotated[
            str | None, Query(description="Restringe el resultado a una Subregion.")
        ] = None,
        locale_id: LocaleQuery = None,
    ) -> Any:
        return _listing(list_countries(reader, status, region_id, subregion_id, locale_id))

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
        for name in ("HTTPValidationError", "ValidationError"):
            schema["components"]["schemas"].pop(name, None)
        for parameter in schema["paths"]["/v1/countries"]["get"]["parameters"]:
            if parameter["name"] == "status":
                parameter["schema"] = {
                    "type": "string",
                    "enum": list(STATUS_FILTERS),
                    "default": "active",
                }
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
