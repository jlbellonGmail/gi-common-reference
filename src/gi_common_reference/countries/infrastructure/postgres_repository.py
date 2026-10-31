"""Adaptador de Postgres para la incorporación de Countries (psycopg 3 con SQL explícito, D15, D17).

Cada transacción toma el lock exclusivo de Countries y locks compartidos sobre los de Locale y
Regions: ni Locale ni Regions cambian mientras se valida contra ellos (RF-36, RF-47, RF-48). Lee
`reference.locale`, `reference.region` y sus snapshots del mismo schema; no importa código de
`locales` ni de `regions` (RNF-7).
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import errors
from psycopg.types.json import Jsonb

from gi_common_reference.countries.domain.errors import (
    ConstraintRejected,
    PersistenceError,
    describe_error,
)
from gi_common_reference.countries.domain.model import (
    CatalogState,
    CodeKind,
    CountryRecord,
    FlagRecord,
    LocaleCatalog,
    LocaleInfo,
    NameRecord,
    Recoding,
    RegionCatalog,
    RegionInfo,
    SubregionInfo,
)
from gi_common_reference.countries.domain.snapshot import HistoricalSnapshot
from gi_common_reference.countries.infrastructure.conninfo import validate_conninfo

LOCK_NAME = "gi-common-reference.countries.incorporation"
LOCALES_LOCK_NAME = "gi-common-reference.locales.incorporation"  # el que toma Locale (D12 de 001)
REGIONS_LOCK_NAME = "gi-common-reference.regions.incorporation"  # el que toma Regions (D1 de 002)

# Un código que ya no es el vigente de su país fue histórico: salió de una recodificación (RF-43).
HISTORICAL_CODES = (
    "SELECT 'alpha2', r.previous_alpha2, r.country_id::text FROM reference.country_recoding r "
    "JOIN reference.country c USING (country_id) WHERE r.previous_alpha2 <> c.alpha2 "
    "UNION ALL SELECT 'alpha3', r.previous_alpha3, r.country_id::text "
    "FROM reference.country_recoding r JOIN reference.country c USING (country_id) "
    "WHERE r.previous_alpha3 <> c.alpha3 "
    "UNION ALL SELECT 'numeric_code', r.previous_numeric_code, r.country_id::text "
    "FROM reference.country_recoding r JOIN reference.country c USING (country_id) "
    "WHERE r.previous_numeric_code <> c.numeric_code ORDER BY 1, 2, 3"
)


class PostgresCountryRepository:
    """Cada `transaction()` abre una conexión, toma los locks y confirma o deshace todo junto."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = validate_conninfo(conninfo)

    @contextmanager
    def transaction(self) -> Iterator["PostgresCountryTransaction"]:
        """Una constraint violada sale como `ConstraintRejected` (con su nombre, D17); los demás
        errores del driver, como `PersistenceError` con solo tipo y SQLSTATE."""
        try:
            with psycopg.connect(self._conninfo) as connection:  # commit al salir; si no, rollback
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [LOCK_NAME]
                )
                for shared in (LOCALES_LOCK_NAME, REGIONS_LOCK_NAME):
                    connection.execute(
                        "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))", [shared]
                    )
                yield PostgresCountryTransaction(connection)
        except errors.IntegrityError as error:
            raise ConstraintRejected(
                error.diag.constraint_name,
                error.sqlstate,
                isinstance(error, errors.ForeignKeyViolation),
            ) from None
        except psycopg.Error as error:
            raise PersistenceError(describe_error(error)) from None

    @contextmanager
    def inspect(self) -> Iterator["PostgresCatalogView"]:
        """Vista de solo lectura sobre una instantánea consistente; sin locks (RF-30, D18)."""
        try:
            with psycopg.connect(self._conninfo) as connection:
                connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                connection.read_only = True
                yield PostgresCatalogView(connection)
        except psycopg.Error as error:
            raise PersistenceError(describe_error(error)) from None


class PostgresCatalogView:
    def __init__(self, connection: "psycopg.Connection[Any]") -> None:
        self._connection = connection

    def history(self) -> Sequence[HistoricalSnapshot]:
        rows = self._connection.execute(
            "SELECT snapshot_version, content_digest FROM reference.country_snapshot "
            "ORDER BY snapshot_version"
        ).fetchall()
        return [HistoricalSnapshot(version, digest) for version, digest in rows]

    def current_state(self) -> CatalogState:
        execute = self._connection.execute
        countries = execute(
            "SELECT country_id::text, alpha2, alpha3, numeric_code, region_id::text, "
            "subregion_id::text, calling_code, status, replacement_country_id::text "
            "FROM reference.country ORDER BY country_id"
        ).fetchall()
        names = execute(
            "SELECT country_id::text, locale_id::text, name, official_name "
            "FROM reference.country_locale ORDER BY country_id, locale_id"
        ).fetchall()
        flags = execute(
            "SELECT country_id::text, asset_path, sha256, exception_reason "
            "FROM reference.country_flag ORDER BY country_id"
        ).fetchall()
        history = execute(HISTORICAL_CODES).fetchall()
        historical: list[tuple[CodeKind, str, str]] = [
            (_kind(kind), code, country_id) for kind, code, country_id in history
        ]
        return CatalogState(
            countries=tuple(CountryRecord(*row) for row in countries),
            names=tuple(NameRecord(*row) for row in names),
            flags=tuple(FlagRecord(*row) for row in flags),
            historical_codes=tuple(historical),
        )

    def locale_catalog(self) -> LocaleCatalog:
        row = self._connection.execute(
            "SELECT max(snapshot_version) FROM reference.locale_snapshot"
        ).fetchone()
        locales = self._connection.execute(
            "SELECT locale_id::text, code, status FROM reference.locale ORDER BY code"
        ).fetchall()
        return LocaleCatalog(
            None if row is None else row[0], tuple(LocaleInfo(*item) for item in locales)
        )

    def region_catalog(self) -> RegionCatalog:
        execute = self._connection.execute
        versions = [
            row[0]
            for row in execute(
                "SELECT snapshot_version FROM reference.region_snapshot ORDER BY snapshot_version"
            ).fetchall()
        ]
        regions = execute(
            "SELECT region_id::text, status FROM reference.region ORDER BY region_id"
        ).fetchall()
        subregions = execute(
            "SELECT subregion_id::text, region_id::text, status FROM reference.subregion "
            "ORDER BY subregion_id"
        ).fetchall()
        return RegionCatalog(
            max(versions) if versions else None,
            frozenset(versions),
            tuple(RegionInfo(*row) for row in regions),
            tuple(SubregionInfo(*row) for row in subregions),
        )


_KINDS: dict[str, CodeKind] = {
    "alpha2": "alpha2",
    "alpha3": "alpha3",
    "numeric_code": "numeric_code",
}


def _kind(value: str) -> CodeKind:
    return _KINDS[value]


class PostgresCountryTransaction(PostgresCatalogView):
    def insert_snapshot(
        self,
        document: Mapping[str, Any],
        locale_snapshot_version: int,
        region_current_snapshot_version: int,
        policy_version: int,
    ) -> None:
        self._connection.execute(
            "INSERT INTO reference.country_snapshot (snapshot_version, content_digest, "
            "locale_snapshot_version, region_snapshot_version, region_current_snapshot_version, "
            "required_locales_version, provenance, artifact) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [
                document["snapshot_version"],
                document["content_digest"],
                locale_snapshot_version,
                document["region_snapshot_version"],
                region_current_snapshot_version,
                policy_version,
                Jsonb(document["provenance"]),
                Jsonb(document),
            ],
        )

    def insert_countries(self, countries: Sequence[CountryRecord], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.country (country_id, alpha2, alpha3, numeric_code, "
                "region_id, subregion_id, calling_code, status, replacement_country_id, "
                "first_snapshot_version, codes_snapshot_version, last_changed_snapshot_version) "
                "VALUES (%s::uuid, %s, %s, %s, %s::uuid, %s::uuid, %s, %s, %s::uuid, %s, %s, %s)",
                [
                    (
                        c.country_id,
                        c.alpha2,
                        c.alpha3,
                        c.numeric_code,
                        c.region_id,
                        c.subregion_id,
                        c.calling_code,
                        c.status,
                        c.replacement_country_id,
                        version,
                        version,
                        version,
                    )
                    for c in countries
                ],
            )

    def update_countries(self, countries: Sequence[CountryRecord], version: int) -> None:
        # Los valores de la derecha de SET son los de la fila anterior: la versión de los códigos
        # solo avanza si la tripleta cambia (RF-51).
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE reference.country SET codes_snapshot_version = CASE WHEN "
                "(alpha2, alpha3, numeric_code) IS DISTINCT FROM "
                "(%(alpha2)s::text, %(alpha3)s::text, %(numeric_code)s::text) "
                "THEN %(version)s::bigint ELSE codes_snapshot_version END, "
                "alpha2 = %(alpha2)s, alpha3 = %(alpha3)s, numeric_code = %(numeric_code)s, "
                "region_id = %(region_id)s::uuid, subregion_id = %(subregion_id)s::uuid, "
                "calling_code = %(calling_code)s, status = %(status)s, "
                "replacement_country_id = %(replacement)s::uuid, "
                "last_changed_snapshot_version = %(version)s::bigint "
                "WHERE country_id = %(id)s::uuid",
                [
                    {
                        "id": c.country_id,
                        "alpha2": c.alpha2,
                        "alpha3": c.alpha3,
                        "numeric_code": c.numeric_code,
                        "region_id": c.region_id,
                        "subregion_id": c.subregion_id,
                        "calling_code": c.calling_code,
                        "status": c.status,
                        "replacement": c.replacement_country_id,
                        "version": version,
                    }
                    for c in countries
                ],
            )

    def record_recodings(self, recodings: Sequence[Recoding], version: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.country_recoding (country_id, snapshot_version, "
                "previous_alpha2, previous_alpha3, previous_numeric_code, new_alpha2, new_alpha3, "
                "new_numeric_code, provenance) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        r.country_id,
                        version,
                        r.previous.alpha2,
                        r.previous.alpha3,
                        r.previous.numeric_code,
                        r.new.alpha2,
                        r.new.alpha3,
                        r.new.numeric_code,
                        Jsonb(r.provenance),
                    )
                    for r in recodings
                ],
            )

    def insert_names(self, names: Sequence[NameRecord]) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.country_locale (country_id, locale_id, name, official_name) "
                "VALUES (%s::uuid, %s::uuid, %s, %s)",
                [(n.country_id, n.locale_id, n.name, n.official_name) for n in names],
            )

    def update_names(self, names: Sequence[NameRecord]) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE reference.country_locale SET name = %s, official_name = %s "
                "WHERE country_id = %s::uuid AND locale_id = %s::uuid",
                [(n.name, n.official_name, n.country_id, n.locale_id) for n in names],
            )

    def write_flags(
        self, new: Sequence[FlagRecord], updated: Sequence[FlagRecord], version: int
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO reference.country_flag (country_id, asset_path, sha256, "
                "exception_reason, snapshot_version) VALUES (%s::uuid, %s, %s, %s, %s)",
                [(f.country_id, f.asset_path, f.sha256, f.exception_reason, version) for f in new],
            )
            cursor.executemany(
                "UPDATE reference.country_flag SET asset_path = %s, sha256 = %s, "
                "exception_reason = %s, snapshot_version = %s WHERE country_id = %s::uuid",
                [
                    (f.asset_path, f.sha256, f.exception_reason, version, f.country_id)
                    for f in updated
                ],
            )

    def touch_countries(self, country_ids: Sequence[str], version: int) -> None:
        if not country_ids:
            return
        self._connection.execute(
            "UPDATE reference.country SET last_changed_snapshot_version = %s "
            "WHERE country_id = ANY(%s::uuid[])",
            [version, list(country_ids)],
        )

    def check_constraints(self) -> None:
        """Evalúa ahora las constraints diferidas: el estado final completo (RF-44, RF-6)."""
        self._connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
