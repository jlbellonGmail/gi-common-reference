"""Lector de Units en memoria: implementa la semántica de los puertos de lectura (T7).

Es la referencia de las consultas: las pruebas de integración comparan el lector de Postgres con
este sobre los mismos datos. Se construye desde uno o más documentos de snapshot (el de mayor
versión es el vigente; todos quedan disponibles como artefactos) o vacío.
"""

import copy
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from gi_common_reference.units.domain.catalog import incoming_from
from gi_common_reference.units.domain.ports import (
    QuantityKindView,
    ReaderUnavailable,
    UnitAssociationView,
    UnitView,
)
from tests.fixtures.units import EN, ES

FR = "d3e9a5c2-0a4c-4a4e-9a5b-3a9e2a4f9a11"  # un locale válido sin traducciones


class InMemoryUnitsSession:
    def __init__(self, reader: "InMemoryUnitsReader") -> None:
        self._reader = reader

    def snapshot_version(self) -> int | None:
        return self._reader.version

    def locale_exists(self, locale_id: str) -> bool:
        return locale_id in self._reader.locale_ids

    def quantity_kind_exists(self, quantity_kind_id: str) -> bool:
        return quantity_kind_id in self._reader.kinds

    def _kind(self, quantity_kind_id: str, locale_id: str | None) -> QuantityKindView:
        name = (
            None
            if locale_id is None
            else self._reader.kind_names.get((quantity_kind_id, locale_id))
        )
        return QuantityKindView(self._reader.kinds[quantity_kind_id], name)

    def _unit(self, unit_id: str, locale_id: str | None) -> UnitView:
        name = plural = None
        if locale_id is not None and (unit_id, locale_id) in self._reader.unit_names:
            found = self._reader.unit_names[(unit_id, locale_id)]
            name, plural = found.name, found.plural
        associations = sorted(
            (
                UnitAssociationView(
                    a.quantity_kind_id,
                    a.status,
                    self._reader.kinds[a.quantity_kind_id].reference_unit_id == unit_id,
                )
                for a in self._reader.associations
                if a.unit_id == unit_id
            ),
            key=lambda item: item.quantity_kind_id,
        )
        return UnitView(self._reader.units[unit_id], name, plural, tuple(associations))

    def quantity_kinds(
        self, include_inactive: bool, code: str | None, locale_id: str | None
    ) -> list[QuantityKindView]:
        chosen = [
            k
            for k in self._reader.kinds.values()
            if (include_inactive or k.status == "active") and (code is None or k.code == code)
        ]
        chosen.sort(key=lambda k: (k.code.encode(), k.quantity_kind_id))
        return [self._kind(k.quantity_kind_id, locale_id) for k in chosen]

    def quantity_kind_by_id(
        self, quantity_kind_id: str, locale_id: str | None
    ) -> QuantityKindView | None:
        return (
            self._kind(quantity_kind_id, locale_id)
            if quantity_kind_id in self._reader.kinds
            else None
        )

    def units(
        self,
        quantity_kind_id: str | None,
        ucum_code: str | None,
        unece_code: str | None,
        include_inactive: bool,
        locale_id: str | None,
    ) -> list[UnitView]:
        def linked(unit_id: str) -> bool:
            return any(
                a.unit_id == unit_id
                and a.quantity_kind_id == quantity_kind_id
                and (include_inactive or a.status == "active")
                for a in self._reader.associations
            )

        chosen = [
            u
            for u in self._reader.units.values()
            if (include_inactive or u.status == "active")
            and (ucum_code is None or u.ucum_code == ucum_code)
            and (unece_code is None or u.unece_code == unece_code)
            and (quantity_kind_id is None or linked(u.unit_id))
        ]
        chosen.sort(key=lambda u: (u.symbol.encode(), u.unit_id))
        return [self._unit(u.unit_id, locale_id) for u in chosen]

    def unit_by_id(self, unit_id: str, locale_id: str | None) -> UnitView | None:
        return self._unit(unit_id, locale_id) if unit_id in self._reader.units else None

    def artifact(self, snapshot_version: int) -> Mapping[str, Any] | None:
        self._reader.artifact_reads.append(snapshot_version)
        found = self._reader.artifacts.get(snapshot_version)
        return None if found is None else copy.deepcopy(found)


class InMemoryUnitsReader:
    """Cuenta las sesiones y las lecturas de artefactos; puede simular la base caída."""

    def __init__(self, *documents: dict[str, Any]) -> None:
        self.artifacts = {d["snapshot_version"]: d for d in documents}
        current = max(documents, key=lambda d: d["snapshot_version"]) if documents else None
        incoming = incoming_from(current or {})
        self.version = current["snapshot_version"] if current else None
        self.kinds = {k.quantity_kind_id: k for k in incoming.quantity_kinds}
        self.units = {u.unit_id: u for u in incoming.units}
        self.associations = list(incoming.associations)
        self.kind_names = {(n.quantity_kind_id, n.locale_id): n.name for n in incoming.kind_names}
        self.unit_names = {(n.unit_id, n.locale_id): n for n in incoming.unit_names}
        self.locale_ids = {EN, ES, FR}
        self.sessions = 0
        self.artifact_reads: list[int] = []
        self.unavailable = False

    @contextmanager
    def session(self) -> Iterator[InMemoryUnitsSession]:
        if self.unavailable:
            raise ReaderUnavailable("OperationalError (SQLSTATE 08006)")
        self.sessions += 1
        yield InMemoryUnitsSession(self)
