"""Repositorio de Currency en memoria que respeta el contrato de los puertos."""

import copy
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from gi_common_reference.currencies.domain.errors import ConstraintRejected
from gi_common_reference.currencies.domain.model import (
    CatalogState,
    CountryCatalog,
    CountryCurrencyRecord,
    CurrencyRecord,
    LocaleCatalog,
    NameRecord,
)
from gi_common_reference.currencies.domain.ports import IntegrityViolation
from gi_common_reference.currencies.domain.snapshot import HistoricalSnapshot
from tests.fixtures.currencies import country_catalog, locale_catalog


@dataclass
class CurrencyState:
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    currencies: dict[str, CurrencyRecord] = field(default_factory=dict)
    names: dict[tuple[str, str], NameRecord] = field(default_factory=dict)
    associations: dict[str, CountryCurrencyRecord] = field(default_factory=dict)
    versions: dict[str, list[int]] = field(default_factory=dict)  # id → [primero, último]


class FakeCatalogView:
    def __init__(self, state: CurrencyState, repository: "FakeCurrencyRepository") -> None:
        self.state, self.repository = state, repository

    def history(self) -> Sequence[HistoricalSnapshot]:
        return [
            HistoricalSnapshot(s["snapshot_version"], s["content_digest"])
            for s in self.state.snapshots
        ]

    def current_state(self) -> CatalogState:
        return CatalogState(
            currencies=tuple(self.state.currencies.values()),
            names=tuple(self.state.names.values()),
            associations=tuple(self.state.associations.values()),
        )

    def locale_catalog(self) -> LocaleCatalog:
        return self.repository.locales

    def country_catalog(self) -> CountryCatalog:
        return self.repository.countries

    def integrity_violations(self) -> Sequence[IntegrityViolation]:
        countries = {c.country_id: c for c in self.repository.countries.countries}
        found = []
        for a in self.state.associations.values():
            if a.status != "active" or a.valid_to is not None:
                continue
            country, currency = countries.get(a.country_id), self.state.currencies[a.currency_id]
            country_off = country is not None and country.status != "active"
            currency_off = currency.status != "active"
            if country_off or currency_off:
                found.append(
                    IntegrityViolation(
                        a.country_currency_id,
                        a.country_id,
                        a.currency_id,
                        country_off,
                        currency_off,
                    )
                )
        return found


class FakeCurrencyTransaction(FakeCatalogView):
    def _step(self, name: str) -> None:
        self.repository.calls.append(name)
        if self.repository.fail_at == name:
            raise RuntimeError(f"fallo inyectado en {name}")

    def insert_snapshot(
        self,
        document: Mapping[str, Any],
        locale_snapshot_version: int,
        country_current_snapshot_version: int,
        policy_version: int,
    ) -> None:
        self._step("insert_snapshot")
        stored = copy.deepcopy(dict(document))
        stored["_locale_snapshot_version"] = locale_snapshot_version
        stored["_country_current_snapshot_version"] = country_current_snapshot_version
        stored["_policy_version"] = policy_version
        self.state.snapshots.append(stored)

    def insert_currencies(self, currencies: Sequence[CurrencyRecord], version: int) -> None:
        self._step("insert_currencies")
        for currency in currencies:
            self.state.currencies[currency.currency_id] = currency
            self.state.versions[currency.currency_id] = [version, version]

    def update_currencies(self, currencies: Sequence[CurrencyRecord], version: int) -> None:
        self._step("update_currencies")
        for currency in currencies:
            self.state.currencies[currency.currency_id] = currency
            self.state.versions[currency.currency_id][1] = version

    def insert_names(self, names: Sequence[NameRecord]) -> None:
        self._step("insert_names")
        self.state.names.update({(n.currency_id, n.locale_id): n for n in names})

    def update_names(self, names: Sequence[NameRecord]) -> None:
        self._step("update_names")
        self.state.names.update({(n.currency_id, n.locale_id): n for n in names})

    def insert_associations(
        self, associations: Sequence[CountryCurrencyRecord], version: int
    ) -> None:
        self._step("insert_associations")
        for a in associations:
            self.state.associations[a.country_currency_id] = a
            self.state.versions[a.country_currency_id] = [version, version]

    def update_associations(
        self, associations: Sequence[CountryCurrencyRecord], version: int
    ) -> None:
        self._step("update_associations")
        for a in associations:
            self.state.associations[a.country_currency_id] = a
            self.state.versions[a.country_currency_id][1] = version

    def touch_currencies(self, currency_ids: Sequence[str], version: int) -> None:
        self._step("touch_currencies")
        for currency_id in currency_ids:
            self.state.versions[currency_id][1] = version

    def check_constraints(self) -> None:
        self._step("check_constraints")
        if self.repository.constraint_failure is not None:
            raise self.repository.constraint_failure


class FakeCurrencyRepository:
    def __init__(
        self, locales: LocaleCatalog | None = None, countries: CountryCatalog | None = None
    ) -> None:
        self.state = CurrencyState()
        self.calls: list[str] = []
        self.fail_at: str | None = None
        self.constraint_failure: ConstraintRejected | None = None
        self.locales = locales if locales is not None else locale_catalog()
        self.countries = countries if countries is not None else country_catalog()
        self.transactions = 0
        self.inspections = 0

    @contextmanager
    def transaction(self) -> Iterator[FakeCurrencyTransaction]:
        self.transactions += 1
        staged = copy.deepcopy(self.state)
        yield FakeCurrencyTransaction(staged, self)
        self.state = staged  # solo se confirma si no hubo excepción

    @contextmanager
    def inspect(self) -> Iterator[FakeCatalogView]:
        self.inspections += 1
        yield FakeCatalogView(copy.deepcopy(self.state), self)
