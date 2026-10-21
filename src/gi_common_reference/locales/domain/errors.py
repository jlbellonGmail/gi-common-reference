"""Errores de configuración y de persistencia cuyo mensaje es seguro de mostrar.

Ningún mensaje de estas excepciones contiene la cadena de conexión ni fragmentos de ella: las
credenciales no deben llegar a la salida de la CLI ni a los logs.
"""


class SchemaLoadError(RuntimeError):
    """El schema del snapshot que viaja con el paquete no se pudo cargar (instalación incompleta).

    Es un error del entorno, distinto de un archivo de snapshot ilegible o inválido.
    """


class InvalidConnectionString(ValueError):
    """La cadena de conexión no es válida; nunca se reproduce en el mensaje."""

    def __init__(self) -> None:
        super().__init__("la cadena de conexión no es válida (no se muestra por seguridad)")


class PersistenceError(Exception):
    """Falló la base de datos; el mensaje solo identifica el tipo de error y su SQLSTATE."""


def describe_error(error: BaseException) -> str:
    """Tipo de la excepción y, si el driver lo informa, su SQLSTATE; nunca el texto original.

    El texto de un error de conexión puede incluir fragmentos de la cadena de conexión.
    """
    sqlstate = getattr(error, "sqlstate", None)
    name = type(error).__name__
    return f"{name} (SQLSTATE {sqlstate})" if isinstance(sqlstate, str) else name
