"""Горячие клавиши: разбор сочетаний, API и поток с RegisterHotKey."""

import ctypes
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import hotkeys
from app.hotkeys import ACTIONS, DEFAULTS, HotkeyError, Hotkeys, normalize, parse
from app.server import Hub, create_app
from test_server import FakeRecognizer, SMALL

# Сочетание, которое вряд ли занято на машине разработчика или в CI.
RARE = "Ctrl+Alt+Shift+F24"
windows_only = pytest.mark.skipif(os.name != "nt", reason="RegisterHotKey есть только в Windows")


# --- разбор ---


@pytest.mark.parametrize(
    ("combo", "expected"),
    [
        ("Ctrl+Shift+F9", (hotkeys.MOD_CONTROL | hotkeys.MOD_SHIFT, 0x78)),
        ("Alt+A", (hotkeys.MOD_ALT, 0x41)),
        ("Win+0", (hotkeys.MOD_WIN, 0x30)),
        ("F13", (0, 0x7C)),
        ("NumAdd", (0, 0x6B)),
        ("Pause", (0, 0x13)),
        ("", None),
    ],
)
def test_parse(combo, expected):
    assert parse(combo) == expected


@pytest.mark.parametrize("combo", ["A", "Space", "Ctrl+", "Ctrl+Ctrl+A", "Hyper+A", "Ctrl+Plus", "ctrl+a"])
def test_parse_rejects(combo):
    with pytest.raises(HotkeyError):
        parse(combo)


def test_defaults_are_valid():
    for combo in DEFAULTS.values():
        parse(combo)
    assert DEFAULTS["reset"] == ""  # сброс без клавиши, чтобы не стереть счёт случайно


def test_normalize_fills_defaults_and_drops_unknown():
    assert normalize({"reset": "Ctrl+Alt+R", "other": "F1", "pause": None}) == {
        "increment": DEFAULTS["increment"],
        "pause": "",
        "reset": "Ctrl+Alt+R",
    }


# --- API ---


class FakeHotkeys:
    available = True

    def __init__(self):
        self.on_press = None
        self.failed: list[str] = []
        self.calls: list[tuple] = []
        self.busy: set[str] = set()  # сочетания, «занятые другой программой»

    def start(self, combos):
        self.calls.append(("start", dict(combos)))
        self.apply(combos)

    def apply(self, combos):
        self.calls.append(("apply", dict(combos)))
        self.failed = [action for action, combo in combos.items() if combo in self.busy]
        return self.failed

    def stop(self):
        self.calls.append(("stop",))


@pytest.fixture
def listener():
    return FakeHotkeys()


@pytest.fixture
def make_client(counter, models_dir, settings, tmp_path, fake_sd):
    from app.sound import Sound

    (models_dir / SMALL).mkdir()

    def make(listener=None):
        hub = Hub(counter)
        app = create_app(hub, FakeRecognizer(models_dir / SMALL), settings, Sound(settings, tmp_path / "s"),
                         hotkey_listener=listener)
        return hub, TestClient(app, base_url="http://localhost")

    return make


def test_unavailable_without_listener(make_client):
    _, client = make_client()
    with client:
        assert client.get("/api/hotkeys").json() == {"available": False, "hotkeys": DEFAULTS, "failed": []}


def test_listener_started_with_saved_combos(make_client, listener, settings):
    settings.set("hotkeys", {"reset": "Ctrl+Alt+R"})
    _, client = make_client(listener)
    with client:
        assert listener.calls[0] == ("start", {**DEFAULTS, "reset": "Ctrl+Alt+R"})
    assert listener.calls[-1] == ("stop",)


def test_set_hotkey_saves_and_applies(make_client, listener, settings):
    _, client = make_client(listener)
    with client:
        state = client.post("/api/hotkeys", json={"action": "reset", "combo": "Ctrl+Alt+R"}).json()
    assert state["hotkeys"]["reset"] == "Ctrl+Alt+R"
    assert settings.get("hotkeys")["reset"] == "Ctrl+Alt+R"
    assert listener.calls[-2] == ("apply", {**DEFAULTS, "reset": "Ctrl+Alt+R"})


def test_clear_hotkey(make_client, listener):
    _, client = make_client(listener)
    with client:
        state = client.post("/api/hotkeys", json={"action": "increment", "combo": ""}).json()
    assert state["hotkeys"]["increment"] == ""


def test_busy_combo_reported(make_client, listener):
    listener.busy = {"Ctrl+Alt+R"}
    _, client = make_client(listener)
    with client:
        state = client.post("/api/hotkeys", json={"action": "reset", "combo": "Ctrl+Alt+R"}).json()
        assert state["failed"] == ["reset"]
        assert client.get("/api/hotkeys").json()["failed"] == ["reset"]


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"action": "explode", "combo": "F13"}, "Неизвестное действие"),
        ({"action": "reset", "combo": "R"}, "Добавьте Ctrl"),
        ({"action": "reset", "combo": DEFAULTS["increment"]}, "уже назначено"),
    ],
)
def test_set_hotkey_rejects(make_client, listener, settings, body, detail):
    _, client = make_client(listener)
    with client:
        response = client.post("/api/hotkeys", json=body)
    assert response.status_code == 400
    assert detail in response.json()["detail"]
    assert settings.get("hotkeys") is None


def test_hotkey_actions_change_counter_and_pause(make_client, listener):
    hub, client = make_client(listener)
    with client:
        for action in ("increment", "increment", "pause"):
            listener.on_press(action).result(timeout=5)
        assert client.get("/api/state").json() == {"count": 2}
        assert client.get("/api/pause").json() == {"paused": True}
        listener.on_press("pause").result(timeout=5)
        listener.on_press("reset").result(timeout=5)
        assert client.get("/api/state").json() == {"count": 0}
        assert client.get("/api/pause").json() == {"paused": False}


# --- настоящий RegisterHotKey ---


def post_hotkey_message(listener: Hotkeys, action: str) -> None:
    """Имитирует нажатие: то же сообщение WM_HOTKEY, что присылает Windows."""
    ctypes.windll.user32.PostThreadMessageW(listener._thread_id, Hotkeys.WM_HOTKEY, ACTIONS.index(action) + 1, 0)


@windows_only
def test_real_listener_dispatches_presses():
    pressed = []
    done = threading.Event()

    def on_press(action):
        pressed.append(action)
        done.set()

    listener = Hotkeys(on_press)
    listener.start({"increment": RARE, "pause": "", "reset": ""})
    try:
        assert listener.failed == []
        post_hotkey_message(listener, "increment")
        assert done.wait(5)
        assert pressed == ["increment"]
    finally:
        listener.stop()
    assert not listener._thread.is_alive()


@windows_only
def test_real_listener_reports_busy_combo():
    first = Hotkeys(lambda action: None)
    second = Hotkeys(lambda action: None)
    first.start({"increment": RARE})
    try:
        second.start({})
        assert second.apply({"increment": "", "pause": RARE, "reset": ""}) == ["pause"]
        first.apply({})  # освободили — теперь второму достаётся
        deadline = time.monotonic() + 5
        while second.apply({"increment": "", "pause": RARE, "reset": ""}) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert second.failed == []
    finally:
        first.stop()
        second.stop()
