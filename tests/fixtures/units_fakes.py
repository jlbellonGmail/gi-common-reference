"""Repositorio de Units en memoria que respeta el contrato de los puertos (T6)."""

import copy
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from gi_common_reference.units.domain.errors import ConstraintRejected
from gi_common_reference.units.domain.model import (
    AssociationRecord,
    CatalogState,
    KindNameRecord,
    LocaleCatalog,
    LocaleInfo,
    QuantityKindRecord,
    UnitNameRecord,
    UnitRecord,
)
from gi_common_reference.units.domain.snapshot import HistoricalSnapshot
from tests.fixtures.units import EN, ES


def default_locales() -> LocaleCatalog:
    return LocaleCatalog(1, (LocaleInfo(EN, "en", "active"), LocaleInfo(ES, "es", "active")))


@dataclass
class UnitsState:
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    units: dict[str, UnitRecord] = field(default_factory=dict)
    kinds: dict[str, QuantityKindRecord] = field(default_factory=dict)
    associations: dict[tuple[str, str], AssociationRecord] = field(default_factory=dict)
    kind_names: dict[tuple[str, str], KindNameRecord] = field(default_factory=dict)
    unit_names: dict[tuple[str, str], UnitNameRecord] = field(default_factory=dict)
    versions: dict[Any, list[int]] = field(default_factory=dict)  # clave → [primero, último]


class FakeUnitsView:
    def __init__(self, state: UnitsState, repository: "FakeUnitsRepository") -> None:
        self.state, self.repository = state, repository

    def history(self) -> Sequence[HistoricalSnapshot]:
        return [
            HistoricalSnapshot(s["snapshot_version"], s["content_digest"])
            for s in self.state.snapshots
        ]

    def current_state(self) -> CatalogState:
        return CatalogState(
            quantity_kinds=tuple(self.state.kinds.values()),
            units=tuple(self.state.units.values()),
            associations=tuple(self.state.associations.values()),
            kind_names=tuple(self.state.kind_names.values()),
            unit_names=tuple(self.state.unit_names.values()),
        )

    def locale_catalog(self) -> LocaleCatalog:
        return self.repository.locales


class FakeUnitsTransaction(FakeUnitsView):
    def _step(self, name: str) -> None:
        self.repository.calls.append(name)
        if self.repository.fail_at == name:
            raise RuntimeError(f"fallo inyectado en {name}")

    def insert_snapshot(
        self,
        document: Mapping[str, Any],
        locale_snapshot_version: int,
        policy_version: int,
        ucum_table_version: str,
    ) -> None:
        self._step("insert_snapshot")
        stored = copy.deepcopy(dict(document))
        stored["_locale_snapshot_version"] = locale_snapshot_version
        stored["_policy_version"] = policy_version
        stored["_ucum_table_version"] = ucum_table_version
        self.state.snapshots.append(stored)

    def insert_units(self, units: Sequence[UnitRecord], version: int) -> None:
        self._step("insert_units")
        for item in units:
            self.state.units[item.unit_id] = item
            self.state.versions[item.unit_id] = [version, version]

    def update_units(self, units: Sequence[UnitRecord], version: int) -> None:
        self._step("update_units")
        for item in units:
            self.state.units[item.unit_id] = item
            self.state.versions[item.unit_id][1] = version

    def insert_quantity_kinds(self, kinds: Sequence[QuantityKindRecord], version: int) -> None:
        self._step("insert_quantity_kinds")
        for item in kinds:
            self.state.kinds[item.quantity_kind_id] = item
            self.state.versions[item.quantity_kind_id] = [version, version]

    def update_quantity_kinds(self, kinds: Sequence[QuantityKindRecord], version: int) -> None:
        self._step("update_quantity_kinds")
        for item in kinds:
            self.state.kinds[item.quantity_kind_id] = item
            self.state.versions[item.quantity_kind_id][1] = version

    def insert_associations(self, associations: Sequence[AssociationRecord], version: int) -> None:
        self._step("insert_associations")
        for item in associations:
            key = (item.quantity_kind_id, item.unit_id)
            self.state.associations[key] = item
            self.state.versions[key] = [version, version]

    def update_associations(self, associations: Sequence[AssociationRecord], version: int) -> None:
        self._step("update_associations")
        for item in associations:
            key = (item.quantity_kind_id, item.unit_id)
            self.state.associations[key] = item
            self.state.versions[key][1] = version

    def insert_kind_names(self, names: Sequence[KindNameRecord]) -> None:
        self._step("insert_kind_names")
        self.state.kind_names.update({(n.quantity_kind_id, n.locale_id): n for n in names})

    def update_kind_names(self, names: Sequence[KindNameRecord]) -> None:
        self._step("update_kind_names")
        self.state.kind_names.update({(n.quantity_kind_id, n.locale_id): n for n in names})

    def insert_unit_names(self, names: Sequence[UnitNameRecord]) -> None:
        self._step("insert_unit_names")
        self.state.unit_names.update({(n.unit_id, n.locale_id): n for n in names})

    def update_unit_names(self, names: Sequence[UnitNameRecord]) -> None:
        self._step("update_unit_names")
        self.state.unit_names.update({(n.unit_id, n.locale_id): n for n in names})

    def touch_units(self, unit_ids: Sequence[str], version: int) -> None:
        self._step("touch_units")
        for unit_id in unit_ids:
            self.state.versions[unit_id][1] = version

    def touch_quantity_kinds(self, kind_ids: Sequence[str], version: int) -> None:
        self._step("touch_quantity_kinds")
        for kind_id in kind_ids:
            self.state.versions[kind_id][1] = version

    def check_constraints(self) -> None:
        self._step("check_constraints")
        if self.repository.constraint_failure is not None:
            raise self.repository.constraint_failure


class FakeUnitsRepository:
    def __init__(self, locales: LocaleCatalog | None = None) -> None:
        self.state = UnitsState()
        self.calls: list[str] = []
        self.fail_at: str | None = None
        self.constraint_failure: ConstraintRejected | None = None
        self.locales = locales if locales is not None else default_locales()
        self.transactions = 0
        self.inspections = 0

    @contextmanager
    def transaction(self) -> Iterator[FakeUnitsTransaction]:
        self.transactions += 1
        staged = copy.deepcopy(self.state)
        yield FakeUnitsTransaction(staged, self)
        self.state = staged  # solo se confirma si no hubo excepción

    @contextmanager
    def inspect(self) -> Iterator[FakeUnitsView]:
        self.inspections += 1
        yield FakeUnitsView(copy.deepcopy(self.state), self)
