"""Оконный режим: страница управления в окне приложения и значок в трее.

Сервер (uvicorn) работает в фоновом потоке, окно (pywebview, WebView2) — в главном.
Закрытие окна прячет его в трей; программа завершается пунктом «Выход».
"""

import ctypes
import logging
import subprocess
import threading
import time
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from socket import socket

import uvicorn
from fastapi import FastAPI

from . import SUPPORT_URL, __version__
from .paths import ICON_FILE, WEBVIEW_DIR
from .updater import Updater

TITLE = "Счётчик матов"
MUTEX_NAME = "Local\\SwearCounter"
ERROR_ALREADY_EXISTS = 183
MB_ICONERROR = 0x10
MB_ICONINFORMATION = 0x40
CREATE_NO_WINDOW = 0x08000000
SERVER_START_TIMEOUT = 30.0
SERVER_STOP_TIMEOUT = 10.0

log = logging.getLogger(__name__)


@contextmanager
def single_instance(name: str = MUTEX_NAME) -> Iterator[bool]:
    """True, если это первый запущенный экземпляр (именованный mutex Windows)."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateMutexW(None, False, name)
    first = bool(handle) and ctypes.get_last_error() != ERROR_ALREADY_EXISTS
    try:
        # Mutex не создался вовсе — не мешаем запуску.
        yield first or not handle
    finally:
        if handle:
            kernel32.CloseHandle(handle)


def message_box(text: str, icon: int = MB_ICONINFORMATION) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, TITLE, icon)


@dataclass(frozen=True)
class Urls:
    port: int

    @property
    def control(self) -> str:
        return f"http://localhost:{self.port}/control/"

    @property
    def overlay(self) -> str:
        return f"http://localhost:{self.port}/overlay/"


class ServerThread:
    """uvicorn в фоновом потоке на уже занятом сокете."""

    def __init__(self, app: FastAPI, sock: socket):
        # log_config=None: логи uvicorn идут в общий лог, а не в консоль, которой у exe нет.
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
        self.thread = threading.Thread(target=self._run, args=(sock,), name="server", daemon=True)

    def _run(self, sock: socket) -> None:
        try:
            self.server.run(sockets=[sock])
        except SystemExit as e:
            # uvicorn выходит через sys.exit, если не удался запуск (например, lifespan).
            log.error("Сервер остановился с кодом %s", e.code)

    def start(self, timeout: float = SERVER_START_TIMEOUT) -> bool:
        """Запускает сервер и ждёт, пока он начнёт принимать запросы."""
        self.thread.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                return False
            time.sleep(0.05)
        return True

    def stop(self, timeout: float = SERVER_STOP_TIMEOUT) -> None:
        self.server.should_exit = True
        self.thread.join(timeout)
        if self.thread.is_alive():
            log.warning("Сервер не остановился за %.0f с", timeout)


def copy_to_clipboard(text: str) -> None:
    subprocess.run(["clip"], input=text.encode("ascii"), check=False, creationflags=CREATE_NO_WINDOW)


def run(app: FastAPI, sock: socket, notice: str | None = None, updater: Updater | None = None) -> None:
    import pystray
    import webview
    from PIL import Image

    urls = Urls(sock.getsockname()[1])
    server = ServerThread(app, sock)
    if not server.start():
        server.stop()
        raise SystemExit("Сервер не запустился, подробности — в swearcounter.log.")

    title = f"{TITLE} v{__version__}"
    window = webview.create_window(title, urls.control, width=960, height=860, min_size=(480, 480))
    quitting = threading.Event()

    def on_closing() -> bool:
        if quitting.is_set():
            return True
        # Прячем из отдельного потока: обработчик closing выполняется, пока окно ждёт ответа.
        threading.Thread(target=window.hide, daemon=True).start()
        return False

    def show() -> None:
        window.show()
        window.restore()

    def copy_overlay() -> None:
        copy_to_clipboard(urls.overlay)
        icon.notify(f"Адрес оверлея скопирован: {urls.overlay}", TITLE)

    def quit_app() -> None:
        quitting.set()
        icon.stop()
        window.destroy()

    def check_updates() -> None:
        status = updater.check_threadsafe()
        if status == "none":
            icon.notify(f"У вас последняя версия: v{__version__}", TITLE)
        elif status == "error":
            icon.notify(updater.error or "Не удалось проверить обновления", TITLE)
        # О найденном обновлении сообщает on_update_found.

    def on_update_found(version: str) -> None:
        if updater.forced:
            show()
            icon.notify(f"Нужно обязательное обновление до v{version}: без него программа не работает.", TITLE)
        else:
            icon.notify(f"Доступна версия v{version}. Установить — на странице управления.", TITLE)

    if updater is not None:
        updater.on_found = on_update_found
        updater.quit = quit_app

    window.events.closing += on_closing
    icon = pystray.Icon(
        "SwearCounter",
        Image.open(ICON_FILE),
        title,
        menu=pystray.Menu(
            pystray.MenuItem("Открыть", show, default=True),
            pystray.MenuItem("Скопировать адрес оверлея", copy_overlay),
            pystray.MenuItem("Открыть в браузере", lambda: webbrowser.open(urls.control)),
            pystray.MenuItem("Проверить обновления", check_updates, visible=updater is not None),
            pystray.MenuItem(
                "Поддержать автора", lambda: webbrowser.open(SUPPORT_URL), visible=bool(SUPPORT_URL)
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", quit_app),
        ),
    )
    icon.run_detached()

    def on_started() -> None:
        if notice:
            icon.notify(notice, TITLE)

    try:
        # private_mode=False и свой storage_path: тема и выборы страницы управления сохраняются.
        webview.start(on_started, private_mode=False, storage_path=str(WEBVIEW_DIR))
    finally:
        quitting.set()
        icon.stop()
        server.stop()
