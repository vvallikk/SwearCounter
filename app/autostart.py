"""Автозапуск: вместе с Windows, при запуске OBS и при начале трансляции.

Запуск с Windows — значение в HKCU\\...\\Run, программа стартует свёрнутой в трей.
Реакцию на OBS даёт фоновый процесс ожидания (`--watch`, см. app/watcher.py): он
работает, только пока сама программа закрыта, без сервера и микрофона. Поэтому
значение в Run одно: либо сама программа (`--autostart`), либо процесс ожидания.
Когда программа закрывается, процесс ожидания запускается снова (spawn_watcher).
"""

import logging
import subprocess
import sys
from pathlib import Path

from .settings import Settings

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "SwearCounter"
AUTOSTART_ARG = "--autostart"
WATCH_ARG = "--watch"

# Что делать, когда запустился OBS или началась трансляция, а программа закрыта.
TRIGGER_OFF = "off"
TRIGGER_NOTIFY = "notify"
TRIGGER_LAUNCH = "launch"
TRIGGER_MODES = (TRIGGER_OFF, TRIGGER_NOTIFY, TRIGGER_LAUNCH)

DEFAULT_OBS_PORT = 4455  # порт сервера WebSocket в OBS по умолчанию

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

ROOT_DIR = Path(__file__).resolve().parent.parent


def windows_enabled(settings: Settings) -> bool:
    return bool(settings.get("autostart_windows", False))


def trigger(settings: Settings, key: str) -> str:
    """Режим для "autostart_obs" или "autostart_stream"; незнакомое значение — выключен."""
    mode = settings.get(key, TRIGGER_OFF)
    return mode if mode in TRIGGER_MODES else TRIGGER_OFF


def obs_port(settings: Settings) -> int:
    port = settings.get("obs_ws_port", DEFAULT_OBS_PORT)
    return port if isinstance(port, int) and 0 < port < 65536 else DEFAULT_OBS_PORT


def obs_password(settings: Settings) -> str:
    password = settings.get("obs_ws_password", "")
    return password if isinstance(password, str) else ""


def watch_needed(settings: Settings) -> bool:
    return any(trigger(settings, key) != TRIGGER_OFF for key in ("autostart_obs", "autostart_stream"))


def state(settings: Settings) -> dict:
    return {
        "windows": windows_enabled(settings),
        "obs": trigger(settings, "autostart_obs"),
        "stream": trigger(settings, "autostart_stream"),
        "obs_port": obs_port(settings),
        # Сам пароль странице не отдаём: только есть ли он.
        "has_password": bool(obs_password(settings)),
        "available": sys.platform == "win32",
    }


def launch_command(*args: str) -> list[str]:
    """Команда запуска программы: exe или pythonw с swearcounter.py из исходников."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    python = Path(sys.executable)
    # pythonw — без чёрного окна консоли; в venv он лежит рядом с python.exe.
    pythonw = python.with_name("pythonw.exe")
    return [str(pythonw if pythonw.exists() else python), str(ROOT_DIR / "swearcounter.py"), *args]


def run_args(settings: Settings) -> list[str] | None:
    """Ключ для значения в Run: программа целиком, процесс ожидания или ничего."""
    if windows_enabled(settings):
        return [AUTOSTART_ARG]
    if watch_needed(settings):
        return [WATCH_ARG]
    return None


class RunKey:
    """Значение SwearCounter в HKCU\\...\\Run (без прав администратора)."""

    def read(self) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, RUN_VALUE)
        except FileNotFoundError:
            return None
        return value if isinstance(value, str) else None

    def write(self, command: str) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, command)

    def delete(self) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            pass


def default_run_key() -> RunKey | None:
    """Реестр есть только в Windows (тесты подменяют эту функцию)."""
    return RunKey() if sys.platform == "win32" else None


def sync(settings: Settings, run_key: RunKey | None = None) -> None:
    """Приводит значение в Run к настройкам (и к текущему пути exe, если папку перенесли).

    Бросает OSError, если реестр недоступен.
    """
    run_key = run_key or default_run_key()
    if run_key is None:
        return
    args = run_args(settings)
    current = run_key.read()
    if args is None:
        if current is not None:
            run_key.delete()
            log.info("Автозапуск выключен")
        return
    command = subprocess.list2cmdline(launch_command(*args))
    if current != command:
        run_key.write(command)
        log.info("Автозапуск: %s", command)


def spawn(*args: str) -> None:
    """Запускает программу отдельным процессом, который переживёт текущий."""
    subprocess.Popen(
        launch_command(*args),
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


def spawn_watcher(settings: Settings) -> None:
    """После выхода из программы: снова ждать OBS, если это включено."""
    if sys.platform != "win32" or not watch_needed(settings):
        return
    try:
        spawn(WATCH_ARG)
    except OSError as e:
        log.error("Не удалось запустить ожидание OBS: %s", e)
