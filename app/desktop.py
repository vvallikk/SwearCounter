"""Оконный режим: страница управления в окне приложения и значок в трее.

Сервер (uvicorn) работает в фоновом потоке, окно (pywebview, WebView2) — в главном.
Закрытие окна прячет его в трей; программа завершается пунктом «Выход».
"""

import ctypes
import json
import logging
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from socket import socket

import uvicorn
from fastapi import FastAPI

from . import SUPPORT_LINKS, __version__, i18n
from .paths import ICON_FILE, WEBVIEW_DIR
from .updater import Updater

TITLE = i18n.TITLES[i18n.RU]
MUTEX_NAME = "Local\\SwearCounter"
ERROR_ALREADY_EXISTS = 183
MB_ICONERROR = 0x10
MB_ICONINFORMATION = 0x40
CREATE_NO_WINDOW = 0x08000000
SERVER_START_TIMEOUT = 30.0
SERVER_STOP_TIMEOUT = 10.0
API_TIMEOUT = 5.0

log = logging.getLogger(__name__)


@contextmanager
def single_instance(name: str = MUTEX_NAME) -> Iterator[bool]:
    """True, если это первый запущенный экземпляр (именованный mutex Windows)."""
    if sys.platform != "win32":
        with _lock_file(name) as first:
            yield first
        return
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


@contextmanager
def _lock_file(name: str) -> Iterator[bool]:
    """Замена mutex в macOS и Linux: блокировка файла снимается сама, даже если процесс упал."""
    import fcntl

    path = Path(tempfile.gettempdir()) / f"{re.sub(r'\W', '_', name)}.lock"
    try:
        file = path.open("a")
    except OSError:
        yield True  # файл не открылся — не мешаем запуску
        return
    try:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
        else:
            yield True
    finally:
        file.close()


def message_box(text: str, icon: int = MB_ICONINFORMATION, title: str = TITLE) -> None:
    if sys.platform != "win32":
        print(f"{title}: {text}", file=sys.stderr)
        return
    ctypes.windll.user32.MessageBoxW(None, text, title, icon)


@dataclass(frozen=True)
class Urls:
    port: int

    @property
    def control(self) -> str:
        return f"http://localhost:{self.port}/control/"

    @property
    def overlay(self) -> str:
        return f"http://localhost:{self.port}/overlay/"

    def api(self, path: str) -> str:
        return f"http://localhost:{self.port}{path}"


def post_api(url: str, body: dict | None = None) -> dict:
    """Команда своему серверу из трея: так она проходит те же проверки, что и из окна."""
    data = json.dumps(body or {}).encode()
    request = urllib.request.Request(url, data, {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:  # noqa: S310 только localhost
        return json.loads(response.read())


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


def run(
    app: FastAPI,
    sock: socket,
    notice: str | None = None,
    updater: Updater | None = None,
    hidden: bool = False,
    language: Callable[[], str] = lambda: i18n.RU,
) -> None:
    """hidden: окно не показывать (запуск с Windows), программа ждёт в трее.
    language: текущий язык интерфейса (см. i18n.py) — для трея и уведомлений."""
    import pystray
    import webview
    from PIL import Image

    urls = Urls(sock.getsockname()[1])
    server = ServerThread(app, sock)
    if not server.start():
        server.stop()
        raise SystemExit("Сервер не запустился, подробности — в swearcounter.log.")

    def tr(text: str) -> str:
        return i18n.tr(text, language())

    def label(text: str) -> Callable:
        # pystray вызывает функцию при каждой перестройке меню: пункты следуют за языком.
        return lambda item: tr(text)

    def notify(text: str) -> None:
        icon.notify(text, i18n.title(language()))

    title = f"{i18n.title(language())} v{__version__}"
    window = webview.create_window(
        title, urls.control, width=960, height=860, min_size=(480, 480), hidden=hidden
    )
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

    def open_support() -> None:
        # Раскрываем блок «Поддержать» в окне: там все способы и QR-коды.
        show()
        window.evaluate_js("window.openSupport && window.openSupport()")

    def copy_overlay() -> None:
        copy_to_clipboard(urls.overlay)
        notify(tr("Адрес оверлея скопирован: {}").format(urls.overlay))

    def is_paused(item=None) -> bool:
        return app.state.hub.paused

    def toggle_pause() -> None:
        try:
            post_api(urls.api("/api/pause"), {"paused": not is_paused()})
        except OSError as e:
            log.error("Не удалось переключить паузу: %s", e)

    def quit_app() -> None:
        quitting.set()
        icon.stop()
        window.destroy()

    def check_updates() -> None:
        status = updater.check_threadsafe()
        if status == "none":
            notify(tr("У вас последняя версия: v{}").format(__version__))
        elif status == "error":
            notify(updater.error or tr("Не удалось проверить обновления"))
        # О найденном обновлении сообщает on_update_found.

    def on_update_found(version: str) -> None:
        if updater.forced:
            show()
            notify(tr("Нужно обязательное обновление до v{}: без него программа не работает.").format(version))
        else:
            notify(tr("Доступна версия v{}. Установить — на странице управления.").format(version))

    if updater is not None:
        updater.on_found = on_update_found
        updater.quit = quit_app

    window.events.closing += on_closing
    icon = pystray.Icon(
        "SwearCounter",
        Image.open(ICON_FILE),
        title,
        menu=pystray.Menu(
            pystray.MenuItem(label("Открыть"), show, default=True),
            pystray.MenuItem(label("Пауза распознавания"), toggle_pause, checked=is_paused),
            pystray.MenuItem(label("Скопировать адрес оверлея"), copy_overlay),
            pystray.MenuItem(label("Открыть в браузере"), lambda: webbrowser.open(urls.control)),
            pystray.MenuItem(label("Проверить обновления"), check_updates, visible=updater is not None),
            pystray.MenuItem(label("Поддержать автора"), open_support, visible=bool(SUPPORT_LINKS)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(label("Выход"), quit_app),
        ),
    )
    icon.run_detached()

    def on_language_changed() -> None:
        # Вызывается сервером, когда язык переключили на странице управления.
        title = f"{i18n.title(language())} v{__version__}"
        try:
            icon.title = title
            icon.update_menu()
            window.set_title(title)
        except Exception as e:  # окно могло уже закрыться при выходе
            log.warning("Не удалось сменить язык окна и трея: %s", e)

    app.state.on_ui_language = on_language_changed

    def on_started() -> None:
        if notice:
            notify(notice)
        elif hidden:
            notify(tr("Счётчик матов запущен и работает в трее. Нажмите на значок, чтобы открыть окно."))

    try:
        # private_mode=False и свой storage_path: тема и выборы страницы управления сохраняются.
        webview.start(on_started, private_mode=False, storage_path=str(WEBVIEW_DIR))
    finally:
        quitting.set()
        icon.stop()
        server.stop()
