"""API pública de solo lectura `/v1/currencies` (D18). Es el único contrato público del módulo
`currencies`.

Todas las respuestas llevan `snapshot_version`, la versión vigente del catálogo Currency (RF-32):
`{snapshot_version, data}` si hay resultado o `{snapshot_version, error}` si no. Con el catálogo
vacío es `null`. Los errores llevan códigos estables sin traducir (D20 del plan). Los cinco
resultados de RF-26 son distinguibles: entidad `active` y entidad `inactive` (200, campo `status`),
«no encontrado» (404), entrada inválida (422) y error técnico (503).

No existe ninguna ruta de escritura (RF-34): cualquier método distinto de GET es 405. El contrato
OpenAPI propio se sirve en `/v1/openapi/currencies.json`.
"""

import logging
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gi_common_reference.currencies.application.queries import (
    Listing,
    Lookup,
    LookupStatus,
    Validation,
    countries_of_currency,
    currencies_of_country,
    get_catalog_version,
    get_currency_by_code,
    get_currency_by_id,
    history_of_country,
    history_of_currency,
    list_currencies,
    validate_currency,
)
from gi_common_reference.currencies.domain.ports import (
    AssociationView,
    Clock,
    CurrencyReader,
    CurrencySession,
    CurrencyView,
    ReaderUnavailable,
)

# Superficie pública del módulo (`architecture.json`). Los puertos se reexportan para que la
# composición (`app.py`) dependa solo de este módulo y no de los internos de `currencies`.
__all__ = [
    "OPENAPI_URL",
    "Clock",
    "CurrencyReader",
    "CurrencySession",
    "create_api",
]

OPENAPI_URL = "/v1/openapi/currencies.json"
logger = logging.getLogger(__name__)

LocaleQuery = Annotated[
    str | None,
    Query(
        description=(
            "Devuelve `name` en este locale (UUID del catálogo de Locale). Sin traducción es "
            "`null`: no hay fallback a otro locale."
        )
    ),
]
AsOfQuery = Annotated[
    str | None,
    Query(
        description=(
            "Fecha de referencia `YYYY-MM-DD` (día calendario). La vigencia `[valid_from, "
            "valid_to)` incluye el día de inicio y excluye el de fin. Por defecto, el día UTC de "
            "la consulta."
        )
    ),
]
InactiveQuery = Annotated[
    bool, Query(description="Incluye también los registros `inactive` (por defecto no).")
]
FundsQuery = Annotated[bool, Query(description="Excluye los códigos de fondos (BOV, CHE, CLF…).")]


class Currency(BaseModel):
    """Moneda ISO 4217. La identidad es `currency_id`; el código alfabético es clave de resolución.

    Sin ningún texto propio (el nombre es de `CurrencyLocale`), ni símbolos, ni formato (D-11).
    """

    currency_id: str = Field(description="Identidad estable de la moneda (UUID de Reference).")
    alphabetic_code: str = Field(description="ISO 4217 alfabético (`USD`).")
    numeric_code: str = Field(description="ISO 4217 numérico, con ceros (`032`). Solo atributo.")
    minor_units: int | None = Field(
        description="Dígitos decimales estándar; `null` es «no aplicable» (distinto de 0)."
    )
    fund_code: bool = Field(description="ISO la declara código de fondos.")
    status: Literal["active", "inactive"] = Field(
        description="`active`: apta para nuevas referencias; `inactive`: sigue resoluble."
    )
    replacement_currency_ids: list[str] = Field(
        description=(
            "Monedas sucesoras (0..N), en orden ascendente de `currency_id`; vacío si no hay "
            "sucesión declarada o si la moneda es `active`."
        )
    )
    name: str | None = Field(description="Nombre en el `locale_id` pedido, o `null`.")


class CountryCurrency(BaseModel):
    """Asociación Country–Currency. `status` es el ciclo de vida del registro; la vigencia es el
    período real `[valid_from, valid_to)` y no la sustituye."""

    country_currency_id: str = Field(description="Identidad de la asociación (UUID).")
    country_id: str = Field(description="UUID de un Country publicado por 003-countries.")
    currency: Currency
    status: Literal["active", "inactive"] = Field(description="Ciclo de vida del registro.")
    valid_from: str | None = Field(
        description="Primer día en que corresponde (incluido); `null` si no está acotado."
    )
    valid_to: str | None = Field(
        description="Primer día en que ya no corresponde (excluido); `null` sin fin declarado."
    )


class VersionData(BaseModel):
    snapshot_version: int | None


class ValidationData(BaseModel):
    result: Literal["active", "inactive", "not_found"] = Field(
        description="Resultado de la consulta; `not_found` nunca es un `status` persistido."
    )


class CurrencyEnvelope(BaseModel):
    snapshot_version: int | None
    data: Currency


class CurrencyListEnvelope(BaseModel):
    snapshot_version: int | None = Field(
        description="Snapshot vigente; `null` si todavía no se incorporó ninguno."
    )
    data: list[Currency]


class AssociationListEnvelope(BaseModel):
    snapshot_version: int | None
    data: list[CountryCurrency]


class VersionEnvelope(BaseModel):
    snapshot_version: int | None
    data: VersionData


class ValidationEnvelope(BaseModel):
    snapshot_version: int | None
    data: ValidationData


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


def _currency(view: CurrencyView) -> dict[str, Any]:
    record = view.record
    return {
        "currency_id": record.currency_id,
        "alphabetic_code": record.alphabetic_code,
        "numeric_code": record.numeric_code,
        "minor_units": record.minor_units,
        "fund_code": record.fund_code,
        "status": record.status,
        "replacement_currency_ids": list(record.replacement_currency_ids),
        "name": view.name,
    }


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _association(view: AssociationView) -> dict[str, Any]:
    record = view.association
    return {
        "country_currency_id": record.country_currency_id,
        "country_id": record.country_id,
        "currency": _currency(view.currency),
        "status": record.status,
        "valid_from": _day(record.valid_from),
        "valid_to": _day(record.valid_to),
    }


def _error(status: int, snapshot_version: int | None, code: str, message: str) -> JSONResponse:
    body = {"snapshot_version": snapshot_version, "error": {"code": code, "message": message}}
    return JSONResponse(status_code=status, content=body)


def _lookup(result: Lookup[CurrencyView]) -> Any:
    if result.status is LookupStatus.FOUND and result.item is not None:
        return {"snapshot_version": result.snapshot_version, "data": _currency(result.item)}
    if result.status is LookupStatus.INVALID:
        return _error(422, result.snapshot_version, result.error, result.detail)
    return _error(404, result.snapshot_version, result.error, result.detail)


def _listing(result: Listing[CurrencyView]) -> Any:
    if result.status is LookupStatus.INVALID:
        return _error(422, result.snapshot_version, result.error, result.detail)
    return {
        "snapshot_version": result.snapshot_version,
        "data": [_currency(item) for item in result.items],
    }


def _associations(result: Listing[AssociationView]) -> Any:
    if result.status is LookupStatus.INVALID:
        return _error(422, result.snapshot_version, result.error, result.detail)
    if result.status is LookupStatus.NOT_FOUND:
        return _error(404, result.snapshot_version, result.error, result.detail)
    return {
        "snapshot_version": result.snapshot_version,
        "data": [_association(item) for item in result.items],
    }


def create_api(reader: CurrencyReader, clock: Clock) -> FastAPI:
    app = FastAPI(
        title="gi-common-reference: currencies",
        version="1.0.0",
        description=(
            "Catálogo global de monedas ISO 4217, versionado y de solo lectura: identidad "
            "`currency_id`, código alfabético de resolución, nombres por `locale_id` y "
            "asociaciones Country–Currency con vigencia temporal. Sin cotizaciones, tipos de "
            "cambio, precios ni saldos."
        ),
        docs_url=None,
        redoc_url=None,
        openapi_url=OPENAPI_URL,
        redirect_slashes=False,
    )
    router = APIRouter(prefix="/v1/currencies", tags=["currencies"])

    # Las rutas fijas (`version`, `by-code`, `by-country`) se declaran antes que `{currency_id}`:
    # gana la más específica.
    @router.get(
        "/version",
        operation_id="getCurrencyCatalogVersion",
        summary="Versión aplicada del catálogo Currency",
        response_model=VersionEnvelope,
    )
    def catalog_version() -> Any:
        version = get_catalog_version(reader)
        return {"snapshot_version": version, "data": {"snapshot_version": version}}

    @router.get(
        "/by-code/{code}",
        operation_id="getCurrencyByCode",
        summary="Obtener una moneda por su código alfabético ISO 4217",
        response_model=CurrencyEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def currency_by_code(code: str, locale_id: LocaleQuery = None) -> Any:
        """Sin distinguir mayúsculas (`usd`). Un código mal formado (` USD`, `US`, vacío) es 422;
        uno bien formado que no existe, 404. Resuelve también las monedas `inactive`."""
        return _lookup(get_currency_by_code(reader, code, locale_id))

    @router.get(
        "/by-country/{country_id}/history",
        operation_id="getCountryCurrencyHistory",
        summary="Historial completo de monedas de un país, sin filtrar por fecha",
        response_model=AssociationListEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def country_history(
        country_id: str, include_inactive: InactiveQuery = False, locale_id: LocaleQuery = None
    ) -> Any:
        """Orden: inicio de vigencia (los ausentes primero), código alfabético e id."""
        return _associations(history_of_country(reader, country_id, include_inactive, locale_id))

    @router.get(
        "/by-country/{country_id}",
        operation_id="listCountryCurrencies",
        summary="Monedas de un país en una fecha de referencia",
        response_model=AssociationListEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def country_currencies(
        country_id: str,
        as_of: AsOfQuery = None,
        include_inactive: InactiveQuery = False,
        exclude_funds: FundsQuery = False,
        locale_id: LocaleQuery = None,
    ) -> Any:
        """Un país existente sin monedas, o sin monedas en esa fecha, devuelve lista vacía; un
        `country_id` inexistente, 404."""
        return _associations(
            currencies_of_country(
                reader, clock, country_id, as_of, include_inactive, exclude_funds, locale_id
            )
        )

    @router.get(
        "/{currency_id}/validation",
        operation_id="validateCurrency",
        summary="Validar un currency_id: active, inactive o not_found",
        response_model=ValidationEnvelope,
        responses=INVALID,
    )
    def currency_validation(currency_id: str) -> Any:
        """No decide si el consumidor acepta monedas `inactive`."""
        result: Lookup[Validation] = validate_currency(reader, currency_id)
        if result.status is LookupStatus.INVALID:
            return _error(422, result.snapshot_version, result.error, result.detail)
        value = result.item.value if result.item is not None else Validation.NOT_FOUND.value
        return {"snapshot_version": result.snapshot_version, "data": {"result": value}}

    @router.get(
        "/{currency_id}/countries/history",
        operation_id="getCurrencyCountryHistory",
        summary="Historial completo de países de una moneda, sin filtrar por fecha",
        response_model=AssociationListEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def currency_countries_history(
        currency_id: str, include_inactive: InactiveQuery = False
    ) -> Any:
        return _associations(history_of_currency(reader, currency_id, include_inactive))

    @router.get(
        "/{currency_id}/countries",
        operation_id="listCurrencyCountries",
        summary="Países de una moneda en una fecha de referencia",
        response_model=AssociationListEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def currency_countries(
        currency_id: str, as_of: AsOfQuery = None, include_inactive: InactiveQuery = False
    ) -> Any:
        """Solo `country_id` y vigencia: los datos del país los resuelve el contrato de 003."""
        return _associations(
            countries_of_currency(reader, clock, currency_id, as_of, include_inactive)
        )

    @router.get(
        "/{currency_id}",
        operation_id="getCurrencyById",
        summary="Obtener una moneda por su currency_id, cualquiera sea su status",
        response_model=CurrencyEnvelope,
        responses={**NOT_FOUND, **INVALID},
    )
    def currency_by_id(currency_id: str, locale_id: LocaleQuery = None) -> Any:
        """Un `currency_id` mal formado es 422; uno bien formado que no existe, 404."""
        return _lookup(get_currency_by_id(reader, currency_id, locale_id))

    @router.get(
        "",
        operation_id="listCurrencies",
        summary="Listar las monedas, ordenadas por código alfabético",
        response_model=CurrencyListEnvelope,
        responses=INVALID,
    )
    def currency_listing(
        include_inactive: InactiveQuery = False,
        exclude_funds: FundsQuery = False,
        locale_id: LocaleQuery = None,
    ) -> Any:
        return _listing(list_currencies(reader, include_inactive, exclude_funds, locale_id))

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

    # Un parámetro de query mal tipado (p. ej. `include_inactive=maybe`) es entrada inválida con el
    # mismo sobre de error que el resto, no el cuerpo por defecto de FastAPI.
    @app.exception_handler(RequestValidationError)
    async def invalid_parameter(request: Request, error: RequestValidationError) -> JSONResponse:
        names = sorted({str(part) for item in error.errors() for part in item["loc"][1:]})
        return _error(422, None, "invalid_parameter", f"parámetro inválido: {', '.join(names)}")

    # La causa se registra en el log; al cliente solo llega un mensaje genérico. No se registra la
    # query string ni la cadena de conexión.
    @app.exception_handler(ReaderUnavailable)
    async def unavailable(request: Request, error: ReaderUnavailable) -> JSONResponse:
        logger.error("catálogo no disponible en %s %s: %s", request.method, request.url.path, error)
        return _error(503, None, "technical_error", "el catálogo no está disponible")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        logger.error("error interno en %s %s", request.method, request.url.path, exc_info=error)
        return _error(500, None, "internal_error", "error interno")

    return app
