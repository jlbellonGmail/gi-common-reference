"""Errores con mensaje seguro: nunca reproducen la cadena de conexión ni el texto del driver."""

from gi_common_reference.locales.domain.errors import (
    InvalidConnectionString,
    describe_error,
)


class WithSqlstate(Exception):
    sqlstate = "28P01"


class WithoutSqlstate(Exception):
    sqlstate = None


class WithOddSqlstate(Exception):
    sqlstate = 28


def test_describe_error_reports_the_type_and_the_sqlstate_but_never_the_text() -> None:
    error = WithSqlstate('password authentication failed for "u:SECRETPW@host"')
    assert describe_error(error) == "WithSqlstate (SQLSTATE 28P01)"
    assert "SECRETPW" not in describe_error(error)


def test_describe_error_without_a_sqlstate_is_just_the_type() -> None:
    assert describe_error(WithoutSqlstate("host=h password=SECRETPW")) == "WithoutSqlstate"
    assert describe_error(WithOddSqlstate("x")) == "WithOddSqlstate"
    assert describe_error(ValueError("SECRETPW")) == "ValueError"


def test_invalid_connection_string_has_a_fixed_message() -> None:
    assert "SECRETPW" not in str(InvalidConnectionString())
    assert str(InvalidConnectionString()) == str(InvalidConnectionString())
