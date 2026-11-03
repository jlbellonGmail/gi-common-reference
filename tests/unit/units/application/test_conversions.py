"""T7: servicio de conversión con caché por versión (RF-24, RF-25, RF-29 a RF-31, RNF-6, CL-10,
CL-11, CL-14, CL-15, CA-5, CA-7)."""

import threading

import pytest

from gi_common_reference.units.application.conversions import (
    CatalogCache,
    ConversionService,
)
from gi_common_reference.units.domain.conversion import (
    ConversionRejection,
    ConversionRequest,
    ConversionSuccess,
)
from gi_common_reference.units.domain.ports import ReaderUnavailable
from tests.fixtures.units import build_snapshot, kind_id, unit_id
from tests.fixtures.units_reader import InMemoryUnitsReader
from tests.fixtures.units_variants import retired_oz, sack_snapshot


def request(
    value: str = "10", source: str = "lb", target: str = "kg", kind: str | None = "mass"
) -> ConversionRequest:
    return ConversionRequest(
        kind_id(kind) if kind else None, value, unit_id(source), unit_id(target)
    )


def service(reader: InMemoryUnitsReader) -> ConversionService:
    return ConversionService(reader, CatalogCache())


def test_a_conversion_uses_the_current_version_and_reports_the_catalog_version() -> None:
    reader = InMemoryUnitsReader(build_snapshot(3))
    response = service(reader).convert(request())
    assert response.snapshot_version == 3
    assert response.outcome == ConversionSuccess(
        "4.5359237", True, unit_id("kg"), kind_id("mass"), 3
    )


def test_an_explicit_catalog_version_converts_with_that_version() -> None:
    reader = InMemoryUnitsReader(sack_snapshot(1, factor="60"), sack_snapshot(2, factor="50"))
    sack = ConversionRequest(
        kind_id("mass"), "2", "6f0e0000-0000-4000-8000-000000000001", unit_id("kg")
    )
    current = service(reader).convert(sack)
    old = service(reader).convert(sack, catalog_version=1)
    assert isinstance(current.outcome, ConversionSuccess) and current.outcome.result == "100"
    assert isinstance(old.outcome, ConversionSuccess) and old.outcome.result == "120"
    assert (current.outcome.catalog_version, old.outcome.catalog_version) == (2, 1)
    assert old.snapshot_version == 2  # la vigente, no la usada


def test_a_version_that_was_never_incorporated_is_not_available() -> None:
    reader = InMemoryUnitsReader(build_snapshot(3))
    for missing in (1, 2, 4, 99):
        response = service(reader).convert(request(), catalog_version=missing)
        assert isinstance(response.outcome, ConversionRejection)
        assert response.outcome.code == "catalog_version_not_available"
        assert response.snapshot_version == 3


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "1"])
def test_an_invalid_catalog_version_is_rejected(bad: object) -> None:
    response = service(InMemoryUnitsReader(build_snapshot(1))).convert(
        request(),
        catalog_version=bad,  # type: ignore[arg-type]
    )
    assert isinstance(response.outcome, ConversionRejection)
    assert response.outcome.code == "invalid_catalog_version"


def test_an_empty_catalog_has_no_version_available() -> None:
    empty = InMemoryUnitsReader()
    for version in (None, 1):
        response = service(empty).convert(request(), catalog_version=version)
        assert isinstance(response.outcome, ConversionRejection)
        assert response.outcome.code == "catalog_version_not_available"
        assert response.snapshot_version is None
    assert empty.artifact_reads == [] or empty.artifact_reads == [1]


def test_domain_rejections_pass_through_with_their_codes() -> None:
    svc = service(InMemoryUnitsReader(build_snapshot(1)))
    cases = {
        "quantity_kind_required": request(kind=None),
        "invalid_value": request(value="1e3"),
        "incompatible_units": request(source="m"),
        "unit_not_found": ConversionRequest(
            kind_id("mass"), "1", "00000000-0000-4000-8000-000000000000", unit_id("kg")
        ),
    }
    for code, case in cases.items():
        outcome = svc.convert(case).outcome
        assert isinstance(outcome, ConversionRejection) and outcome.code == code


def test_a_retired_unit_is_rejected_now_and_converts_with_the_historical_version() -> None:
    reader = InMemoryUnitsReader(build_snapshot(1), retired_oz(2))
    svc = service(reader)
    now = svc.convert(request(source="oz"))
    assert isinstance(now.outcome, ConversionRejection) and now.outcome.code == "inactive_unit"
    then = svc.convert(request(source="oz"), catalog_version=1)
    assert isinstance(then.outcome, ConversionSuccess)
    assert (then.outcome.result, then.outcome.catalog_version) == ("0.28349523125", 1)


def test_the_artifact_is_read_once_per_version() -> None:
    reader = InMemoryUnitsReader(build_snapshot(1), retired_oz(2))
    svc = service(reader)
    for _ in range(5):
        svc.convert(request())
        svc.convert(request(), catalog_version=1)
        svc.convert(request(), catalog_version=2)
    assert sorted(reader.artifact_reads) == [1, 2]
    assert reader.sessions == 15  # una por solicitud: la versión vigente se consulta siempre


def test_concurrent_requests_load_the_artifact_once() -> None:
    reader = InMemoryUnitsReader(build_snapshot(1))
    svc = service(reader)
    gate = threading.Barrier(8)
    results: list[object] = []

    def worker() -> None:
        gate.wait(timeout=10)
        results.append(svc.convert(request()).outcome)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(results) == 8 and len(set(map(repr, results))) == 1
    assert reader.artifact_reads == [1]


def test_a_cache_shared_between_services_keeps_each_version_separate() -> None:
    cache = CatalogCache()
    first = InMemoryUnitsReader(sack_snapshot(1, factor="60"))
    ConversionService(first, cache).convert(request())
    second = InMemoryUnitsReader(sack_snapshot(1, factor="60"))
    ConversionService(second, cache).convert(request())
    assert first.artifact_reads == [1] and second.artifact_reads == []


def test_a_technical_failure_is_not_a_rejection() -> None:
    reader = InMemoryUnitsReader(build_snapshot(1))
    reader.unavailable = True
    with pytest.raises(ReaderUnavailable):
        service(reader).convert(request())
    with pytest.raises(ReaderUnavailable):
        service(reader).convert(request(), catalog_version=1)


def test_a_failed_load_is_not_cached() -> None:
    reader = InMemoryUnitsReader(build_snapshot(1))
    svc = service(reader)
    reader.unavailable = True
    with pytest.raises(ReaderUnavailable):
        svc.convert(request())
    reader.unavailable = False
    assert isinstance(svc.convert(request()).outcome, ConversionSuccess)


def test_the_service_never_writes() -> None:
    reader = InMemoryUnitsReader(build_snapshot(1))
    before = (dict(reader.units), list(reader.associations), reader.version)
    service(reader).convert(request())
    assert (dict(reader.units), list(reader.associations), reader.version) == before
