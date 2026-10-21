"""Adaptador de Postgres para la incorporación (D2: psycopg 3 con SQL explícito, D12: lock)."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from gi_common_reference.locales.domain.errors import PersistenceError, describe_error
from gi_common_reference.locales.domain.model import LocaleRecord
from gi_common_reference.locales.domain.snapshot import HistoricalSnapshot
from gi_common_reference.locales.infrastructure.conninfo import validate_conninfo

LOCK_NAME = "gi-common-reference.locales.incorporation"


class PostgresLocaleRepository:
    """Cada `transaction()` abre una conexión, toma el lock y confirma o deshace todo junto."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = validate_conninfo(conninfo)

    @contextmanager
    def transaction(self) -> Iterator["PostgresTransaction"]:
        """Los errores del driver salen como `PersistenceError`: su texto puede citar la conexión"""
        try:
            with psycopg.connect(
                self._conninfo
            ) as connection:  # commit al salir; rollback si falla
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [LOCK_NAME]
                )
                yield PostgresTransaction(connection)
        except psycopg.Error as error:
            raise PersistenceError(describe_error(error)) from None


class PostgresTransaction:
    def __init__(self, connection: "psycopg.Connection[Any]") -> None:
        self._connection = connection

    def history(self) -> Sequence[HistoricalSnapshot]:
        rows = self._connection.execute(
            "SELECT snapshot_version, content_digest, iana_file_date "
            "FROM reference.locale_snapshot ORDER BY snapshot_version"
        ).fetchall()
        return [
            HistoricalSnapshot(version, digest, file_date) for version, digest, file_date in rows
        ]

    def current_locales(self) -> Sequence[LocaleRecord]:
        rows = self._connection.execute(
            "SELECT locale_id::text, code, status, iana_deprecated, replacement_locale_id::text "
            "FROM reference.locale ORDER BY code"
        ).fetchall()
        return [LocaleRecord(*row) for row in rows]

    def insert_snapshot(self, document: Mapping[str, Any]) -> None:
        iana = document["iana"]
        self._connection.execute(
            "INSERT INTO reference.locale_snapshot "
            "(snapshot_version, content_digest, iana_file_date, iana_digest, provenance, artifact) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [
                document["snapshot_version"],
                document["content_digest"],
                date.fromisoformat(iana["file_date"]),
                iana["digest"],
                Jsonb(document["provenance"]),
                Jsonb(document),
            ],
        )

    def insert_locales(self, locales: Sequence[LocaleRecord], first_snapshot_version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.locale "
                "(locale_id, code, status, iana_deprecated, replacement_locale_id, "
                "first_snapshot_version) VALUES (%s::uuid, %s, %s, %s, %s::uuid, %s)",
                [
                    (
                        r.locale_id,
                        r.code,
                        r.status,
                        r.iana_deprecated,
                        r.replacement_locale_id,
                        first_snapshot_version,
                    )
                    for r in locales
                ],
            )

    def update_metadata(self, locales: Sequence[LocaleRecord]) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE reference.locale SET status = %s, iana_deprecated = %s, "
                "replacement_locale_id = %s::uuid WHERE locale_id = %s::uuid",
                [
                    (r.status, r.iana_deprecated, r.replacement_locale_id, r.locale_id)
                    for r in locales
                ],
            )

    def replace_aliases(self, aliases: Mapping[str, str]) -> None:
        self._connection.execute("DELETE FROM reference.locale_alias")
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.locale_alias (subtag, preferred_value) VALUES (%s, %s)",
                sorted(aliases.items()),
            )
