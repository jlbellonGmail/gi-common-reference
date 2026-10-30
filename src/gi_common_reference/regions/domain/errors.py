"""Errores de configuración y de persistencia cuyo mensaje es seguro de mostrar.

Mismas reglas que `locales` (D12): ningún mensaje contiene la cadena de conexión ni fragmentos de
ella, porque las credenciales no deben llegar a la salida de la CLI ni a los logs.
"""


class SchemaLoadError(RuntimeError):
    """Un recurso que viaja con el paquete (schema, política) no se pudo cargar.

    Es un error del entorno, distinto de un archivo de snapshot ilegible o inválido.
    """


class InvalidConnectionString(ValueError):
    """La cadena de conexión no es válida; nunca se reproduce en el mensaje."""

    def __init__(self) -> None:
        super().__init__("la cadena de conexión no es válida (no se muestra por seguridad)")


class PersistenceError(Exception):
    """Falló la base de datos; el mensaje solo identifica el tipo de error y su SQLSTATE."""


class ConstraintRejected(Exception):
    """La base rechazó el estado final por una constraint (D13): es un rechazo, no una falla.

    `constraint` es el nombre de la constraint (parte del schema, nunca de la conexión) y `foreign`
    indica si es una FK, p. ej. la de un catálogo dependiente ante una reclasificación (RF-35).
    """

    def __init__(self, constraint: str | None, sqlstate: str | None, foreign: bool) -> None:
        super().__init__(f"constraint {constraint or '(sin nombre)'} (SQLSTATE {sqlstate})")
        self.constraint, self.sqlstate, self.foreign = constraint, sqlstate, foreign


def describe_error(error: BaseException) -> str:
    """Tipo de la excepción y, si el driver lo informa, su SQLSTATE; nunca el texto original."""
    sqlstate = getattr(error, "sqlstate", None)
    name = type(error).__name__
    return f"{name} (SQLSTATE {sqlstate})" if isinstance(sqlstate, str) else name
