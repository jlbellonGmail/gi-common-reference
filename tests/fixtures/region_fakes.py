"""Repositorio y lector de Regions en memoria que respetan el contrato de los puertos."""

import copy
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any

from gi_common_reference.regions.domain.errors import ConstraintRejected
from gi_common_reference.regions.domain.model import (
    CatalogState,
    EntityType,
    LocaleCatalog,
    NameRecord,
    Reclassification,
    Recoding,
    RegionRecord,
    SubregionRecord,
)
from gi_common_reference.regions.domain.ports import ReaderUnavailable, RegionView, SubregionView
from gi_common_reference.regions.domain.snapshot import HistoricalSnapshot
from tests.fixtures.regions import locale_catalog


@dataclass
class RegionState:
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    regions: dict[str, RegionRecord] = field(default_factory=dict)
    subregions: dict[str, SubregionRecord] = field(default_factory=dict)
    region_names: dict[tuple[str, str], str] = field(default_factory=dict)
    subregion_names: dict[tuple[str, str], str] = field(default_factory=dict)
    reclassifications: list[tuple[Reclassification, int]] = field(default_factory=list)
    recodings: list[tuple[Recoding, int]] = field(default_factory=list)


class FakeRegionTransaction:
    def __init__(
        self, state: RegionState, calls: list[str], repository: "FakeRegionRepository"
    ) -> None:
        self.state, self.calls, self.repository = state, calls, repository

    def _step(self, name: str) -> None:
        self.calls.append(name)
        if self.repository.fail_at == name:
            raise RuntimeError(f"fallo inyectado en {name}")

    def history(self) -> Sequence[HistoricalSnapshot]:
        return [
            HistoricalSnapshot(s["snapshot_version"], s["content_digest"])
            for s in self.state.snapshots
        ]

    def current_state(self) -> CatalogState:
        historical: list[tuple[EntityType, str, str]] = []
        for recoding_, _ in self.state.recodings:
            kind: EntityType = "region" if recoding_.entity_type == "region" else "subregion"
            historical.append((kind, recoding_.entity_id, recoding_.previous_code))
        return CatalogState(
            regions=tuple(self.state.regions.values()),
            subregions=tuple(self.state.subregions.values()),
            region_names=tuple(
                NameRecord(e, lo, n) for (e, lo), n in self.state.region_names.items()
            ),
            subregion_names=tuple(
                NameRecord(e, lo, n) for (e, lo), n in self.state.subregion_names.items()
            ),
            historical_codes=tuple(historical),
        )

    def locale_catalog(self) -> LocaleCatalog:
        return self.repository.locales

    def insert_snapshot(
        self, document: Mapping[str, Any], locale_snapshot_version: int, policy_version: int
    ) -> None:
        self._step("insert_snapshot")
        stored = copy.deepcopy(dict(document))
        stored["_locale_snapshot_version"] = locale_snapshot_version
        stored["_policy_version"] = policy_version
        self.state.snapshots.append(stored)

    def insert_regions(self, regions: Sequence[RegionRecord], version: int) -> None:
        self._step("insert_regions")
        self.state.regions.update({r.region_id: r for r in regions})

    def update_regions(self, regions: Sequence[RegionRecord], version: int) -> None:
        self._step("update_regions")
        self.state.regions.update({r.region_id: r for r in regions})

    def insert_subregions(self, subregions: Sequence[SubregionRecord], version: int) -> None:
        self._step("insert_subregions")
        self.state.subregions.update({s.subregion_id: s for s in subregions})

    def update_subregions(self, subregions: Sequence[SubregionRecord], version: int) -> None:
        self._step("update_subregions")
        self.state.subregions.update({s.subregion_id: s for s in subregions})

    def record_reclassifications(
        self, reclassifications: Sequence[Reclassification], version: int
    ) -> None:
        self._step("record_reclassifications")
        self.state.reclassifications += [(r, version) for r in reclassifications]

    def record_recodings(self, recodings: Sequence[Recoding], version: int) -> None:
        self._step("record_recodings")
        self.state.recodings += [(r, version) for r in recodings]

    def insert_names(
        self, region_names: Sequence[NameRecord], subregion_names: Sequence[NameRecord]
    ) -> None:
        self._step("insert_names")
        self.state.region_names.update({(n.entity_id, n.locale_id): n.name for n in region_names})
        self.state.subregion_names.update(
            {(n.entity_id, n.locale_id): n.name for n in subregion_names}
        )

    def update_names(
        self, region_names: Sequence[NameRecord], subregion_names: Sequence[NameRecord]
    ) -> None:
        self._step("update_names")
        self.insert_names(region_names, subregion_names)
        self.calls.pop()  # `insert_names` interno: no es un paso propio

    def check_constraints(self) -> None:
        self._step("check_constraints")
        if self.repository.constraint_failure is not None:
            raise self.repository.constraint_failure


class FakeRegionRepository:
    def __init__(self, locales: LocaleCatalog | None = None) -> None:
        self.state = RegionState()
        self.calls: list[str] = []
        self.fail_at: str | None = None
        self.constraint_failure: ConstraintRejected | None = None
        self.locales = locales if locales is not None else locale_catalog()
        self.transactions = 0

    @contextmanager
    def transaction(self) -> Iterator[FakeRegionTransaction]:
        self.transactions += 1
        staged = copy.deepcopy(self.state)
        yield FakeRegionTransaction(staged, self.calls, self)
        self.state = staged  # solo se confirma si no hubo excepción


class FakeRegionSession:
    def __init__(self, reader: "FakeRegionReader") -> None:
        self._reader = reader

    def snapshot_version(self) -> int | None:
        return self._reader.version

    def locale_exists(self, locale_id: str) -> bool:
        return locale_id in self._reader.locale_ids

    def _name(
        self, names: Mapping[tuple[str, str], str], entity_id: str, locale_id: str | None
    ) -> str | None:
        return None if locale_id is None else names.get((entity_id, locale_id))

    def _region(self, record: RegionRecord, locale_id: str | None) -> RegionView:
        return RegionView(
            record, self._name(self._reader.region_names, record.region_id, locale_id)
        )

    def _subregion(self, record: SubregionRecord, locale_id: str | None) -> SubregionView:
        name = self._name(self._reader.subregion_names, record.subregion_id, locale_id)
        return SubregionView(record, name)

    def regions(self, status: str | None, locale_id: str | None) -> Sequence[RegionView]:
        chosen = [r for r in self._reader.regions if status is None or r.status == status]
        return [self._region(r, locale_id) for r in sorted(chosen, key=_order)]

    def region_by_id(self, region_id: str, locale_id: str | None) -> RegionView | None:
        found = next((r for r in self._reader.regions if r.region_id == region_id), None)
        return None if found is None else self._region(found, locale_id)

    def region_by_code(self, code: str, locale_id: str | None) -> RegionView | None:
        found = [r for r in self._reader.regions if r.code == code]
        found.sort(key=lambda r: (r.status != "active", r.region_id))
        return self._region(found[0], locale_id) if found else None

    def subregions(
        self, region_id: str | None, status: str | None, locale_id: str | None
    ) -> Sequence[SubregionView]:
        chosen = [
            s
            for s in self._reader.subregions
            if (status is None or s.status == status)
            and (region_id is None or s.region_id == region_id)
        ]
        return [self._subregion(s, locale_id) for s in sorted(chosen, key=_order)]

    def subregion_by_id(self, subregion_id: str, locale_id: str | None) -> SubregionView | None:
        found = next((s for s in self._reader.subregions if s.subregion_id == subregion_id), None)
        return None if found is None else self._subregion(found, locale_id)

    def subregion_by_code(self, code: str, locale_id: str | None) -> SubregionView | None:
        found = [s for s in self._reader.subregions if s.code == code]
        found.sort(key=lambda s: (s.status != "active", s.subregion_id))
        return self._subregion(found[0], locale_id) if found else None


def _order(record: RegionRecord | SubregionRecord) -> tuple[bool, str, str]:
    identifier = record.region_id if isinstance(record, RegionRecord) else record.subregion_id
    return (record.code is None, record.code or "", identifier)


class FakeRegionReader:
    """Lector en memoria; cuenta las sesiones para comprobar una sola por consulta."""

    def __init__(
        self,
        version: int | None = None,
        regions: Sequence[RegionRecord] = (),
        subregions: Sequence[SubregionRecord] = (),
        region_names: Mapping[tuple[str, str], str] | None = None,
        subregion_names: Mapping[tuple[str, str], str] | None = None,
        locale_ids: Sequence[str] = (),
    ) -> None:
        self.version = version
        self.regions, self.subregions = list(regions), list(subregions)
        self.region_names = dict(region_names or {})
        self.subregion_names = dict(subregion_names or {})
        self.locale_ids = set(locale_ids)
        self.sessions = 0
        self.unavailable = False

    @contextmanager
    def session(self) -> Iterator[FakeRegionSession]:
        if self.unavailable:
            raise ReaderUnavailable("la base no responde")
        self.sessions += 1
        yield FakeRegionSession(self)


def with_status(record: SubregionRecord, status: str) -> SubregionRecord:
    return replace(record, status=status)
