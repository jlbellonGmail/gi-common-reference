"""L-9: la cadena de conexión no se reproduce en ningún error de los adaptadores de Postgres."""

import traceback
from collections.abc import Callable
from typing import Any

import pytest

from gi_common_reference.locales.domain.errors import InvalidConnectionString, PersistenceError
from gi_common_reference.locales.domain.ports import ReaderUnavailable
from gi_common_reference.locales.infrastructure.conninfo import validate_conninfo
from gi_common_reference.locales.infrastructure.postgres_reader import PostgresLocaleReader
from gi_common_reference.locales.infrastructure.postgres_repository import (
    PostgresLocaleRepository,
)

SECRET = "SECRETPW"
MALFORMED = [SECRET, f"host=h password={SECRET} =x", f"password={SECRET} port"]
UNREACHABLE = f"postgresql://user:{SECRET}@127.0.0.1:1/db?connect_timeout=1"


def everything_printed(error: BaseException) -> str:
    """Mensaje más el traceback completo, tal como lo vería un log."""
    return str(error) + "".join(traceback.format_exception(error))


@pytest.mark.parametrize(
    "conninfo",
    ["postgresql://u:p@localhost:5432/db", "host=localhost dbname=db user=u", "postgresql://x"],
)
def test_valid_connection_strings_are_returned_unchanged(conninfo: str) -> None:
    assert validate_conninfo(conninfo) == conninfo


@pytest.mark.parametrize("conninfo", MALFORMED)
def test_a_malformed_connection_string_is_rejected_without_echoing_it(conninfo: str) -> None:
    with pytest.raises(InvalidConnectionString) as raised:
        validate_conninfo(conninfo)
    assert SECRET not in everything_printed(raised.value)


@pytest.mark.parametrize("adapter", [PostgresLocaleReader, PostgresLocaleRepository])
@pytest.mark.parametrize("conninfo", MALFORMED)
def test_adapters_refuse_a_malformed_connection_string_when_built(
    adapter: Callable[[str], Any], conninfo: str
) -> None:
    with pytest.raises(InvalidConnectionString) as raised:
        adapter(conninfo)
    assert SECRET not in everything_printed(raised.value)


def test_driver_errors_of_the_repository_become_persistence_errors_without_the_driver_text() -> (
    None
):
    repository = PostgresLocaleRepository(UNREACHABLE)
    with pytest.raises(PersistenceError) as raised, repository.transaction():
        pytest.fail("no debería conectar")
    printed = everything_printed(raised.value)
    assert SECRET not in printed and "127.0.0.1" not in printed
    assert "Error" in str(raised.value) or "Timeout" in str(raised.value)


def test_an_unreachable_database_is_reader_unavailable_without_the_driver_text() -> None:
    reader = PostgresLocaleReader(UNREACHABLE)
    with pytest.raises(ReaderUnavailable) as raised, reader.session():
        pytest.fail("no debería conectar")
    assert SECRET not in str(raised.value) and "127.0.0.1" not in str(raised.value)


# --- T11 (hallazgo L-A): todo error del driver al conectar es `ReaderUnavailable`, sin su texto ---

# `ProgrammingError` al conectar (valor de opción inválido), no solo `OperationalError`
BAD_OPTION_VALUES = [
    f"host=127.0.0.1 port=1 password={SECRET} connect_timeout={SECRET}",
    f"host=127.0.0.1 port=1 password={SECRET} connect_timeout=-{SECRET}",
]
HOSTILE = [
    *BAD_OPTION_VALUES,
    f"postgresql://u:{SECRET}@127.0.0.1:1/db?sslmode={SECRET}",
    f"host=127.0.0.1 port=1 password={SECRET} sslmode=bogus connect_timeout=1",
    f"postgresql://u:pa@{SECRET}@127.0.0.1:1/db?connect_timeout=1",  # '@' sin escapar
]


@pytest.mark.parametrize("conninfo", BAD_OPTION_VALUES)
def test_the_driver_raises_a_programming_error_for_these_options(conninfo: str) -> None:
    """Precondición de las pruebas siguientes: el caso no es un `OperationalError`."""
    import psycopg

    with pytest.raises(psycopg.ProgrammingError) as raised:
        psycopg.connect(conninfo)
    assert SECRET in str(raised.value)  # el driver sí cita el valor: por eso se traduce


@pytest.mark.parametrize("conninfo", HOSTILE)
def test_the_reader_translates_every_driver_error_at_connect_time(conninfo: str) -> None:
    with pytest.raises(ReaderUnavailable) as raised, PostgresLocaleReader(conninfo).session():
        pytest.fail("no debería conectar")
    printed = everything_printed(raised.value)
    assert SECRET not in printed and "127.0.0.1" not in printed
    assert str(raised.value).endswith("Error") or "SQLSTATE" in str(raised.value)


def test_the_reader_names_the_error_type_and_nothing_else() -> None:
    conninfo = BAD_OPTION_VALUES[0]
    with pytest.raises(ReaderUnavailable) as raised, PostgresLocaleReader(conninfo).session():
        pytest.fail("no debería conectar")
    assert str(raised.value) == "ProgrammingError"
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
