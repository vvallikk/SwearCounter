"""Выбор порта: если основной занят, сервер запускается на следующем свободном."""

import logging
import socket
from contextlib import ExitStack

import pytest

from app.main import PORT, PORT_ATTEMPTS, bind_socket, setup_logging

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
        other.bind(("0.0.0.0", first))  # noqa: S104
        other.listen()
        sock = bind_socket(HOST, first, 2)
        try:
            assert sock.getsockname()[1] == first + 1
        finally:
            sock.close()


@pytest.fixture
def restore_logging():
    root, app_log = logging.getLogger(), logging.getLogger("app")
    handlers, level, app_level = root.handlers[:], root.level, app_log.level
    yield
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers[:], root.level = handlers, level
    app_log.setLevel(app_level)


def test_spoken_text_stays_out_of_log_file(tmp_path, restore_logging):
    """Окно программы пишет журнал в файл: распознанный текст (DEBUG) туда не попадает."""
    log_file = tmp_path / "swearcounter.log"
    setup_logging(log_file)
    logging.getLogger("app.profanity").debug("Распознано: %r", "секрет")
    logging.getLogger("app.profanity").info("Фраза: найдено 1")
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = log_file.read_text(encoding="utf-8")
    assert "Фраза: найдено 1" in text and "секрет" not in text


def test_console_mode_shows_spoken_text(restore_logging):
    setup_logging(None)
    assert logging.getLogger("app.profanity").isEnabledFor(logging.DEBUG)
