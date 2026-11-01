"""Lector de Currency en memoria: implementa la semántica de los puertos de lectura.

Es la referencia de las consultas: las pruebas de integración comparan el lector de Postgres con
este sobre los mismos datos. Se construye desde un documento de snapshot (o vacío).
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from typing import Any

from gi_common_reference.currencies.domain.catalog import incoming_from
from gi_common_reference.currencies.domain.ports import (
    AssociationView,
    CurrencyView,
    ReaderUnavailable,
)
from tests.fixtures.currencies import COUNTRY_CODES, EN, ES, country_id

FR = "d3e9a5c2-0a4c-4a4e-9a5b-3a9e2a4f9a11"  # un locale válido sin traducciones


class FakeClock:
    def __init__(self, today: date) -> None:
        self._today = today

    def today(self) -> date:
        return self._today


class InMemoryCurrencySession:
    def __init__(self, reader: "InMemoryCurrencyReader") -> None:
        self._reader = reader

    def snapshot_version(self) -> int | None:
        return self._reader.version

    def locale_exists(self, locale_id: str) -> bool:
        return locale_id in self._reader.locale_ids

    def country_exists(self, country_id: str) -> bool:
        return country_id in self._reader.country_ids

    def _name(self, currency_id: str, locale_id: str | None) -> str | None:
        if locale_id is None:
            return None
        return self._reader.names.get((currency_id, locale_id))

    def _view(self, currency_id: str, locale_id: str | None) -> CurrencyView:
        return CurrencyView(
            self._reader.currencies[currency_id], self._name(currency_id, locale_id)
        )

    def currencies(
        self, include_inactive: bool, exclude_funds: bool, locale_id: str | None
    ) -> Sequence[CurrencyView]:
        chosen = [
            c
            for c in self._reader.currencies.values()
            if (include_inactive or c.status == "active") and not (exclude_funds and c.fund_code)
        ]
        chosen.sort(key=lambda c: (c.alphabetic_code.encode(), c.currency_id))
        return [self._view(c.currency_id, locale_id) for c in chosen]

    def currency_by_id(self, currency_id: str, locale_id: str | None) -> CurrencyView | None:
        return (
            self._view(currency_id, locale_id) if currency_id in self._reader.currencies else None
        )

    def currency_by_code(self, code: str, locale_id: str | None) -> CurrencyView | None:
        for c in self._reader.currencies.values():
            if c.alphabetic_code == code:
                return self._view(c.currency_id, locale_id)
        return None

    def associations_of_country(
        self, country_id: str, locale_id: str | None
    ) -> Sequence[AssociationView]:
        return [
            AssociationView(a, self._view(a.currency_id, locale_id))
            for a in self._reader.associations
            if a.country_id == country_id
        ]

    def associations_of_currency(
        self, currency_id: str, locale_id: str | None
    ) -> Sequence[AssociationView]:
        return [
            AssociationView(a, self._view(a.currency_id, locale_id))
            for a in self._reader.associations
            if a.currency_id == currency_id
        ]


class InMemoryCurrencyReader:
    """Cuenta las sesiones para comprobar una sola por consulta; puede simular la base caída."""

    def __init__(self, document: dict[str, Any] | None = None) -> None:
        incoming = incoming_from(document or {})
        self.version = document["snapshot_version"] if document else None
        self.currencies = {c.currency_id: c for c in incoming.currencies}
        self.names = {(n.currency_id, n.locale_id): n.name for n in incoming.names}
        self.associations = list(incoming.associations)
        self.locale_ids = {EN, ES, FR}
        self.country_ids = {country_id(code) for code in COUNTRY_CODES} if document else set()
        self.sessions = 0
        self.unavailable = False

    @contextmanager
    def session(self) -> Iterator[InMemoryCurrencySession]:
        if self.unavailable:
            raise ReaderUnavailable("OperationalError (SQLSTATE 08006)")
        self.sessions += 1
        yield InMemoryCurrencySession(self)
