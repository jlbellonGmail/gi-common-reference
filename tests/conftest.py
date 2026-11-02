import socket
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from types import TracebackType
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from testcontainers.community.postgres import PostgresContainer

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("anon", "authenticated", "reference_reader", "reference_loader")
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("postgresql://", "postgresql+psycopg://"))
    return config


def with_database(url: str, name: str) -> str:
    return url.rsplit("/", 1)[0] + "/" + name


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Postgres real y descartable; solo se conecta a localhost (RNF-2)."""
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def postgres_with_roles(postgres_url: str) -> str:
    """Simula Supabase: roles de la API y privilegios por defecto a anon/authenticated/PUBLIC."""
    with psycopg.connect(postgres_url, autocommit=True) as conn:
        for role in ROLES:
            conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
    # Los privilegios por defecto son por base: se fijan en template1 para que los hereden
    # las bases de cada prueba.
    with psycopg.connect(with_database(postgres_url, "template1"), autocommit=True) as conn:
        conn.execute("ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO anon, authenticated, PUBLIC")
    return postgres_url


@pytest.fixture
def database_factory(postgres_with_roles: str) -> Iterator[Callable[[], str]]:
    """Crea bases nuevas con la migración aplicada hasta head; las elimina al terminar."""
    created: list[str] = []

    def create() -> str:
        name = f"t_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        created.append(name)
        url = with_database(postgres_with_roles, name)
        command.upgrade(alembic_config(url), "head")
        return url

    yield create

    with psycopg.connect(postgres_with_roles, autocommit=True) as admin:
        for name in created:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def database_url(database_factory: Callable[[], str]) -> str:
    """Base nueva con la migración aplicada hasta head."""
    return database_factory()


@pytest.fixture
def conn(database_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(database_url, autocommit=True) as connection:
        yield connection


class NetworkGuard:
    """Registra y bloquea todo uso de red de Python hacia hosts que no sean locales.

    Las conexiones a Postgres las hace libpq (código C) y no pasan por aquí: lo que este guard
    detecta es cualquier acceso de red desde Python, p. ej. descargar el registro IANA.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.blocked: list[tuple[str, object]] = []
        self.allowed: list[tuple[str, object]] = []
        self._monkeypatch = monkeypatch

    def _check(self, name: str, host: object) -> None:
        if host in LOCAL_HOSTS:
            self.allowed.append((name, host))
            return
        self.blocked.append((name, host))
        raise AssertionError(f"acceso de red no permitido: {name}({host!r})")

    def __enter__(self) -> "NetworkGuard":
        original_getaddrinfo = socket.getaddrinfo
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex

        def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
            self._check("getaddrinfo", host)
            return original_getaddrinfo(host, *args, **kwargs)

        def connect(sock: socket.socket, address: Any) -> Any:
            self._check("connect", address[0] if isinstance(address, tuple) else address)
            return original_connect(sock, address)

        def connect_ex(sock: socket.socket, address: Any) -> Any:
            self._check("connect_ex", address[0] if isinstance(address, tuple) else address)
            return original_connect_ex(sock, address)

        self._monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
        self._monkeypatch.setattr(socket.socket, "connect", connect)
        self._monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._monkeypatch.undo()


@pytest.fixture
def network_guard(monkeypatch: pytest.MonkeyPatch) -> NetworkGuard:
    return NetworkGuard(monkeypatch)
