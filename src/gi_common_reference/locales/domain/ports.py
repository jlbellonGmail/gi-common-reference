"""Puertos del dominio de Locale: lo que la incorporación necesita de la persistencia."""

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from gi_common_reference.locales.domain.model import LocaleRecord
from gi_common_reference.locales.domain.snapshot import HistoricalSnapshot


class SnapshotFormatError(ValueError):
    """El archivo no es un snapshot estructuralmente válido; `errors` lista cada problema."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


SnapshotReader = Callable[[Path], dict[str, Any]]
"""Lee un archivo local de snapshot y devuelve su documento ya validado (RF-31, paso 1)."""


class IncorporationTransaction(Protocol):
    """Una transacción de incorporación. Las escrituras se llaman en este orden (RF-18, RF-20)."""

    def history(self) -> Sequence[HistoricalSnapshot]: ...

    def current_locales(self) -> Sequence[LocaleRecord]: ...

    def insert_snapshot(self, document: Mapping[str, Any]) -> None: ...

    def insert_locales(
        self, locales: Sequence[LocaleRecord], first_snapshot_version: int
    ) -> None: ...

    def update_metadata(self, locales: Sequence[LocaleRecord]) -> None: ...

    def replace_aliases(self, aliases: Mapping[str, str]) -> None: ...


class LocaleRepository(Protocol):
    def transaction(self) -> AbstractContextManager[IncorporationTransaction]:
        """Serializa las incorporaciones; confirma al salir sin error y deshace ante cualquiera."""
        ...


class ReaderUnavailable(Exception):
    """La fuente de lectura no responde (p. ej. la base está caída)."""


class LocaleSession(Protocol):
    """Lecturas de una sesión consistente: todas ven el mismo estado del catálogo."""

    def snapshot_version(self) -> int | None: ...

    def by_id(self, locale_id: str) -> LocaleRecord | None: ...

    def by_code(self, code: str) -> LocaleRecord | None: ...

    def alias(self, subtag: str) -> str | None: ...

    def all_locales(self, status: str | None) -> Sequence[LocaleRecord]: ...


class LocaleReader(Protocol):
    def session(self) -> AbstractContextManager[LocaleSession]:
        """Una sesión de solo lectura; `snapshot_version` y los datos salen del mismo estado."""
        ...
