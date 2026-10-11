"""Процесс ожидания (`--watch`): запускает программу или напоминает о ней, когда
запустился OBS или началась трансляция.

Работает только пока сама программа закрыта: без сервера, окна и микрофона.
Как только программа запущена (её mutex занят), процесс ожидания выходит; программа
при выходе запускает его снова (app/autostart.py).
"""

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

from . import autostart
from .obs import ObsClient, ObsError, stream_started
from .paths import ICON_FILE, SETTINGS_FILE
from .settings import Settings

WATCH_MUTEX = "Local\\SwearCounterWatch"
OBS_PROCESSES = ("obs64.exe", "obs32.exe", "obs.exe")
POLL_INTERVAL = 2.0
OBS_RETRY = 5.0  # пауза перед новым подключением к obs-websocket
OBS_RECV_TIMEOUT = 1.0
# После запуска программы она несколько секунд стартует; не запускаем её второй раз.
LAUNCH_COOLDOWN = 60.0

OBS_TEXT = "OBS запущен. Нажмите, чтобы запустить счётчик матов."
STREAM_TEXT = "Трансляция началась, а счётчик матов не запущен. Нажмите, чтобы запустить."

log = logging.getLogger(__name__)


# --- Windows: процессы и mutex программы ---

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
SYNCHRONIZE = 0x00100000


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel32


def process_names() -> set[str]:
    """Имена exe всех запущенных процессов (в нижнем регистре)."""
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return set()
    names = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.lower())
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return names


def obs_running() -> bool:
    return not process_names().isdisjoint(OBS_PROCESSES)


def mutex_exists(name: str) -> bool:
    kernel32 = _kernel32()
    handle = kernel32.OpenMutexW(SYNCHRONIZE, False, name)
    if handle:
        kernel32.CloseHandle(handle)
    return bool(handle)


def app_running() -> bool:
    from .desktop import MUTEX_NAME

    return mutex_exists(MUTEX_NAME)


# --- Трансляция: события obs-websocket ---


class StreamWatch:
    """Фоновое подключение к OBS: on_started при каждом начале трансляции.

    report_active: если при первом подключении трансляция уже идёт, это тоже начало
    (OBS мог начать её сам при запуске, раньше, чем мы подключились).
    """

    def __init__(self, settings: Callable[[], Settings], on_started: Callable[[], None], report_active: bool):
        self._settings = settings
        self._on_started = on_started
        self._report_active = report_active
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="obs-stream", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            settings = self._settings()
            try:
                with ObsClient(autostart.obs_port(settings), autostart.obs_password(settings)) as client:
                    log.info("Подключился к OBS")
                    active = client.streaming()
                    if active and self._report_active:
                        self._on_started()
                    self._report_active = False  # переподключение посреди трансляции — не начало
                    for message in client.messages(OBS_RECV_TIMEOUT):
                        if self._stop.is_set():
                            return
                        if message is not None and stream_started(message):
                            self._on_started()
            except ObsError as e:
                log.info("OBS: %s", e)
            self._stop.wait(OBS_RETRY)


# --- Решения: когда запускать и когда напоминать ---


class Watcher:
    def __init__(
        self,
        settings: Callable[[], Settings],
        obs_running: Callable[[], bool],
        app_running: Callable[[], bool],
        launch: Callable[[], None],
        notify: Callable[[str], None],
        stream_watch: Callable[[bool], StreamWatch] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._settings = settings
        self._obs_running = obs_running
        self._app_running = app_running
        self._launch = launch
        self._notify = notify
        self._make_stream_watch = stream_watch or (lambda report: StreamWatch(settings, self.on_stream_started, report))
        self._clock = clock
        self._obs_seen: bool | None = None  # None — ещё не смотрели
        self._stream: StreamWatch | None = None
        self._launched_at: float | None = None
        self._lock = threading.Lock()

    def tick(self) -> bool:
        """Одна проверка; False — процессу ожидания пора выйти."""
        if self._app_running():
            log.info("Программа запущена, ожидание OBS не нужно")
            return False
        settings = self._settings()
        if not autostart.watch_needed(settings):
            log.info("Реакция на OBS выключена")
            return False
        running = self._obs_running()
        first = self._obs_seen is None
        if running and self._obs_seen is False:
            log.info("Запущен OBS")
            self._act(autostart.trigger(settings, "autostart_obs"), OBS_TEXT)
        self._obs_seen = running
        # OBS, который уже работал при старте ожидания (программу закрыли посреди
        # трансляции), не повод запускать её снова: ждём следующего запуска или трансляции.
        want_stream = running and autostart.trigger(settings, "autostart_stream") != autostart.TRIGGER_OFF
        if want_stream and self._stream is None:
            self._stream = self._make_stream_watch(not first)
            self._stream.start()
        elif not want_stream and self._stream is not None:
            self._stream.stop()
            self._stream = None
        return True

    def on_stream_started(self) -> None:
        log.info("Началась трансляция")
        if self._app_running():
            return
        self._act(autostart.trigger(self._settings(), "autostart_stream"), STREAM_TEXT)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream = None

    def launch(self) -> None:
        """Запуск программы: по настройке или по нажатию на уведомление."""
        with self._lock:
            now = self._clock()
            if self._launched_at is not None and now - self._launched_at < LAUNCH_COOLDOWN:
                return
            self._launched_at = now
        log.info("Запускаю программу")
        self._launch()

    def _act(self, mode: str, text: str) -> None:
        if mode == autostart.TRIGGER_LAUNCH:
            self.launch()
        elif mode == autostart.TRIGGER_NOTIFY:
            with self._lock:
                recently = self._launched_at is not None and self._clock() - self._launched_at < LAUNCH_COOLDOWN
            if not recently:
                self._notify(text)


# --- Уведомление в трее ---


NIN_BALLOONUSERCLICK = 0x0405  # WM_USER + 5: нажали на само уведомление


class Tray:
    """Значок появляется только вместе с уведомлением; нажатие на любое из них запускает программу."""

    def __init__(self, on_launch: Callable[[], None]):
        self._on_launch = on_launch
        self._icon = None

    def _launch(self) -> None:
        self._icon.visible = False
        self._on_launch()

    def _ensure_icon(self):
        if self._icon is not None:
            return self._icon
        import pystray
        from PIL import Image
        from pystray import _win32

        from .desktop import TITLE

        icon = pystray.Icon(
            "SwearCounterWatch",
            Image.open(ICON_FILE),
            TITLE,
            menu=pystray.Menu(
                pystray.MenuItem("Запустить счётчик матов", self._launch, default=True),
                pystray.MenuItem("Скрыть", lambda: setattr(icon, "visible", False)),
            ),
        )
        # pystray не сообщает о нажатии на само уведомление: подменяем обработчик
        # сообщений значка (закрытая часть pystray, версия закреплена в requirements.txt).
        on_notify = icon._message_handlers[_win32.win32.WM_NOTIFY]

        def handle_notify(wparam, lparam):
            if lparam == NIN_BALLOONUSERCLICK:
                self._launch()
            return on_notify(wparam, lparam)

        icon._message_handlers[_win32.win32.WM_NOTIFY] = handle_notify
        icon.run_detached()
        self._icon = icon
        return icon

    def notify(self, text: str) -> None:
        from .desktop import TITLE

        icon = self._ensure_icon()
        icon.visible = True
        icon.notify(text, TITLE)

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()


def run() -> None:
    """Точка входа `--watch`."""
    from .desktop import single_instance

    with single_instance(WATCH_MUTEX) as first:
        if not first:
            return
        watcher: Watcher | None = None
        tray = Tray(lambda: watcher.launch())
        watcher = Watcher(
            settings=lambda: Settings(SETTINGS_FILE),
            obs_running=obs_running,
            app_running=app_running,
            launch=autostart.spawn,
            notify=tray.notify,
        )
        log.info("Жду запуска OBS")
        try:
            while watcher.tick():
                time.sleep(POLL_INTERVAL)
        finally:
            watcher.stop()
            tray.stop()
