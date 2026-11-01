"""Entorno de Alembic: solo modo online, SQL plano, historial en el schema propio `reference`.

La URL sale de `sqlalchemy.url` o, si no está, de `REFERENCE_MIGRATION_DATABASE_URL`: el rol dueño
del schema. Es una variable distinta de las que usan la CLI (`REFERENCE_DATABASE_URL`, rol
`reference_loader`) y la API (`REFERENCE_READER_DATABASE_URL`, rol `reference_reader`).
"""

import os

from alembic import context
from sqlalchemy import Connection, create_engine, text

SCHEMA = "reference"
MIGRATION_DATABASE_URL = "REFERENCE_MIGRATION_DATABASE_URL"


def database_url() -> str:
    url = context.config.get_main_option("sqlalchemy.url") or os.environ.get(MIGRATION_DATABASE_URL)
    if not url:
        raise RuntimeError(f"falta la variable de entorno {MIGRATION_DATABASE_URL}")
    # SQLAlchemy usaría psycopg2 con `postgresql://`; el proyecto usa psycopg 3.
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def describe_error(error: BaseException) -> str:
    """Tipo del error del driver y su SQLSTATE; nunca su texto, que puede citar la conexión."""
    original = getattr(error, "orig", error)  # SQLAlchemy envuelve el error de psycopg
    sqlstate = getattr(original, "sqlstate", None)
    name = type(original).__name__
    return f"{name} (SQLSTATE {sqlstate})" if isinstance(sqlstate, str) else name


def connect() -> Connection:
    """Los errores de conexión salen sin texto del driver ni causa encadenada: con una contraseña
    mal escapada citan un fragmento de la credencial del rol dueño. Los errores de las propias
    migraciones (SQL, constraints) no pasan por aquí y se informan completos."""
    url = database_url()
    try:
        return create_engine(url).connect()
    except Exception as error:
        raise RuntimeError(
            f"no se pudo conectar para migrar ({MIGRATION_DATABASE_URL}): {describe_error(error)}"
        ) from None


def run_migrations_online() -> None:
    connection = connect()
    engine = connection.engine
    with connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.commit()
        context.configure(connection=connection, version_table_schema=SCHEMA)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Las migraciones de gi-common-reference solo se ejecutan online")
run_migrations_online()
