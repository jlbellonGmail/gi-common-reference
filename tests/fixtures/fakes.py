"""Repositorio en memoria que respeta el contrato transaccional del puerto."""

import copy
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from gi_common_reference.locales.domain.model import LocaleRecord
from gi_common_reference.locales.domain.snapshot import HistoricalSnapshot


@dataclass
class State:
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    locales: dict[str, LocaleRecord] = field(default_factory=dict)
    first_snapshot: dict[str, int] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)


class FakeTransaction:
    def __init__(self, state: State, calls: list[str], fail_at: str | None) -> None:
        self.state, self.calls, self.fail_at = state, calls, fail_at

    def _step(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError(f"fallo inyectado en {name}")

    def history(self) -> Sequence[HistoricalSnapshot]:
        return [
            HistoricalSnapshot(
                s["snapshot_version"],
                s["content_digest"],
                date.fromisoformat(s["iana"]["file_date"]),
            )
            for s in self.state.snapshots
        ]

    def current_locales(self) -> Sequence[LocaleRecord]:
        return list(self.state.locales.values())

    def insert_snapshot(self, document: Mapping[str, Any]) -> None:
        self._step("insert_snapshot")
        self.state.snapshots.append(copy.deepcopy(dict(document)))

    def insert_locales(self, locales: Sequence[LocaleRecord], first_snapshot_version: int) -> None:
        self._step("insert_locales")
        for record in locales:
            self.state.locales[record.locale_id] = record
            self.state.first_snapshot[record.locale_id] = first_snapshot_version

    def update_metadata(self, locales: Sequence[LocaleRecord]) -> None:
        self._step("update_metadata")
        for record in locales:
            self.state.locales[record.locale_id] = record

    def replace_aliases(self, aliases: Mapping[str, str]) -> None:
        self._step("replace_aliases")
        self.state.aliases = dict(aliases)


class FakeRepository:
    def __init__(self) -> None:
        self.state = State()
        self.calls: list[str] = []
        self.fail_at: str | None = None
        self.transactions = 0

    @contextmanager
    def transaction(self) -> Iterator[FakeTransaction]:
        self.transactions += 1
        staged = copy.deepcopy(self.state)
        yield FakeTransaction(staged, self.calls, self.fail_at)
        self.state = staged  # solo se confirma si no hubo excepción


class FakeSession:
    def __init__(
        self, version: int | None, locales: Sequence[LocaleRecord], aliases: Mapping[str, str]
    ) -> None:
        self._version, self._locales, self._aliases = version, list(locales), dict(aliases)

    def snapshot_version(self) -> int | None:
        return self._version

    def by_id(self, locale_id: str) -> LocaleRecord | None:
        return next((r for r in self._locales if r.locale_id == locale_id), None)

    def by_code(self, code: str) -> LocaleRecord | None:
        return next((r for r in self._locales if r.code == code), None)

    def alias(self, subtag: str) -> str | None:
        return self._aliases.get(subtag)

    def all_locales(self, status: str | None) -> Sequence[LocaleRecord]:
        chosen = [r for r in self._locales if status is None or r.status == status]
        return sorted(chosen, key=lambda r: r.code)


class FakeReader:
    """Lector en memoria; cuenta las sesiones para comprobar una sola por consulta."""

    def __init__(
        self,
        version: int | None = None,
        locales: Sequence[LocaleRecord] = (),
        aliases: Mapping[str, str] | None = None,
    ) -> None:
        self.version, self.locales, self.aliases = version, list(locales), dict(aliases or {})
        self.sessions = 0
        self.unavailable = False

    @contextmanager
    def session(self) -> Iterator[FakeSession]:
        from gi_common_reference.locales.domain.ports import ReaderUnavailable

        if self.unavailable:
            raise ReaderUnavailable("la base no responde")
        self.sessions += 1
        yield FakeSession(self.version, self.locales, self.aliases)
