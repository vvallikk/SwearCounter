"""Выбор порта: если основной занят, сервер запускается на следующем свободном."""

import socket
from contextlib import ExitStack

import pytest

from app.main import PORT, PORT_ATTEMPTS, bind_socket

HOST = "127.0.0.1"


def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, port))
        except OSError:
            return False
        return True


def free_ports(count: int) -> int:
    """Первый из count подряд свободных портов вне диапазона работающего приложения."""
    busy_range = range(PORT, PORT + PORT_ATTEMPTS)
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((HOST, 0))
            first = sock.getsockname()[1]
        ports = range(first, first + count)
        if ports[-1] < 65536 and not set(ports) & set(busy_range) and all(map(_is_free, ports)):
            return first
    pytest.skip("не нашлось подряд свободных портов")


def occupy(stack: ExitStack, port: int) -> None:
    sock = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
    sock.bind((HOST, port))
    sock.listen()


def test_binds_first_port_when_free():
    first = free_ports(3)
    with bind_socket(HOST, first, 3) as sock:
        assert sock.getsockname() == (HOST, first)


def test_falls_back_to_next_free_port():
    first = free_ports(3)
    with ExitStack() as stack:
        occupy(stack, first)
        with bind_socket(HOST, first, 3) as sock:
            assert sock.getsockname()[1] == first + 1


def test_skips_several_busy_ports():
    first = free_ports(3)
    with ExitStack() as stack:
        occupy(stack, first)
        occupy(stack, first + 1)
        with bind_socket(HOST, first, 3) as sock:
            assert sock.getsockname()[1] == first + 2


def test_exits_when_all_ports_busy():
    first = free_ports(2)
    with ExitStack() as stack:
        occupy(stack, first)
        occupy(stack, first + 1)
        with pytest.raises(SystemExit) as exc:
            bind_socket(HOST, first, 2)
    assert f"{first}–{first + 1}" in str(exc.value.code)


def test_port_taken_on_all_interfaces_counts_as_busy():
    first = free_ports(2)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as other:
        # Другая программа слушает порт на всех адресах, а не только на 127.0.0.1.
        other.bind(("0.0.0.0", first))
        other.listen()
        sock = bind_socket(HOST, first, 2)
        try:
            assert sock.getsockname()[1] == first + 1
        finally:
            sock.close()
