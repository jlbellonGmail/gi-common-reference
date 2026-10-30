"""T1: el fixture de sesión entrega un Postgres real en testcontainers."""

import psycopg


def test_postgres_connection_works(postgres_url: str) -> None:
    with psycopg.connect(postgres_url) as conn:
        row = conn.execute("SELECT 1").fetchone()
    assert row == (1,)
