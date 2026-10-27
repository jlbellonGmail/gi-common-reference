"""API pública de solo lectura `/v1/regions` y `/v1/subregions` (D4). Es el único contrato público
del módulo `regions`.

Todas las respuestas llevan `snapshot_version`, la versión vigente del catálogo Region/Subregion
(RF-20, RF-37): `{snapshot_version, data}` si hay resultado o `{snapshot_version, error}` si no. Con
el catálogo vacío es `null`. El contrato OpenAPI propio se sirve en `/v1/openapi/regions.json`.
"""

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gi_common_reference.regions.application.queries import (
    Listing,
    Lookup,
    LookupStatus,
    get_region_by_code,
    get_region_by_id,
    get_subregion_by_code,
    get_subregion_by_id,
    list_regions,
    list_subregions,
)
from gi_common_reference.regions.domain.model import STATUSES
from gi_common_reference.regions.domain.ports import (
    ReaderUnavailable,
    RegionReader,
    RegionSession,
    RegionView,
    SubregionView,
)

# Superficie pública del módulo (`architecture.json`). Los puertos se reexportan para que la
# composición (`app.py`) dependa solo de este módulo y no de los internos de `regions`.
__all__ = ["OPENAPI_URL", "RegionReader", "RegionSession", "create_api"]

OPENAPI_URL = "/v1/openapi/regions.json"
logger = logging.getLogger(__name__)

LocaleQuery = Annotated[
    str | None,
    Query(
        description=(
            "Devuelve el nombre en este locale (UUID del catálogo de Locale). Sin traducción, "
            "`name` es `null`: no hay fallback a otro locale."
        )
    ),
]
StatusQuery = Annotated[
    str | None,
    Query(
        description="Restringe el resultado a un `status`.",
        json_schema_extra={"enum": list(STATUSES)},
    ),
]


class Region(BaseModel):
    """Región UN M49 (nivel superior, p. ej. 019 Americas). Sin textos propios (RF-8)."""

    region_id: str = Field(description="Identidad estable de la Region (UUID asignado por PREP).")
    code: str | None = Field(description="Código UN M49 vigente de 3 dígitos, o `null`.")
    status: Literal["active", "inactive"] = Field(
        description="`active`: apta para nuevas referencias; `inactive`: sigue resoluble."
    )
    replacement_region_id: str | None = Field(
        description="Region sucesora según la fuente de autoridad; solo si es `inactive`."
    )
    name: str | None = Field(description="Nombre en el `locale_id` pedido, o `null`.")


class Subregion(BaseModel):
    """Subregión UN M49, contenida en exactamente una Region (p. ej. 419 en 019)."""

    subregion_id: str = Field(description="Identidad estable de la Subregion (UUID de PREP).")
    region_id: str = Field(description="Region que la contiene.")
    code: str | None = Field(description="Código UN M49 vigente de 3 dígitos, o `null`.")
    status: Literal["active", "inactive"] = Field(
        description="`active`: apta para nuevas referencias; `inactive`: sigue resoluble."
    )
    replacement_subregion_id: str | None = Field(
        description="Subregion sucesora según la fuente de autoridad; solo si es `inactive`."
    )
    name: str | None = Field(description="Nombre en el `locale_id` pedido, o `null`.")


class RegionEnvelope(BaseModel):
    snapshot_version: int = Field(description="Snapshot vigente del catálogo Region/Subregion.")
    data: Region


class RegionListEnvelope(BaseModel):
    snapshot_version: int | None = Field(
        description="Snapshot vigente; `null` si todavía no se incorporó ninguno."
    )
    data: list[Region]


class SubregionEnvelope(BaseModel):
    snapshot_version: int = Field(description="Snapshot vigente del catálogo Region/Subregion.")
    data: Subregion


class SubregionListEnvelope(BaseModel):
    snapshot_version: int | None = Field(
        description="Snapshot vigente; `null` si todavía no se incorporó ninguno."
    )
    data: list[Subregion]


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


def _region(view: RegionView) -> dict[str, Any]:
    record = view.record
    return {
        "region_id": record.region_id,
        "code": record.code,
        "status": record.status,
        "replacement_region_id": record.replacement_region_id,
        "name": view.name,
    }


def _subregion(view: SubregionView) -> dict[str, Any]:
    record = view.record
    return {
        "subregion_id": record.subregion_id,
        "region_id": record.region_id,
        "code": record.code,
        "status": record.status,
        "replacement_subregion_id": record.replacement_subregion_id,
        "name": view.name,
    }


def _error(status: int, snapshot_version: int | None, code: str, message: str) -> JSONResponse:
    body = {"snapshot_version": snapshot_version, "error": {"code": code, "message": message}}
    return JSONResponse(status_code=status, content=body)


def _lookup(result: Lookup[Any], render: Any) -> Any:
    if result.status is LookupStatus.FOUND and result.item is not None:
        return {"snapshot_version": result.snapshot_version, "data": render(result.item)}
    if result.status is LookupStatus.INVALID:
        return _error(422, result.snapshot_version, result.error, result.detail)
    return _error(404, result.snapshot_version, result.error, result.detail)


def _listing(result: Listing[Any], render: Any) -> Any:
    if result.status is LookupStatus.INVALID:
        return _error(422, result.snapshot_version, result.error, result.detail)
    return {
        "snapshot_version": result.snapshot_version,
        "data": [render(item) for item in result.items],
    }


def create_api(reader: RegionReader) -> FastAPI:
    app = FastAPI(
        title="gi-common-reference: regions",
        version="1.0.0",
        description=(
            "Catálogo global de regiones y subregiones UN M49, versionado y de solo lectura, "
            "con nombres por locale_id."
        ),
        docs_url=None,
        redoc_url=None,
        openapi_url=OPENAPI_URL,
        redirect_slashes=False,
    )
    regions = APIRouter(prefix="/v1/regions", tags=["regions"])
    subregions = APIRouter(prefix="/v1/subregions", tags=["subregions"])

    @regions.get(
        "/by-code/{code}",
        operation_id="getRegionByCode",
        summary="Obtener una Region por su código UN M49 vigente",
        response_model=RegionEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def region_by_code(code: str, locale_id: LocaleQuery = None) -> Any:
        """La `active` que tiene el código; si ninguna, la `inactive` que lo obtuvo en el snapshot
        más reciente. Un código que no tiene 3 dígitos es 422; un código histórico, 404."""
        return _lookup(get_region_by_code(reader, code, locale_id), _region)

    @regions.get(
        "/{region_id}",
        operation_id="getRegionById",
        summary="Obtener una Region por su region_id, cualquiera sea su status",
        response_model=RegionEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def region_by_id(region_id: str, locale_id: LocaleQuery = None) -> Any:
        return _lookup(get_region_by_id(reader, region_id, locale_id), _region)

    @regions.get(
        "",
        operation_id="listRegions",
        summary="Listar las regiones publicadas, ordenadas por código",
        response_model=RegionListEnvelope,
        responses=INVALID,
    )
    def region_listing(status: StatusQuery = None, locale_id: LocaleQuery = None) -> Any:
        return _listing(list_regions(reader, status, locale_id), _region)

    @subregions.get(
        "/by-code/{code}",
        operation_id="getSubregionByCode",
        summary="Obtener una Subregion por su código UN M49 vigente",
        response_model=SubregionEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def subregion_by_code(code: str, locale_id: LocaleQuery = None) -> Any:
        """Mismas reglas que para Region; `419` pedido como Region es 404 (RF-4)."""
        return _lookup(get_subregion_by_code(reader, code, locale_id), _subregion)

    @subregions.get(
        "/{subregion_id}",
        operation_id="getSubregionById",
        summary="Obtener una Subregion por su subregion_id, cualquiera sea su status",
        response_model=SubregionEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def subregion_by_id(subregion_id: str, locale_id: LocaleQuery = None) -> Any:
        return _lookup(get_subregion_by_id(reader, subregion_id, locale_id), _subregion)

    @subregions.get(
        "",
        operation_id="listSubregions",
        summary="Listar las subregiones publicadas, ordenadas por código",
        response_model=SubregionListEnvelope,
        responses=INVALID,
    )
    def subregion_listing(
        region_id: Annotated[
            str | None, Query(description="Restringe el resultado a una Region.")
        ] = None,
        status: StatusQuery = None,
        locale_id: LocaleQuery = None,
    ) -> Any:
        return _listing(list_subregions(reader, region_id, status, locale_id), _subregion)

    app.include_router(regions)
    app.include_router(subregions)

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
        for path in ("/v1/regions", "/v1/subregions"):
            for parameter in schema["paths"][path]["get"]["parameters"]:
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
