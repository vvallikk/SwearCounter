"""Живые субтитры: цензура, выключатель, пауза и доставка только обычным клиентам /ws."""

import asyncio
from functools import partial

import pytest
from fastapi.testclient import TestClient

from app.server import Hub, create_app
from app.sound import Sound
from app.subtitles import Subtitles, censor
from conftest import skip_greeting
from test_server import SMALL, FakeRecognizer

ROOTS = ("бля", "хрен")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ну бля опять", "ну *** опять"),
        ("Хреново БЛЯТЬ", "******* *****"),  # регистр и формы слова
        ("чистая фраза", "чистая фраза"),
        ("", ""),
    ],
)
def test_censor_masks_words_starting_with_root(text, expected):
    assert censor(text, ROOTS) == expected


def test_censor_without_roots_keeps_text():
    assert censor("бля", ()) == "бля"


def feed(settings, steps, paused=lambda: False) -> list[dict]:
    """Прогоняет фразы ("p"/"f", текст) через субтитры и возвращает разосланные сообщения."""
    sent: list[dict] = []

    async def broadcast(message: dict) -> None:
        sent.append(message)

    async def scenario() -> None:
        subtitles = Subtitles(settings, broadcast, paused=paused, censor=partial(censor, roots=ROOTS))
        for kind, text in steps:
            await subtitles.feed(text, kind == "f")

    asyncio.run(scenario())
    return sent


def test_disabled_by_default_sends_nothing(settings):
    assert feed(settings, [("p", "привет"), ("f", "привет мир")]) == []


def test_enabled_sends_censored_partial_and_final(settings):
    settings.set("subtitles", True)
    assert feed(settings, [("p", "ну бля"), ("f", "ну бля опять")]) == [
        {"type": "subtitle", "text": "ну ***", "final": False},
        {"type": "subtitle", "text": "ну *** опять", "final": True},
    ]


def test_uncensored_sends_text_as_is(settings):
    settings.set("subtitles", True)
    settings.set("subtitles_uncensored", True)
    assert feed(settings, [("f", "ну бля")])[0]["text"] == "ну бля"


def test_repeated_and_empty_partials_are_skipped(settings):
    settings.set("subtitles", True)
    sent = feed(settings, [("f", "раз"), ("p", ""), ("p", "два"), ("p", "два"), ("f", "два")])
    assert [(m["text"], m["final"]) for m in sent] == [("раз", True), ("два", False), ("два", True)]


def test_paused_sends_nothing(settings):
    settings.set("subtitles", True)
    assert feed(settings, [("p", "привет"), ("f", "привет")], paused=lambda: True) == []


# --- сервер ---


@pytest.fixture
def subtitles_client(counter, settings, tmp_path, models_dir, fake_sd):
    (models_dir / SMALL).mkdir()
    hub = Hub(counter)
    subtitles = Subtitles(settings, hub.broadcast, paused=lambda: hub.paused)
    app = create_app(hub, FakeRecognizer(models_dir / SMALL), settings, Sound(settings, tmp_path / "sounds"),
                     subtitles=subtitles)
    with TestClient(app, base_url="http://localhost") as client:
        yield client, subtitles


def test_api_toggles_are_saved_and_broadcast(subtitles_client, settings_path):
    client, _ = subtitles_client
    assert client.get("/api/subtitles").json() == {"type": "subtitles", "enabled": False, "uncensored": False}
    with client.websocket_connect("ws://localhost/ws") as ws:
        assert skip_greeting(ws)[-1]["enabled"] is False
        assert client.post("/api/subtitles", json={"enabled": True}).json()["enabled"] is True
        assert ws.receive_json() == {"type": "subtitles", "enabled": True, "uncensored": False}
    assert '"subtitles": true' in settings_path.read_text(encoding="utf-8")


def test_subtitle_reaches_ws_but_not_events(subtitles_client):
    client, subtitles = subtitles_client
    client.post("/api/subtitles", json={"enabled": True, "uncensored": True})
    with client.websocket_connect("ws://localhost/ws") as ws, client.websocket_connect(
        "ws://localhost/ws/events"
    ) as events:
        skip_greeting(ws)
        assert events.receive_json()["type"] == "state"
        client.portal.call(subtitles.feed, "всем привет", True)
        client.post("/api/increment")  # маркер: до него в /ws/events ничего не пришло
        assert ws.receive_json() == {"type": "subtitle", "text": "всем привет", "final": True}
        assert events.receive_json()["type"] == "increment"


@pytest.mark.parametrize(("language", "word"), [("ru", "субтитры"), ("en", "subtitles")])
def test_sample_phrase_is_sent_even_when_disabled(subtitles_client, settings, language, word):
    client, _ = subtitles_client
    settings.set("ui_language", language)
    with client.websocket_connect("ws://localhost/ws") as ws:
        skip_greeting(ws)
        assert client.post("/api/subtitles/test").status_code == 200
        message = ws.receive_json()
    assert message["type"] == "subtitle" and message["final"] is True and word in message["text"]
