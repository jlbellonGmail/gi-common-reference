"""Adaptador de lectura sobre Postgres (D1, D10): la API se conecta con `reference_reader`."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg

from gi_common_reference.locales.domain.errors import describe_error
from gi_common_reference.locales.domain.model import LocaleRecord
from gi_common_reference.locales.domain.ports import ReaderUnavailable
from gi_common_reference.locales.infrastructure.conninfo import validate_conninfo

COLUMNS = "locale_id::text, code, status, iana_deprecated, replacement_locale_id::text"


class PostgresLocaleReader:
    """Una conexión por sesión, de solo lectura y con una instantánea consistente."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = validate_conninfo(conninfo)

    @contextmanager
    def session(self) -> Iterator["PostgresSession"]:
        """Cualquier error del driver al conectar, y los de conexión perdida a mitad de sesión,
        salen como `ReaderUnavailable` con solo tipo y SQLSTATE: su texto puede citar la conexión.
        Los demás errores de las consultas no se traducen."""
        try:
            connection = psycopg.connect(self._conninfo)
        except psycopg.Error as error:
            raise ReaderUnavailable(describe_error(error)) from None
        try:
            with connection:
                connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                connection.read_only = True
                yield PostgresSession(connection)
        except psycopg.OperationalError as error:
            raise ReaderUnavailable(describe_error(error)) from None


class PostgresSession:
    def __init__(self, connection: "psycopg.Connection[Any]") -> None:
        self._connection = connection

    def snapshot_version(self) -> int | None:
        row = self._connection.execute(
            "SELECT max(snapshot_version) FROM reference.locale_snapshot"
        ).fetchone()
        return None if row is None else row[0]

    def by_id(self, locale_id: str) -> LocaleRecord | None:
        row = self._connection.execute(
            f"SELECT {COLUMNS} FROM reference.locale WHERE locale_id = %s::uuid",
            [locale_id],
        ).fetchone()
        return None if row is None else LocaleRecord(*row)

    def by_code(self, code: str) -> LocaleRecord | None:
        row = self._connection.execute(
            f"SELECT {COLUMNS} FROM reference.locale WHERE code = %s",
            [code],
        ).fetchone()
        return None if row is None else LocaleRecord(*row)

    def alias(self, subtag: str) -> str | None:
        row = self._connection.execute(
            "SELECT preferred_value FROM reference.locale_alias WHERE subtag = %s", [subtag]
        ).fetchone()
        return None if row is None else row[0]

    def all_locales(self, status: str | None) -> Sequence[LocaleRecord]:
        rows = self._connection.execute(
            f"SELECT {COLUMNS} FROM reference.locale "
            "WHERE (%s::text IS NULL OR status = %s) ORDER BY code",
            [status, status],
        ).fetchall()
        return [LocaleRecord(*row) for row in rows]
