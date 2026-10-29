"""Временные события (app/events.py): окно дат, выключатель, оформление и звуки Хеллоуина."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.events import DATE_ENV, EVENTS, HALLOWEEN, Events
from app.server import create_app
from app.settings import Settings
from app.sound import Sound
from conftest import skip_greeting
from test_server import hub, recognizer  # noqa: F401  фикстуры сервера

ROOT = Path(__file__).resolve().parent.parent
HALLOWEEN_DAY = date(2026, 10, 31)


@pytest.fixture
def events(settings):
    return Events(settings)


@pytest.fixture
def halloween(event_day):
    event_day(HALLOWEEN_DAY)


@pytest.mark.parametrize(
    "day, active",
    [
        (date(2026, 10, 14), False),
        (date(2026, 10, 15), True),
        (date(2026, 10, 31), True),
        (date(2026, 11, 1), True),  # последний день включительно
        (date(2026, 11, 2), False),
        (date(2027, 10, 20), True),  # каждый год
        (date(2026, 6, 15), False),
    ],
)
def test_halloween_window_ends_november_first_inclusive(events, event_day, day, active):
    event_day(day)
    assert (events.active_ids() == ["halloween"]) is active


def test_state_shows_running_event_with_last_day(events, halloween):
    assert events.state() == {
        "active": ["halloween"],
        "events": [{"id": "halloween", "title": "Хеллоуин", "until": "2026-11-01", "enabled": True}],
    }


def test_state_is_empty_outside_window(events):
    assert events.state() == {"active": [], "events": []}


def test_event_can_be_switched_off_and_back(events, halloween, settings_path):
    events.set_enabled("halloween", False)
    assert events.active_ids() == []
    assert events.state()["events"][0]["enabled"] is False  # выключенное, но идущее — видно
    assert Settings(settings_path).get("events_off") == ["halloween"]
    events.set_enabled("halloween", True)
    assert events.active_ids() == ["halloween"]


def test_event_switched_off_in_settings_file(settings_path, halloween):
    Settings(settings_path).set("events_off", ["halloween"])
    assert Events(Settings(settings_path)).active_ids() == []


def test_unknown_event_rejected(events):
    with pytest.raises(KeyError):
        events.set_enabled("christmas", False)


def test_event_preset_available_only_during_event(events, event_day):
    assert events.preset_available("classic")
    assert not events.preset_available("halloween")
    event_day(HALLOWEEN_DAY)
    assert events.preset_available("halloween")


@pytest.mark.parametrize(
    "before, count, cursed",
    [(12, 13, True), (13, 14, False), (25, 26, True), (11, 14, True), (0, 1, False), (38, 39, True)],
)
def test_curse_on_every_thirteenth(events, halloween, before, count, cursed):
    assert events.curse(before, count) is cursed


def test_no_curse_outside_event(events):
    assert events.curse(12, 13) is False


def test_date_override_from_environment(monkeypatch):
    from app import events as module

    monkeypatch.undo()  # настоящая today(), без подмены из conftest
    monkeypatch.setenv(DATE_ENV, "2026-10-31")
    assert module.today() == HALLOWEEN_DAY


def test_event_sound_files_exist_and_are_documented():
    readme = (ROOT / "overlay" / "sounds" / "halloween" / "README.md").read_text(encoding="utf-8")
    for event in EVENTS:
        for sound in event.sounds:
            assert sound.id.startswith(event.id + ":")
            if sound.file:
                path = ROOT / "overlay" / "sounds" / sound.file
                assert path.is_file(), sound.file
                assert path.stat().st_size < 200 * 1024  # короткие звуки, не раздуваем exe
                assert Path(sound.file).name in readme  # источник и лицензия записаны
    assert "CC0" in readme


def test_sound_js_lists_the_same_files():
    """Случайный скример оформления в sound.js берёт файлы из того же набора."""
    text = (ROOT / "overlay" / "sound.js").read_text(encoding="utf-8")
    files = {s.file for s in HALLOWEEN.sounds if s.file}
    assert all(f'"{f}"' in text for f in files)


# --- звуки события в библиотеке ---


@pytest.fixture
def sound(settings, tmp_path, events):
    return Sound(settings, tmp_path / "sounds", events)


def test_event_sounds_listed_only_during_event(sound, event_day):
    assert sound.state()["event_sounds"] == []
    event_day(HALLOWEEN_DAY)
    sounds = sound.state()["event_sounds"]
    assert sounds[0] == {"id": "halloween:random", "name": "🎃 Случайный скример", "url": None}
    assert {"id": "halloween:ghost", "name": "👻 Визг призрака", "url": "/overlay/sounds/halloween/ghost-shriek.ogg"} in sounds


def test_event_sound_can_be_selected_during_event(sound, halloween):
    sound.select("halloween:random")
    state = sound.state()
    assert state["active"] == "halloween:random"
    assert state["active_name"] == "🎃 Случайный скример"


def test_event_sound_rejected_outside_event(sound):
    with pytest.raises(KeyError):
        sound.select("halloween:ghost")


def test_selected_event_sound_falls_back_after_event(sound, event_day):
    event_day(HALLOWEEN_DAY)
    sound.select("halloween:ghost")
    event_day(date(2026, 11, 2))
    assert sound.state()["active"] is None  # стандартный звук


# --- сервер ---


@pytest.fixture
def client(hub, recognizer, settings, sound, fake_sd):  # noqa: F811
    app = create_app(hub, recognizer, settings, sound)
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def test_events_api(client, halloween):
    assert client.get("/api/events").json()["active"] == ["halloween"]
    with client.websocket_connect("ws://localhost/ws") as ws:
        greeting = skip_greeting(ws)
        assert greeting[4] == {"type": "events", "active": ["halloween"], "events": [
            {"id": "halloween", "title": "Хеллоуин", "until": "2026-11-01", "enabled": True}]}
        response = client.post("/api/events/halloween", json={"enabled": False})
        assert response.json()["active"] == []
        assert [ws.receive_json()["type"] for _ in range(3)] == ["events", "style", "sound"]


def test_unknown_event_404(client):
    assert client.post("/api/events/christmas", json={"enabled": True}).status_code == 404


def test_halloween_preset_only_during_event(client, event_day):
    assert client.post("/api/overlay/preset", json={"preset": "halloween"}).status_code == 400
    event_day(HALLOWEEN_DAY)
    assert client.post("/api/overlay/preset", json={"preset": "halloween"}).json()["preset"] == "halloween"
    event_day(date(2026, 11, 2))
    assert client.get("/api/overlay").json()["preset"] == "swearcounter"  # после события — обычное


def test_increment_marks_curse_during_event(client, halloween):
    with client.websocket_connect("ws://localhost/ws/events") as ws:
        ws.receive_json()  # счёт
        for _ in range(13):
            client.post("/api/increment")
            message = ws.receive_json()
        assert message == {"type": "increment", "count": 13, "delta": 1, "curse": True}
        client.post("/api/increment")
        assert "curse" not in ws.receive_json()


def test_increment_has_no_curse_outside_event(client):
    with client.websocket_connect("ws://localhost/ws/events") as ws:
        ws.receive_json()
        for _ in range(13):
            client.post("/api/increment")
            message = ws.receive_json()
        assert "curse" not in message
