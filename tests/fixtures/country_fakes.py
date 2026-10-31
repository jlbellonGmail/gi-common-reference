"""Repositorio de Countries en memoria que respeta el contrato de los puertos."""

import copy
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from gi_common_reference.countries.domain.errors import ConstraintRejected
from gi_common_reference.countries.domain.model import (
    CatalogState,
    CodeKind,
    CountryRecord,
    FlagRecord,
    LocaleCatalog,
    NameRecord,
    Recoding,
    RegionCatalog,
)
from gi_common_reference.countries.domain.snapshot import HistoricalSnapshot
from tests.fixtures.countries import locale_catalog, region_catalog


@dataclass
class CountryState:
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    countries: dict[str, CountryRecord] = field(default_factory=dict)
    names: dict[tuple[str, str], NameRecord] = field(default_factory=dict)
    flags: dict[str, FlagRecord] = field(default_factory=dict)
    recodings: list[tuple[Recoding, int]] = field(default_factory=list)
    versions: dict[str, list[int]] = field(default_factory=dict)  # id → [primero, códigos, último]


class FakeCatalogView:
    def __init__(self, state: CountryState, repository: "FakeCountryRepository") -> None:
        self.state, self.repository = state, repository

    def history(self) -> Sequence[HistoricalSnapshot]:
        return [
            HistoricalSnapshot(s["snapshot_version"], s["content_digest"])
            for s in self.state.snapshots
        ]

    def current_state(self) -> CatalogState:
        historical: list[tuple[CodeKind, str, str]] = []
        kinds: tuple[CodeKind, ...] = ("alpha2", "alpha3", "numeric_code")
        for recoding, _ in self.state.recodings:
            current = self.state.countries[recoding.country_id].triple
            for kind in kinds:
                if recoding.previous.code(kind) != current.code(kind):
                    historical.append((kind, recoding.previous.code(kind), recoding.country_id))
        return CatalogState(
            countries=tuple(self.state.countries.values()),
            names=tuple(self.state.names.values()),
            flags=tuple(self.state.flags.values()),
            historical_codes=tuple(historical),
        )

    def locale_catalog(self) -> LocaleCatalog:
        return self.repository.locales

    def region_catalog(self) -> RegionCatalog:
        return self.repository.regions


class FakeCountryTransaction(FakeCatalogView):
    def _step(self, name: str) -> None:
        self.repository.calls.append(name)
        if self.repository.fail_at == name:
            raise RuntimeError(f"fallo inyectado en {name}")

    def insert_snapshot(
        self,
        document: Mapping[str, Any],
        locale_snapshot_version: int,
        region_current_snapshot_version: int,
        policy_version: int,
    ) -> None:
        self._step("insert_snapshot")
        stored = copy.deepcopy(dict(document))
        stored["_locale_snapshot_version"] = locale_snapshot_version
        stored["_region_current_snapshot_version"] = region_current_snapshot_version
        stored["_policy_version"] = policy_version
        self.state.snapshots.append(stored)

    def insert_countries(self, countries: Sequence[CountryRecord], version: int) -> None:
        self._step("insert_countries")
        for country in countries:
            self.state.countries[country.country_id] = country
            self.state.versions[country.country_id] = [version, version, version]

    def update_countries(self, countries: Sequence[CountryRecord], version: int) -> None:
        self._step("update_countries")
        for country in countries:
            before = self.state.countries[country.country_id]
            versions = self.state.versions[country.country_id]
            if before.triple != country.triple:
                versions[1] = version
            versions[2] = version
            self.state.countries[country.country_id] = country

    def record_recodings(self, recodings: Sequence[Recoding], version: int) -> None:
        self._step("record_recodings")
        self.state.recodings += [(r, version) for r in recodings]

    def insert_names(self, names: Sequence[NameRecord]) -> None:
        self._step("insert_names")
        self.state.names.update({(n.country_id, n.locale_id): n for n in names})

    def update_names(self, names: Sequence[NameRecord]) -> None:
        self._step("update_names")
        self.state.names.update({(n.country_id, n.locale_id): n for n in names})

    def write_flags(
        self, new: Sequence[FlagRecord], updated: Sequence[FlagRecord], version: int
    ) -> None:
        self._step("write_flags")
        self.state.flags.update({f.country_id: f for f in (*new, *updated)})

    def touch_countries(self, country_ids: Sequence[str], version: int) -> None:
        self._step("touch_countries")
        for country_id in country_ids:
            self.state.versions[country_id][2] = version

    def check_constraints(self) -> None:
        self._step("check_constraints")
        if self.repository.constraint_failure is not None:
            raise self.repository.constraint_failure


class FakeCountryRepository:
    def __init__(
        self, locales: LocaleCatalog | None = None, regions: RegionCatalog | None = None
    ) -> None:
        self.state = CountryState()
        self.calls: list[str] = []
        self.fail_at: str | None = None
        self.constraint_failure: ConstraintRejected | None = None
        self.locales = locales if locales is not None else locale_catalog()
        self.regions = regions if regions is not None else region_catalog()
        self.transactions = 0
        self.inspections = 0

    @contextmanager
    def transaction(self) -> Iterator[FakeCountryTransaction]:
        self.transactions += 1
        staged = copy.deepcopy(self.state)
        yield FakeCountryTransaction(staged, self)
        self.state = staged  # solo se confirma si no hubo excepción

    @contextmanager
    def inspect(self) -> Iterator[FakeCatalogView]:
        self.inspections += 1
        yield FakeCatalogView(copy.deepcopy(self.state), self)
