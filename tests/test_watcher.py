"""Процесс ожидания: когда запускать программу, когда напоминать и когда выходить."""

import sys

import pytest

from app import watcher
from app.watcher import LAUNCH_COOLDOWN, OBS_TEXT, STREAM_TEXT, Watcher


class FakeStreamWatch:
    def __init__(self, report_active: bool):
        self.report_active = report_active
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class World:
    """Состояние «системы», которое видит процесс ожидания."""

    def __init__(self, settings):
        self.settings = settings
        self.obs = False
        self.app = False
        self.now = 0.0
        self.launches = 0
        self.notices: list[str] = []
        self.streams: list[FakeStreamWatch] = []

    def stream_watch(self, report_active):
        stream = FakeStreamWatch(report_active)
        self.streams.append(stream)
        return stream

    def watcher(self) -> Watcher:
        return Watcher(
            settings=lambda: self.settings,
            obs_running=lambda: self.obs,
            app_running=lambda: self.app,
            launch=self.launch,
            notify=self.notices.append,
            stream_watch=self.stream_watch,
            clock=lambda: self.now,
        )

    def launch(self):
        self.launches += 1


@pytest.fixture
def world(settings):
    return World(settings)


def test_exits_when_disabled(world):
    assert world.watcher().tick() is False


def test_exits_when_app_running(world):
    world.settings.set("autostart_obs", "launch")
    world.app = True
    assert world.watcher().tick() is False


def test_launches_when_obs_starts(world):
    world.settings.set("autostart_obs", "launch")
    w = world.watcher()
    assert w.tick()
    assert world.launches == 0
    world.obs = True
    assert w.tick()
    assert world.launches == 1
    assert w.tick()  # OBS всё ещё работает: второй раз не запускаем
    assert world.launches == 1


def test_notifies_when_obs_starts(world):
    world.settings.set("autostart_obs", "notify")
    w = world.watcher()
    w.tick()
    world.obs = True
    w.tick()
    assert world.notices == [OBS_TEXT]
    assert world.launches == 0


def test_obs_already_running_at_start_is_ignored(world):
    # Программу закрыли при открытом OBS: не запускать её тут же снова.
    world.settings.set("autostart_obs", "launch")
    world.obs = True
    w = world.watcher()
    w.tick()
    w.tick()
    assert world.launches == 0
    world.obs = False
    w.tick()
    world.obs = True
    w.tick()
    assert world.launches == 1


def test_stream_watch_follows_obs(world):
    world.settings.set("autostart_stream", "notify")
    w = world.watcher()
    w.tick()
    assert world.streams == []
    world.obs = True
    w.tick()
    (stream,) = world.streams
    assert stream.started and stream.report_active
    w.tick()
    assert len(world.streams) == 1
    world.obs = False
    w.tick()
    assert stream.stopped


def test_stream_watch_ignores_running_stream_when_obs_was_open(world):
    world.settings.set("autostart_stream", "launch")
    world.obs = True
    world.watcher().tick()
    assert world.streams[0].report_active is False


def test_stream_started_actions(world):
    world.settings.set("autostart_stream", "notify")
    w = world.watcher()
    w.on_stream_started()
    assert world.notices == [STREAM_TEXT]
    world.settings.set("autostart_stream", "launch")
    w.on_stream_started()
    assert world.launches == 1


def test_stream_started_while_app_running_does_nothing(world):
    world.settings.set("autostart_stream", "launch")
    world.app = True
    world.watcher().on_stream_started()
    assert world.launches == 0


def test_no_second_launch_while_app_starts(world):
    # OBS запустил программу, а через секунду OBS сам начал трансляцию: программа ещё стартует.
    world.settings.set("autostart_obs", "launch")
    world.settings.set("autostart_stream", "notify")
    w = world.watcher()
    w.tick()
    world.obs = True
    w.tick()
    world.now = 1.0
    w.on_stream_started()
    assert world.launches == 1
    assert world.notices == []
    world.now = LAUNCH_COOLDOWN + 2
    w.launch()
    assert world.launches == 2


@pytest.mark.skipif(sys.platform != "win32", reason="процессы и mutex Windows")
def test_windows_process_and_mutex_helpers():
    import os
    import uuid

    from app.desktop import single_instance

    assert os.path.basename(sys.executable).lower() in watcher.process_names()
    name = f"Local\\SwearCounterTest-{uuid.uuid4().hex}"
    assert not watcher.mutex_exists(name)
    with single_instance(name):
        assert watcher.mutex_exists(name)
