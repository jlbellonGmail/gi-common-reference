"""T7: el lector de Postgres devuelve lo mismo que el lector en memoria sobre los mismos datos.

El lector en memoria es la referencia de la semántica (consultas, orden, filtros); aquí se
comprueba, contra Postgres real y con el rol `reference_reader`, que el SQL la respeta y que la
conversión es reproducible contra versiones históricas (RF-20, RF-24, RF-25, RF-29 a RF-37, RNF-6,
CL-10, CL-11, CA-5, CA-7).
"""

from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from gi_common_reference.bootstrap import (
    postgres_repository,
    postgres_units_repository,
    units_required_locales,
    units_ucum_table,
)
from gi_common_reference.locales.application.incorporate import (
    incorporate_snapshot as incorporate_locales,
)
from gi_common_reference.units.application.conversions import CatalogCache, ConversionService
from gi_common_reference.units.application.incorporate import Outcome, incorporate_snapshot
from gi_common_reference.units.application.queries import (
    get_catalog_version,
    get_quantity_kind,
    get_unit,
    list_quantity_kinds,
    list_units,
)
from gi_common_reference.units.domain.conversion import (
    ConversionRejection,
    ConversionRequest,
    ConversionSuccess,
)
from gi_common_reference.units.domain.ports import ReaderUnavailable
from gi_common_reference.units.infrastructure.postgres_reader import PostgresUnitsReader
from tests.fixtures.regions import FR, locale_snapshot
from tests.fixtures.units import EN, ES, build_snapshot, kind_id, unit_id
from tests.fixtures.units_reader import InMemoryUnitsReader
from tests.fixtures.units_variants import SACK_ID, sack_snapshot

MISSING = "00000000-0000-4000-8000-000000000000"
LOCALES = (None, EN, ES, FR)


def incorporate(url: str, document: dict[str, Any]) -> None:
    result = incorporate_snapshot(
        document, postgres_units_repository(url), units_required_locales(), units_ucum_table()
    )
    assert result.outcome is Outcome.INCORPORATED, result.violations


@pytest.fixture
def prepared(database_factory: Callable[[], str]) -> str:
    url = database_factory()
    incorporate_locales(locale_snapshot(1), postgres_repository(url))
    return url


@pytest.fixture
def loaded(prepared: str) -> Iterator[tuple[str, InMemoryUnitsReader]]:
    """Base con v1 (con saco) y v2 (otro factor y `oz` retirada) y su lector de referencia."""
    first = sack_snapshot(1, factor="60")
    second = sack_snapshot(
        2, factor="50", retired=("oz",), inactive_links=(("temperature_difference", "degF"),)
    )
    for document in (first, second):
        incorporate(prepared, document)
    reference = InMemoryUnitsReader(first, second)
    reference.locale_ids = {EN, ES, FR}
    yield make_conninfo(prepared, options="-c role=reference_reader"), reference


def both(loaded: tuple[str, InMemoryUnitsReader]) -> tuple[Any, Any]:
    return PostgresUnitsReader(loaded[0]), loaded[1]


def sack_to_kg(value: str = "2") -> ConversionRequest:
    return ConversionRequest(kind_id("mass"), value, SACK_ID, unit_id("kg"))


# --- consultas: SQL = memoria


def test_the_kind_queries_match_the_reference(loaded: tuple[str, InMemoryUnitsReader]) -> None:
    real, reference = both(loaded)
    for include_inactive in (False, True):
        for code in (None, "mass", "temperature", "nope"):
            for locale in LOCALES:
                assert list_quantity_kinds(
                    real, include_inactive, code, locale
                ) == list_quantity_kinds(reference, include_inactive, code, locale)
    for kind in reference.kinds.values():
        for locale in LOCALES:
            assert get_quantity_kind(real, kind.quantity_kind_id, locale) == get_quantity_kind(
                reference, kind.quantity_kind_id, locale
            )
    assert get_quantity_kind(real, MISSING).error == "quantity_kind_not_found"
    assert get_quantity_kind(real, MISSING.upper(), "x").error == "invalid_locale_id"


@pytest.mark.parametrize("include_inactive", [False, True])
@pytest.mark.parametrize("locale", LOCALES)
def test_the_unit_lists_match_the_reference_for_every_filter(
    loaded: tuple[str, InMemoryUnitsReader], include_inactive: bool, locale: str | None
) -> None:
    real, reference = both(loaded)
    kinds = [None, *reference.kinds]
    for kind in kinds:
        assert list_units(real, kind, None, None, include_inactive, locale) == list_units(
            reference, kind, None, None, include_inactive, locale
        )
    for ucum, unece in (
        ("kg", None),
        ("[lb_av]", None),
        ("KG", None),
        (None, "KGM"),
        (None, "kgm"),
    ):
        assert list_units(real, None, ucum, unece, include_inactive, locale) == list_units(
            reference, None, ucum, unece, include_inactive, locale
        )
    assert list_units(real, kind_id("mass"), "kg", "GRM", include_inactive, locale) == list_units(
        reference, kind_id("mass"), "kg", "GRM", include_inactive, locale
    )


def test_every_unit_by_id_matches_the_reference_in_every_locale(
    loaded: tuple[str, InMemoryUnitsReader],
) -> None:
    real, reference = both(loaded)
    for unit in reference.units.values():
        for locale in LOCALES:
            assert get_unit(real, unit.unit_id, locale) == get_unit(reference, unit.unit_id, locale)
    assert get_unit(real, MISSING).error == "unit_not_found"
    assert get_unit(real, MISSING, MISSING).error == "unknown_locale"
    assert get_unit(real, "x").error == "invalid_unit_id"


def test_the_default_unit_list_is_binary_ordered_without_the_retired(
    loaded: tuple[str, InMemoryUnitsReader],
) -> None:
    listing = list_units(PostgresUnitsReader(loaded[0]))
    keys = [(v.record.symbol.encode(), v.record.unit_id) for v in listing.items]
    symbols = [v.record.symbol for v in listing.items]
    assert keys == sorted(keys) and "oz" not in symbols and "sack" in symbols
    assert listing.snapshot_version == 2
    assert list_units(PostgresUnitsReader(loaded[0]), quantity_kind_id=MISSING).error == (
        "quantity_kind_not_found"
    )


def test_the_nulls_names_and_plurals_round_trip_through_sql(
    loaded: tuple[str, InMemoryUnitsReader],
) -> None:
    real = PostgresUnitsReader(loaded[0])
    sack = get_unit(real, SACK_ID, ES).item
    assert sack is not None and sack.record.ucum_code is None and sack.record.unece_code is None
    assert (sack.name, sack.plural) == ("saco", None)
    lb = get_unit(real, unit_id("lb"), EN).item
    assert lb is not None and (lb.name, lb.plural) == ("pound", "pounds")


# --- catálogo vacío, versión y privilegios


def test_the_catalog_version_is_the_latest_incorporated(
    loaded: tuple[str, InMemoryUnitsReader],
) -> None:
    assert get_catalog_version(PostgresUnitsReader(loaded[0])) == 2


def test_an_empty_database_has_no_version_and_no_error(database_factory: Callable[[], str]) -> None:
    empty = PostgresUnitsReader(database_factory())
    assert get_catalog_version(empty) is None
    assert list_units(empty).items == () and list_quantity_kinds(empty).items == ()
    assert get_unit(empty, unit_id("kg")).error == "unit_not_found"
    response = ConversionService(empty, CatalogCache()).convert(sack_to_kg())
    assert isinstance(response.outcome, ConversionRejection)
    assert response.outcome.code == "catalog_version_not_available"
    assert response.snapshot_version is None


def test_the_reader_role_reads_what_the_queries_need_and_writes_nothing(
    loaded: tuple[str, InMemoryUnitsReader],
) -> None:
    with psycopg.connect(loaded[0], autocommit=True) as conn:
        for table in (
            "unit",
            "quantity_kind",
            "quantity_kind_unit",
            "unit_locale",
            "quantity_kind_locale",
            "unit_snapshot",
            "locale",
        ):
            conn.execute(f"SELECT 1 FROM reference.{table} LIMIT 1")
        for statement in (
            "UPDATE reference.unit SET status = 'inactive'",
            "UPDATE reference.quantity_kind_unit SET factor = '2'",
            "DELETE FROM reference.unit_snapshot",
            "INSERT INTO reference.unit_snapshot (snapshot_version) VALUES (99)",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)


# --- conversión: versión vigente, explícita, histórica


def test_the_current_and_the_historical_version_give_different_stable_results(
    loaded: tuple[str, InMemoryUnitsReader],
) -> None:
    """RNF-2, RNF-6, CL-10, CL-11: v1 sigue dando lo mismo después de publicar v2."""
    real = PostgresUnitsReader(loaded[0])
    expected_v1 = ConversionSuccess("120", True, unit_id("kg"), kind_id("mass"), 1)
    expected_v2 = ConversionSuccess("100", True, unit_id("kg"), kind_id("mass"), 2)
    for service in (ConversionService(real, CatalogCache()), ConversionService(real)):
        v1 = service.convert(sack_to_kg(), catalog_version=1)
        current = service.convert(sack_to_kg())
        explicit_v2 = service.convert(sack_to_kg(), catalog_version=2)
        assert v1.outcome == expected_v1 and repr(v1.outcome) == repr(expected_v1)
        assert current.outcome == expected_v2 == explicit_v2.outcome
        assert v1.snapshot_version == current.snapshot_version == 2
    # el mismo resultado desde el lector en memoria (artefacto = documento incorporado)
    memory = ConversionService(loaded[1], CatalogCache())
    assert memory.convert(sack_to_kg(), catalog_version=1).outcome == expected_v1


def test_the_historical_result_is_identical_before_and_after_a_later_version(
    prepared: str,
) -> None:
    reader_url = make_conninfo(prepared, options="-c role=reference_reader")
    real = PostgresUnitsReader(reader_url)
    incorporate(prepared, sack_snapshot(1, factor="60"))
    before = ConversionService(real).convert(sack_to_kg(), catalog_version=1)
    incorporate(prepared, sack_snapshot(2, factor="50", retired=("oz",)))
    after = ConversionService(real).convert(sack_to_kg(), catalog_version=1)
    assert repr(before.outcome) == repr(after.outcome)
    assert before.snapshot_version == 1 and after.snapshot_version == 2
    assert isinstance(after.outcome, ConversionSuccess) and after.outcome.result == "120"
    assert ConversionService(real).convert(sack_to_kg()).outcome == ConversionSuccess(
        "100", True, unit_id("kg"), kind_id("mass"), 2
    )


def test_a_retired_unit_is_rejected_now_but_converts_with_the_historical_version(
    loaded: tuple[str, InMemoryUnitsReader],
) -> None:
    service = ConversionService(PostgresUnitsReader(loaded[0]))
    oz = ConversionRequest(kind_id("mass"), "16", unit_id("oz"), unit_id("kg"))
    now = service.convert(oz)
    assert isinstance(now.outcome, ConversionRejection) and now.outcome.code == "inactive_unit"
    then = service.convert(oz, catalog_version=1)
    assert then.outcome == ConversionSuccess("0.45359237", True, unit_id("kg"), kind_id("mass"), 1)


def test_unavailable_versions_and_invalid_versions(
    loaded: tuple[str, InMemoryUnitsReader],
) -> None:
    service = ConversionService(PostgresUnitsReader(loaded[0]))
    for version in (3, 99):
        outcome = service.convert(sack_to_kg(), catalog_version=version).outcome
        assert isinstance(outcome, ConversionRejection)
        assert outcome.code == "catalog_version_not_available"
    outcome = service.convert(sack_to_kg(), catalog_version=0).outcome
    assert isinstance(outcome, ConversionRejection) and outcome.code == "invalid_catalog_version"


def test_a_skipped_version_is_not_available(prepared: str) -> None:
    incorporate(prepared, build_snapshot(1))
    incorporate(prepared, build_snapshot(5))
    service = ConversionService(PostgresUnitsReader(prepared))
    request = ConversionRequest(kind_id("mass"), "1", unit_id("kg"), unit_id("g"))
    gap = service.convert(request, catalog_version=3).outcome
    assert isinstance(gap, ConversionRejection) and gap.code == "catalog_version_not_available"
    assert isinstance(service.convert(request, catalog_version=5).outcome, ConversionSuccess)


def test_the_artifact_is_read_once_per_version_through_sql(
    loaded: tuple[str, InMemoryUnitsReader], monkeypatch: pytest.MonkeyPatch
) -> None:
    from gi_common_reference.units.infrastructure import postgres_reader as module

    reads: list[int] = []
    original = module.PostgresUnitsSession.artifact

    def counting(self: Any, snapshot_version: int) -> Any:
        reads.append(snapshot_version)
        return original(self, snapshot_version)

    monkeypatch.setattr(module.PostgresUnitsSession, "artifact", counting)
    service = ConversionService(PostgresUnitsReader(loaded[0]))
    for _ in range(3):
        service.convert(sack_to_kg())
        service.convert(sack_to_kg(), catalog_version=1)
    assert sorted(reads) == [1, 2]


def test_a_database_that_cannot_be_reached_is_a_technical_error() -> None:
    """RF-37: ni «no encontrado» ni error de validación; sin credenciales en el mensaje."""
    unreachable = PostgresUnitsReader("postgresql://u:s3cr3t@127.0.0.1:1/none?connect_timeout=2")
    calls: list[Callable[[], object]] = [
        lambda: list_units(unreachable),
        lambda: list_quantity_kinds(unreachable),
        lambda: get_unit(unreachable, unit_id("kg")),
        lambda: get_catalog_version(unreachable),
        lambda: ConversionService(unreachable).convert(sack_to_kg()),
        lambda: ConversionService(unreachable).convert(sack_to_kg(), catalog_version=1),
    ]
    for call in calls:
        with pytest.raises(ReaderUnavailable) as error:
            call()
        assert "s3cr3t" not in str(error.value)
