"""L-9 contra Postgres real: solo se traducen los errores del driver, y sin su texto."""

import pytest

from gi_common_reference.locales.domain.errors import PersistenceError
from gi_common_reference.locales.infrastructure.postgres_repository import (
    PostgresLocaleRepository,
)


class Boom(Exception):
    pass


def test_a_driver_error_inside_the_transaction_becomes_a_persistence_error(
    database_url: str,
) -> None:
    repository = PostgresLocaleRepository(database_url)
    with pytest.raises(PersistenceError) as raised, repository.transaction() as tx:
        tx._connection.execute("SELECT * FROM reference.no_such_table")
    assert str(raised.value) == "UndefinedTable (SQLSTATE 42P01)"
    assert "no_such_table" not in str(raised.value)


def test_errors_that_are_not_from_the_driver_keep_their_type_and_message(
    database_url: str,
) -> None:
    repository = PostgresLocaleRepository(database_url)
    with pytest.raises(Boom, match="del caso de uso"), repository.transaction():
        raise Boom("del caso de uso")


def test_a_driver_error_rolls_the_transaction_back(database_url: str) -> None:
    from tests.fixtures.snapshots import iw_scenario

    v1, _ = iw_scenario()
    repository = PostgresLocaleRepository(database_url)
    with pytest.raises(PersistenceError), repository.transaction() as tx:
        tx.insert_snapshot(v1)
        tx._connection.execute("SELECT * FROM reference.no_such_table")
    with PostgresLocaleRepository(database_url).transaction() as tx:
        assert tx.history() == []
