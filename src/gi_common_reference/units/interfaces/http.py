"""API pública `/v1/quantity-kinds`, `/v1/units` y `/v1/conversions` (D15, D16). Es el único
contrato público del módulo `units`.

Todas las respuestas llevan `snapshot_version`, la versión vigente del catálogo Units: `{snapshot_
version, data}` si hay resultado o `{snapshot_version, error}` si no (`null` con el catálogo vacío).
Los errores llevan códigos estables sin traducir. Consultas: 200, «no encontrado» 404, entrada
inválida 422 y falla técnica 503. La conversión (`POST /v1/conversions`) es la única operación con
cuerpo y no escribe: cualquier rechazo de la solicitud es 422 con su código (la solicitud
referencia datos del cuerpo, no un recurso de la URL); no hay 404 en ella.

Cuerpo de la conversión: `{quantity_kind_id?, value, from_unit_id, to_unit_id, catalog_version?}`.
`value` debe ser una cadena JSON; un valor que no es cadena (p. ej. un número JSON) es
`invalid_value`. Un cuerpo que no es JSON, que no es un objeto, con campos de más o ausentes o con
tipos incorrectos (salvo `value` y `catalog_version`) es `invalid_request`. Un `catalog_version`
que no es un entero positivo (incluidos cadenas, booleanos y decimales) es
`invalid_catalog_version`.

El contrato OpenAPI propio se sirve en `/v1/openapi/units.json`.
"""

import json
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from gi_common_reference.units.application.conversions import CatalogCache, ConversionService
from gi_common_reference.units.application.queries import (
    Listing,
    Lookup,
    LookupStatus,
    get_catalog_version,
    get_quantity_kind,
    get_unit,
    list_quantity_kinds,
    list_units,
)
from gi_common_reference.units.domain.conversion import ConversionRejection, ConversionRequest
from gi_common_reference.units.domain.ports import (
    QuantityKindView,
    ReaderUnavailable,
    UnitsReader,
    UnitsSession,
    UnitView,
)

# Superficie pública del módulo (`architecture.json`). Los puertos se reexportan para que la
# composición (`app.py`) dependa solo de este módulo y no de los internos de `units`.
__all__ = ["OPENAPI_URL", "UnitsReader", "UnitsSession", "create_api"]

OPENAPI_URL = "/v1/openapi/units.json"
logger = logging.getLogger(__name__)

REJECTION_CODES = (
    "invalid_request",
    "invalid_value",
    "invalid_quantity_kind_id",
    "invalid_unit_id",
    "invalid_catalog_version",
    "quantity_kind_required",
    "quantity_kind_not_found",
    "unit_not_found",
    "inactive_quantity_kind",
    "inactive_unit",
    "incompatible_units",
    "catalog_version_not_available",
    "result_not_representable",
)
BODY_FIELDS = frozenset(
    {"quantity_kind_id", "value", "from_unit_id", "to_unit_id", "catalog_version"}
)

LocaleQuery = Annotated[
    str | None,
    Query(
        description=(
            "Devuelve `name` (y `plural`) en este locale (UUID del catálogo de Locale). Sin "
            "traducción es `null`: no hay fallback a otro locale."
        )
    ),
]
InactiveQuery = Annotated[
    bool, Query(description="Incluye también los registros `inactive` (por defecto no).")
]


class QuantityKind(BaseModel):
    """Magnitud física. La identidad es `quantity_kind_id`; `code` es clave de resolución."""

    quantity_kind_id: str = Field(description="Identidad estable de la magnitud (UUID).")
    code: str = Field(description="Código estable en minúsculas (`mass`).")
    conversion_type: Literal["linear", "affine"] = Field(
        description="`linear`: solo factor; `affine`: factor y desplazamiento."
    )
    reference_unit_id: str = Field(description="Unidad de referencia de la magnitud (UUID).")
    status: Literal["active", "inactive"]
    name: str | None = Field(description="Nombre en el `locale_id` pedido, o `null`.")


class UnitQuantityKind(BaseModel):
    quantity_kind_id: str
    status: Literal["active", "inactive"] = Field(description="Estado de la asociación.")
    reference: bool = Field(description="La unidad es la de referencia de esa magnitud.")


class Unit(BaseModel):
    """Unidad de medida: una sola identidad aunque se use en varias magnitudes (°C)."""

    unit_id: str = Field(description="Identidad estable de la unidad (UUID).")
    ucum_code: str | None
    unece_code: str | None
    symbol: str
    status: Literal["active", "inactive"]
    name: str | None = Field(description="Nombre en el `locale_id` pedido, o `null`.")
    plural: str | None = Field(description="Plural en el `locale_id` pedido, o `null`.")
    quantity_kinds: list[UnitQuantityKind] = Field(
        description="Magnitudes con las que está asociada la unidad."
    )


class VersionData(BaseModel):
    snapshot_version: int | None


class ConversionData(BaseModel):
    result: str = Field(
        description="Decimal sin exponente ni ceros finales; redondeo half-even a 34 dígitos."
    )
    exact: bool = Field(description="`false` si el resultado se redondeó.")
    unit_id: str = Field(description="La unidad destino.")
    quantity_kind_id: str
    catalog_version: int = Field(description="Versión del catálogo usada para convertir.")


class ConversionBody(BaseModel):
    """Cuerpo de `POST /v1/conversions`. `value` es una cadena JSON (no un número)."""

    model_config = ConfigDict(extra="forbid")

    quantity_kind_id: str | None = Field(
        default=None, description="Obligatoria: sin ella `quantity_kind_required`."
    )
    value: str = Field(
        description=(
            "Decimal `^-?(0|[1-9][0-9]{0,29})(\\.[0-9]{1,30})?$`. Un valor que no es cadena JSON "
            "es `invalid_value`."
        )
    )
    from_unit_id: str
    to_unit_id: str
    catalog_version: int | None = Field(
        default=None, description="Versión histórica; por defecto, la vigente."
    )


class QuantityKindEnvelope(BaseModel):
    snapshot_version: int | None
    data: QuantityKind


class QuantityKindListEnvelope(BaseModel):
    snapshot_version: int | None = Field(
        description="Snapshot vigente; `null` si todavía no se incorporó ninguno."
    )
    data: list[QuantityKind]


class UnitEnvelope(BaseModel):
    snapshot_version: int | None
    data: Unit


class UnitListEnvelope(BaseModel):
    snapshot_version: int | None
    data: list[Unit]


class VersionEnvelope(BaseModel):
    snapshot_version: int | None
    data: VersionData


class ConversionEnvelope(BaseModel):
    snapshot_version: int | None = Field(description="Versión vigente (no la usada).")
    data: ConversionData


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
UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {"model": ErrorEnvelope, "description": "Falla técnica (distinta de 404 y 422)."}
}
CONVERSION_REJECTED: dict[int | str, dict[str, Any]] = {
    422: {
        "model": ErrorEnvelope,
        "description": (
            "Solicitud rechazada; `error.code` es uno de: " + ", ".join(REJECTION_CODES) + "."
        ),
    }
}


def _kind(view: QuantityKindView) -> dict[str, Any]:
    record = view.record
    return {
        "quantity_kind_id": record.quantity_kind_id,
        "code": record.code,
        "conversion_type": record.conversion_type,
        "reference_unit_id": record.reference_unit_id,
        "status": record.status,
        "name": view.name,
    }


def _unit(view: UnitView) -> dict[str, Any]:
    record = view.record
    return {
        "unit_id": record.unit_id,
        "ucum_code": record.ucum_code,
        "unece_code": record.unece_code,
        "symbol": record.symbol,
        "status": record.status,
        "name": view.name,
        "plural": view.plural,
        "quantity_kinds": [
            {"quantity_kind_id": a.quantity_kind_id, "status": a.status, "reference": a.reference}
            for a in view.quantity_kinds
        ],
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
    if result.status is LookupStatus.NOT_FOUND:
        return _error(404, result.snapshot_version, result.error, result.detail)
    return {
        "snapshot_version": result.snapshot_version,
        "data": [render(item) for item in result.items],
    }


def _is_text_or_none(value: object) -> bool:
    return value is None or isinstance(value, str)


def _parse_conversion(raw: bytes) -> tuple[ConversionRequest, Any] | tuple[str, str]:
    """El cuerpo como (solicitud, `catalog_version` tal como llegó), o `(código, mensaje)` si no
    tiene la forma del contrato."""
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        return "invalid_request", "el cuerpo debe ser un objeto JSON"
    if not isinstance(body, dict):
        return "invalid_request", "el cuerpo debe ser un objeto JSON"
    extra = sorted(set(body) - BODY_FIELDS)
    if extra:
        return "invalid_request", f"campos no admitidos: {', '.join(extra)}"
    missing = [name for name in ("value", "from_unit_id", "to_unit_id") if name not in body]
    if missing:
        return "invalid_request", f"campos obligatorios ausentes: {', '.join(missing)}"
    for name in ("quantity_kind_id", "from_unit_id", "to_unit_id"):
        if not _is_text_or_none(body.get(name)) or (
            name != "quantity_kind_id" and body[name] is None
        ):
            return "invalid_request", f"{name} debe ser una cadena"
    if not isinstance(body["value"], str):
        return "invalid_value", "value debe ser una cadena JSON con un decimal"
    request = ConversionRequest(
        body.get("quantity_kind_id"), body["value"], body["from_unit_id"], body["to_unit_id"]
    )
    return request, body.get("catalog_version")


def create_api(reader: UnitsReader) -> FastAPI:
    # Una caché de catálogos por instancia de la aplicación (D6): las versiones son inmutables.
    conversions = ConversionService(reader, CatalogCache())
    app = FastAPI(
        title="gi-common-reference: units",
        version="1.0.0",
        description=(
            "Catálogo global de magnitudes y unidades de medida, versionado y de solo lectura: "
            "identidades estables, códigos UCUM/UNECE, nombres por `locale_id` y conversión "
            "exacta entre unidades de una magnitud. Sin cantidades, precios, productos ni "
            "unidades específicas de un tenant."
        ),
        docs_url=None,
        redoc_url=None,
        openapi_url=OPENAPI_URL,
        redirect_slashes=False,
    )
    kinds = APIRouter(prefix="/v1/quantity-kinds", tags=["quantity-kinds"])
    units = APIRouter(prefix="/v1/units", tags=["units"])
    conv = APIRouter(prefix="/v1/conversions", tags=["conversions"])

    @kinds.get(
        "/{quantity_kind_id}",
        operation_id="getQuantityKind",
        summary="Obtener una magnitud por su quantity_kind_id, cualquiera sea su status",
        response_model=QuantityKindEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def quantity_kind(quantity_kind_id: str, locale_id: LocaleQuery = None) -> Any:
        """Un id mal formado es 422; uno bien formado que no existe, 404."""
        return _lookup(get_quantity_kind(reader, quantity_kind_id, locale_id), _kind)

    @kinds.get(
        "",
        operation_id="listQuantityKinds",
        summary="Listar las magnitudes, ordenadas por código",
        response_model=QuantityKindListEnvelope,
        responses=INVALID,
    )
    def quantity_kind_listing(
        include_inactive: InactiveQuery = False,
        code: Annotated[str | None, Query(description="Igualdad exacta.")] = None,
        locale_id: LocaleQuery = None,
    ) -> Any:
        return _listing(list_quantity_kinds(reader, include_inactive, code, locale_id), _kind)

    # La ruta fija `version` se declara antes que `{unit_id}`: gana la más específica.
    @units.get(
        "/version",
        operation_id="getUnitsCatalogVersion",
        summary="Versión aplicada del catálogo Units",
        response_model=VersionEnvelope,
    )
    def catalog_version() -> Any:
        version = get_catalog_version(reader)
        return {"snapshot_version": version, "data": {"snapshot_version": version}}

    @units.get(
        "/{unit_id}",
        operation_id="getUnit",
        summary="Obtener una unidad por su unit_id, cualquiera sea su status",
        response_model=UnitEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def unit_by_id(unit_id: str, locale_id: LocaleQuery = None) -> Any:
        """Un `unit_id` mal formado es 422; uno bien formado que no existe, 404."""
        return _lookup(get_unit(reader, unit_id, locale_id), _unit)

    @units.get(
        "",
        operation_id="listUnits",
        summary="Listar las unidades, ordenadas por símbolo (orden binario) e id",
        response_model=UnitListEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def unit_listing(
        quantity_kind_id: Annotated[
            str | None,
            Query(description="Unidades asociadas (activas) a esa magnitud; 404 si no existe."),
        ] = None,
        ucum_code: Annotated[str | None, Query(description="Igualdad exacta.")] = None,
        unece_code: Annotated[str | None, Query(description="Igualdad exacta.")] = None,
        include_inactive: InactiveQuery = False,
        locale_id: LocaleQuery = None,
    ) -> Any:
        return _listing(
            list_units(
                reader, quantity_kind_id, ucum_code, unece_code, include_inactive, locale_id
            ),
            _unit,
        )

    @conv.post(
        "",
        operation_id="convertQuantity",
        summary="Convertir un valor entre dos unidades de una magnitud",
        response_model=ConversionEnvelope,
        responses=CONVERSION_REJECTED,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/ConversionBody"}}
                },
            }
        },
    )
    async def convert(request: Request) -> Any:
        """Conversión exacta (`Fraction`) con un único redondeo half-even a 34 dígitos. No se
        infiere la magnitud. Sin `catalog_version` usa la vigente; con ella reproduce la
        conversión de esa versión. No escribe."""
        parsed = _parse_conversion(await request.body())
        if isinstance(parsed[0], str):
            return _error(422, get_catalog_version(reader), parsed[0], str(parsed[1]))
        # `catalog_version` llega tal cual: el servicio valida que sea un entero positivo.
        response = conversions.convert(parsed[0], parsed[1])
        outcome = response.outcome
        if isinstance(outcome, ConversionRejection):
            return _error(422, response.snapshot_version, outcome.code, outcome.message)
        return {
            "snapshot_version": response.snapshot_version,
            "data": {
                "result": outcome.result,
                "exact": outcome.exact,
                "unit_id": outcome.unit_id,
                "quantity_kind_id": outcome.quantity_kind_id,
                "catalog_version": outcome.catalog_version,
            },
        }

    app.include_router(kinds)
    app.include_router(units)
    app.include_router(conv)

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
        schemas = schema["components"]["schemas"]
        for name in ("HTTPValidationError", "ValidationError"):
            schemas.pop(name, None)
        body = ConversionBody.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas["ConversionBody"] = {k: v for k, v in body.items() if k != "$defs"}
        for path in schema["paths"].values():
            for operation in path.values():
                responses = operation["responses"]
                responses["503"] = {
                    "description": UNAVAILABLE[503]["description"],
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                        }
                    },
                }
                if "422" in responses:
                    responses["422"]["content"] = {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                        }
                    }
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]

    # Un parámetro de query mal tipado es entrada inválida con el mismo sobre de error que el
    # resto, no el cuerpo por defecto de FastAPI.
    @app.exception_handler(RequestValidationError)
    async def invalid_parameter(request: Request, error: RequestValidationError) -> JSONResponse:
        names = sorted({str(part) for item in error.errors() for part in item["loc"][1:]})
        return _error(422, None, "invalid_parameter", f"parámetro inválido: {', '.join(names)}")

    # La causa se registra en el log; al cliente solo llega un mensaje genérico.
    @app.exception_handler(ReaderUnavailable)
    async def unavailable(request: Request, error: ReaderUnavailable) -> JSONResponse:
        logger.error("catálogo no disponible en %s %s: %s", request.method, request.url.path, error)
        return _error(503, None, "technical_error", "el catálogo no está disponible")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        logger.error("error interno en %s %s", request.method, request.url.path, exc_info=error)
        return _error(500, None, "internal_error", "error interno")

    return app
