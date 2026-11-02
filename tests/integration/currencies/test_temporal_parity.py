"""T5: el dominio y PostgreSQL implementan la misma semántica `[inicio, fin)` (RF-44, RF-45)."""

from datetime import date

import psycopg
import pytest

from gi_common_reference.currencies.domain.temporal import Period
from tests.fixtures.temporal_vectors import CONTAINS_VECTORS, OVERLAP_VECTORS, Bound


@pytest.mark.parametrize(("a0", "a1", "b0", "b1", "expected"), OVERLAP_VECTORS)
def test_sql_overlap_matches_the_domain(
    conn: psycopg.Connection, a0: Bound, a1: Bound, b0: Bound, b1: Bound, expected: bool
) -> None:
    row = conn.execute(
        "SELECT daterange(%s, %s, '[)') && daterange(%s, %s, '[)')", [a0, a1, b0, b1]
    ).fetchone()
    assert row == (expected,)
    assert Period(a0, a1).overlaps(Period(b0, b1)) is expected


@pytest.mark.parametrize(("start", "end", "day", "expected"), CONTAINS_VECTORS)
def test_sql_containment_matches_the_domain(
    conn: psycopg.Connection, start: Bound, end: Bound, day: date, expected: bool
) -> None:
    row = conn.execute("SELECT daterange(%s, %s, '[)') @> %s::date", [start, end, day]).fetchone()
    assert row == (expected,)
    assert Period(start, end).contains(day) is expected
