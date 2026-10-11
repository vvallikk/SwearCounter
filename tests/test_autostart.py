"""Автозапуск: что записывается в HKCU\\...\\Run и какой командой."""

import subprocess
import sys

import pytest

from app import autostart


def test_defaults_off(settings):
    assert autostart.state(settings) == {
        "windows": False,
        "obs": "off",
        "stream": "off",
        "obs_port": 4455,
        "has_password": False,
        "available": sys.platform == "win32",
    }
    assert autostart.run_args(settings) is None


def test_garbage_in_settings_means_defaults(settings):
    settings.set("autostart_obs", "explode")
    settings.set("obs_ws_port", "4455")
    settings.set("obs_ws_password", 123)
    assert autostart.trigger(settings, "autostart_obs") == "off"
    assert autostart.obs_port(settings) == 4455
    assert autostart.obs_password(settings) == ""


@pytest.mark.parametrize(
    ("windows", "obs", "stream", "expected"),
    [
        (True, "off", "off", ["--autostart"]),
        # Программа целиком сама запустит ожидание, когда её закроют.
        (True, "launch", "notify", ["--autostart"]),
        (False, "notify", "off", ["--watch"]),
        (False, "off", "launch", ["--watch"]),
        (False, "off", "off", None),
    ],
)
def test_run_args(settings, windows, obs, stream, expected):
    settings.set("autostart_windows", windows)
    settings.set("autostart_obs", obs)
    settings.set("autostart_stream", stream)
    assert autostart.run_args(settings) == expected


def test_launch_command_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Games\SwearCounter\SwearCounter.exe")
    assert autostart.launch_command("--watch") == [r"C:\Games\SwearCounter\SwearCounter.exe", "--watch"]


def test_launch_command_from_sources_prefers_pythonw(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    (tmp_path / "python.exe").touch()
    (tmp_path / "pythonw.exe").touch()
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    command = autostart.launch_command("--autostart")
    assert command == [str(tmp_path / "pythonw.exe"), str(autostart.ROOT_DIR / "swearcounter.py"), "--autostart"]


def test_sync_writes_updates_and_deletes(settings, run_key, monkeypatch):
    monkeypatch.setattr(autostart, "launch_command", lambda *args: [r"C:\Program Files\SC\SwearCounter.exe", *args])
    settings.set("autostart_windows", True)
    autostart.sync(settings)
    assert run_key.value == r'"C:\Program Files\SC\SwearCounter.exe" --autostart'

    settings.set("autostart_windows", False)
    settings.set("autostart_stream", "notify")
    autostart.sync(settings)
    assert run_key.value == r'"C:\Program Files\SC\SwearCounter.exe" --watch'

    settings.set("autostart_stream", "off")
    autostart.sync(settings)
    assert run_key.value is None


def test_sync_rewrites_moved_exe(settings, run_key, monkeypatch):
    run_key.value = r"C:\Old\SwearCounter.exe --autostart"
    monkeypatch.setattr(autostart, "launch_command", lambda *args: [r"D:\New\SwearCounter.exe", *args])
    settings.set("autostart_windows", True)
    autostart.sync(settings)
    assert run_key.value == r"D:\New\SwearCounter.exe --autostart"


def test_spawn_watcher_only_when_needed(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kwargs: calls.append(command))
    autostart.spawn_watcher(settings)
    assert calls == []
    settings.set("autostart_obs", "launch")
    autostart.spawn_watcher(settings)
    assert len(calls) == 1 and calls[0][-1] == "--watch"


@pytest.mark.skipif(sys.platform != "win32", reason="реестр есть только в Windows")
def test_real_run_key_reads_without_writing():
    # Только чтение: тест не должен трогать настоящий автозапуск.
    value = autostart.RunKey().read()
    assert value is None or isinstance(value, str)
