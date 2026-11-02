"""Consultas de solo lectura del catálogo Currency (RF-15, RF-22 a RF-32, RF-48 a RF-50).

Cada consulta usa una única sesión: la `snapshot_version` informada y los datos salen del mismo
estado del catálogo, aunque se incorpore un snapshot en paralelo. Un parámetro inválido es un error
de validación (`INVALID`), distinto de «no encontrado» (RF-24, RF-25); una falla técnica no se
captura aquí: sube como `ReaderUnavailable` (RF-26). Los errores llevan códigos estables y legibles
por máquina, sin traducir (D20 del plan).

Las asociaciones se filtran por fecha con `domain.temporal`, la misma semántica `[inicio, fin)` que
el SQL (RF-44); `status` y vigencia se aplican como criterios independientes (RF-51).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from gi_common_reference.currencies.domain.codes import normalize_code_for_lookup
from gi_common_reference.currencies.domain.ports import (
    AssociationView,
    Clock,
    CurrencyReader,
    CurrencySession,
    CurrencyView,
)
from gi_common_reference.currencies.domain.temporal import history_order_key, in_force_on

UUID_TEXT = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
DAY_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class LookupStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    INVALID = "invalid"


class Validation(StrEnum):
    """Resultado de validar un `currency_id` (RF-28): nunca es un `status` persistido."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class Lookup[T]:
    status: LookupStatus
    snapshot_version: int | None
    item: T | None = None
    error: str = ""  # código de error estable para el contrato (p. ej. `unknown_locale`)
    detail: str = ""


@dataclass(frozen=True)
class Listing[T]:
    status: LookupStatus
    snapshot_version: int | None
    items: tuple[T, ...] = ()
    error: str = ""
    detail: str = ""


@dataclass(frozen=True)
class _Invalid:
    error: str
    detail: str


def _locale(session: CurrencySession, locale_id: str | None) -> str | None | _Invalid:
    """RF-15: `None` sin locale; el `locale_id` normalizado; o el motivo del 422."""
    if locale_id is None:
        return None
    if not UUID_TEXT.fullmatch(locale_id):
        return _Invalid("invalid_locale_id", "locale_id debe ser un UUID")
    key = locale_id.lower()
    if not session.locale_exists(key):
        return _Invalid("unknown_locale", "el locale_id no existe en el catálogo de Locale")
    return key


def _key(locale: str | None | _Invalid) -> str | None:
    return locale if isinstance(locale, str) else None


def _day(text: str | None, clock: Clock) -> date | _Invalid:
    """RF-48: la fecha de referencia o, sin ella, el día UTC del reloj (D14)."""
    if text is None:
        return clock.today()
    try:
        if DAY_TEXT.fullmatch(text) is None:
            raise ValueError(text)
        return date.fromisoformat(text)
    except ValueError:
        return _Invalid("invalid_as_of_date", "as_of debe ser un día real con formato YYYY-MM-DD")


def _not_found(version: int | None, error: str) -> Lookup[object]:
    return Lookup(LookupStatus.NOT_FOUND, version, None, error, "no encontrado")


def get_catalog_version(reader: CurrencyReader) -> int | None:
    """RF-32: la versión aplicada del catálogo Currency (`None` con catálogo vacío)."""
    with reader.session() as session:
        return session.snapshot_version()


def get_currency_by_id(
    reader: CurrencyReader, currency_id: str, locale_id: str | None = None
) -> Lookup[CurrencyView]:
    """RF-22, RF-24, RF-25: `active` o `inactive`; un id mal formado es error de validación."""
    with reader.session() as session:
        version = session.snapshot_version()
        if not UUID_TEXT.fullmatch(currency_id):
            return Lookup(
                LookupStatus.INVALID,
                version,
                None,
                "invalid_currency_id",
                "currency_id debe ser un UUID",
            )
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Lookup(LookupStatus.INVALID, version, None, locale.error, locale.detail)
        found = session.currency_by_id(currency_id.lower(), _key(locale))
    if found is None:
        return Lookup(LookupStatus.NOT_FOUND, version, None, "currency_not_found", "no encontrado")
    return Lookup(LookupStatus.FOUND, version, found)


def get_currency_by_code(
    reader: CurrencyReader, code: str, locale_id: str | None = None
) -> Lookup[CurrencyView]:
    """RF-23 a RF-25: sin distinguir mayúsculas; ` USD`, `US`, `US$` o vacío son inválidos."""
    with reader.session() as session:
        version = session.snapshot_version()
        normalized = normalize_code_for_lookup(code)
        if normalized is None:
            return Lookup(
                LookupStatus.INVALID,
                version,
                None,
                "invalid_code",
                "el código debe tener 3 letras A-Z (p. ej. USD)",
            )
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Lookup(LookupStatus.INVALID, version, None, locale.error, locale.detail)
        found = session.currency_by_code(normalized, _key(locale))
    if found is None:
        return Lookup(LookupStatus.NOT_FOUND, version, None, "currency_not_found", "no encontrado")
    return Lookup(LookupStatus.FOUND, version, found)


def list_currencies(
    reader: CurrencyReader,
    include_inactive: bool = False,
    exclude_funds: bool = False,
    locale_id: str | None = None,
) -> Listing[CurrencyView]:
    """RF-27: por defecto solo las `active`, en orden por código alfabético."""
    with reader.session() as session:
        version = session.snapshot_version()
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Listing(LookupStatus.INVALID, version, (), locale.error, locale.detail)
        items = session.currencies(include_inactive, exclude_funds, _key(locale))
    return Listing(LookupStatus.FOUND, version, tuple(items))


def validate_currency(reader: CurrencyReader, currency_id: str) -> Lookup[Validation]:
    """RF-28: `active`, `inactive` o `not_found`, sin decidir si el consumidor acepta inactivas."""
    with reader.session() as session:
        version = session.snapshot_version()
        if not UUID_TEXT.fullmatch(currency_id):
            return Lookup(
                LookupStatus.INVALID,
                version,
                None,
                "invalid_currency_id",
                "currency_id debe ser un UUID",
            )
        found = session.currency_by_id(currency_id.lower(), None)
    if found is None:
        return Lookup(LookupStatus.FOUND, version, Validation.NOT_FOUND)
    return Lookup(LookupStatus.FOUND, version, Validation(found.record.status))


def _associations_in_force(
    items: Sequence[AssociationView],
    day: date,
    include_inactive: bool,
    exclude_funds: bool,
) -> list[AssociationView]:
    by_id = {item.association.country_currency_id: item for item in items}
    kept = in_force_on((i.association for i in items), day, include_inactive=include_inactive)
    return [
        by_id[a.country_currency_id]
        for a in kept
        if not (exclude_funds and by_id[a.country_currency_id].currency.record.fund_code)
    ]


def currencies_of_country(
    reader: CurrencyReader,
    clock: Clock,
    country_id: str,
    as_of: str | None = None,
    include_inactive: bool = False,
    exclude_funds: bool = False,
    locale_id: str | None = None,
) -> Listing[AssociationView]:
    """RF-18, RF-30, RF-48: las monedas del país en la fecha de referencia.

    Orden por código alfabético, luego inicio de vigencia e id. Un país existente sin monedas, o sin
    monedas en esa fecha, devuelve lista vacía; un `country_id` inexistente, «no encontrado».
    """
    with reader.session() as session:
        version = session.snapshot_version()
        if not UUID_TEXT.fullmatch(country_id):
            return Listing(
                LookupStatus.INVALID,
                version,
                (),
                "invalid_country_id",
                "country_id debe ser un UUID",
            )
        day = _day(as_of, clock)
        if isinstance(day, _Invalid):
            return Listing(LookupStatus.INVALID, version, (), day.error, day.detail)
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Listing(LookupStatus.INVALID, version, (), locale.error, locale.detail)
        key = country_id.lower()
        if not session.country_exists(key):
            return Listing(
                LookupStatus.NOT_FOUND, version, (), "country_not_found", "no encontrado"
            )
        items = session.associations_of_country(key, _key(locale))
    chosen = _associations_in_force(items, day, include_inactive, exclude_funds)
    chosen.sort(
        key=lambda v: (
            v.currency.record.alphabetic_code,
            history_order_key(v.association),
        )
    )
    return Listing(LookupStatus.FOUND, version, tuple(chosen))


def countries_of_currency(
    reader: CurrencyReader,
    clock: Clock,
    currency_id: str,
    as_of: str | None = None,
    include_inactive: bool = False,
) -> Listing[AssociationView]:
    """RF-31, RF-48: los países de la moneda en la fecha de referencia, por `country_id`."""
    with reader.session() as session:
        version = session.snapshot_version()
        if not UUID_TEXT.fullmatch(currency_id):
            return Listing(
                LookupStatus.INVALID,
                version,
                (),
                "invalid_currency_id",
                "currency_id debe ser un UUID",
            )
        day = _day(as_of, clock)
        if isinstance(day, _Invalid):
            return Listing(LookupStatus.INVALID, version, (), day.error, day.detail)
        key = currency_id.lower()
        if session.currency_by_id(key, None) is None:
            return Listing(
                LookupStatus.NOT_FOUND, version, (), "currency_not_found", "no encontrado"
            )
        items = session.associations_of_currency(key, None)
    chosen = _associations_in_force(items, day, include_inactive, False)
    chosen.sort(key=lambda v: (v.association.country_id, history_order_key(v.association)))
    return Listing(LookupStatus.FOUND, version, tuple(chosen))


def history_of_country(
    reader: CurrencyReader,
    country_id: str,
    include_inactive: bool = False,
    locale_id: str | None = None,
) -> Listing[AssociationView]:
    """RF-49: todas las asociaciones `active` (y con opción las `inactive`), sin filtrar por fecha.

    Orden: inicio de vigencia con los ausentes primero, luego código alfabético e id.
    """
    with reader.session() as session:
        version = session.snapshot_version()
        if not UUID_TEXT.fullmatch(country_id):
            return Listing(
                LookupStatus.INVALID,
                version,
                (),
                "invalid_country_id",
                "country_id debe ser un UUID",
            )
        locale = _locale(session, locale_id)
        if isinstance(locale, _Invalid):
            return Listing(LookupStatus.INVALID, version, (), locale.error, locale.detail)
        key = country_id.lower()
        if not session.country_exists(key):
            return Listing(
                LookupStatus.NOT_FOUND, version, (), "country_not_found", "no encontrado"
            )
        items = session.associations_of_country(key, _key(locale))
    chosen = [i for i in items if include_inactive or i.association.status == "active"]
    chosen.sort(
        key=lambda v: (
            history_order_key(v.association)[:2],
            v.currency.record.alphabetic_code,
            v.association.country_currency_id,
        )
    )
    return Listing(LookupStatus.FOUND, version, tuple(chosen))


def history_of_currency(
    reader: CurrencyReader, currency_id: str, include_inactive: bool = False
) -> Listing[AssociationView]:
    """RF-49: el historial de países de la moneda, sin filtrar por fecha."""
    with reader.session() as session:
        version = session.snapshot_version()
        if not UUID_TEXT.fullmatch(currency_id):
            return Listing(
                LookupStatus.INVALID,
                version,
                (),
                "invalid_currency_id",
                "currency_id debe ser un UUID",
            )
        key = currency_id.lower()
        if session.currency_by_id(key, None) is None:
            return Listing(
                LookupStatus.NOT_FOUND, version, (), "currency_not_found", "no encontrado"
            )
        items = session.associations_of_currency(key, None)
    chosen = [i for i in items if include_inactive or i.association.status == "active"]
    chosen.sort(
        key=lambda v: (
            history_order_key(v.association)[:2],
            v.association.country_id,
            v.association.country_currency_id,
        )
    )
    return Listing(LookupStatus.FOUND, version, tuple(chosen))
