"""Validación de la cadena de conexión sin reproducirla en ningún error (misma regla que Locale)."""

import psycopg
from psycopg.conninfo import conninfo_to_dict

from gi_common_reference.currencies.domain.errors import InvalidConnectionString


def validate_conninfo(conninfo: str) -> str:
    """Devuelve `conninfo` si libpq la entiende; si no, `InvalidConnectionString` sin su texto.

    El error de sintaxis de libpq cita el fragmento ofensor, que puede ser una contraseña: se
    descarta junto con su contexto (`from None`).
    """
    try:
        conninfo_to_dict(conninfo)
    except psycopg.ProgrammingError:
        raise InvalidConnectionString() from None
    return conninfo
