"""RNF-2: ninguna suite puede salir a la red; solo se permite localhost."""

import socket

import pytest
from pytest_socket import SocketConnectBlockedError

from tests.conftest import NetworkGuard

# TEST-NET-1 (RFC 5737): no enrutable; sin guard la conexión expira, no se bloquea.
EXTERNAL_HOST = "192.0.2.1"


def test_external_host_connection_is_blocked() -> None:
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection((EXTERNAL_HOST, 80), timeout=1)


def test_guard_records_and_rejects_external_name_resolution(network_guard: NetworkGuard) -> None:
    with network_guard, pytest.raises(AssertionError, match="no permitido"):
        socket.getaddrinfo("www.iana.org", 443)
    assert network_guard.blocked == [("getaddrinfo", "www.iana.org")]


def test_guard_records_and_rejects_external_connections(network_guard: NetworkGuard) -> None:
    client = socket.socket()
    with network_guard, pytest.raises(AssertionError, match="no permitido"):
        client.connect((EXTERNAL_HOST, 80))
    client.close()
    assert network_guard.blocked == [("connect", EXTERNAL_HOST)]


def test_guard_lets_local_hosts_through_and_records_them(network_guard: NetworkGuard) -> None:
    with network_guard:
        socket.getaddrinfo("localhost", 5432)
    assert network_guard.blocked == []
    assert network_guard.allowed == [("getaddrinfo", "localhost")]


def test_guard_is_removed_on_exit(network_guard: NetworkGuard) -> None:
    original = socket.getaddrinfo
    with network_guard:
        assert socket.getaddrinfo is not original
    assert socket.getaddrinfo is original
