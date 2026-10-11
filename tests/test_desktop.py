"""Оконный режим без окна: один экземпляр, адреса и сервер в фоновом потоке."""

import socket
import urllib.request
import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

from app import desktop
from app.desktop import ServerThread, Urls, single_instance
from app.main import PORT, Prepared


def _mutex_name() -> str:
    return f"Local\\SwearCounterTest-{uuid.uuid4().hex}"


def test_single_instance_blocks_second_and_frees_after_exit():
    name = _mutex_name()
    with single_instance(name) as first:
        assert first
        with single_instance(name) as second:
            assert not second
    with single_instance(name) as again:
        assert again


def test_urls():
    urls = Urls(8766)
    assert urls.control == "http://localhost:8766/control/"
    assert urls.overlay == "http://localhost:8766/overlay/"


def _bound_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    return sock


def test_port_notice_only_when_main_port_busy():
    with _bound_socket() as sock:
        prepared = Prepared(FastAPI(), sock, count=0, model_missing=False)
        assert prepared.port != PORT
        assert str(prepared.port) in prepared.port_notice


def test_server_thread_serves_and_stops():
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    sock = _bound_socket()
    port = sock.getsockname()[1]
    server = ServerThread(app, sock)
    assert server.start(timeout=10)
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=5) as resp:
        assert resp.status == 200
    server.stop(timeout=10)
    assert not server.thread.is_alive()


def test_server_thread_reports_failed_start():
    @asynccontextmanager
    async def lifespan(app):
        raise RuntimeError("startup failed")
        yield

    app = FastAPI(lifespan=lifespan)

    sock = _bound_socket()
    server = ServerThread(app, sock)
    assert not server.start(timeout=10)
    server.stop(timeout=10)


def test_port_notice_in_english(settings):
    from app import i18n

    settings.set(i18n.SETTING, i18n.EN)
    with _bound_socket() as sock:
        prepared = Prepared(FastAPI(), sock, count=0, model_missing=False, settings=settings)
        assert prepared.port_notice.startswith(f"Port {PORT} is busy")


def test_lock_file_on_unix():
    """Вне Windows вместо mutex — блокировка файла; второй экземпляр её не получает."""
    pytest.importorskip("fcntl")
    name = _mutex_name()
    with desktop._lock_file(name) as first:
        assert first
        with desktop._lock_file(name) as second:
            assert not second
    with desktop._lock_file(name) as again:
        assert again
