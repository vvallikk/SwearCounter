"""Голосовые команды: поиск в тексте, настройки, повтор и выполнение сервером."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import obs_link, voice_commands
from app.server import Hub, create_app
from app.settings import Settings
from app.sound import Sound
from app.voice_commands import VoiceCommands, VoiceCommandsError, clean_config, default_config, match
from conftest import skip_greeting
from test_obs import FakeObs
from test_obs_link import wait_for
from test_server import SMALL, FakeRecognizer


def config(**changes) -> dict:
    return default_config() | {"enabled": True} | changes


# --- поиск команды в тексте ---


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("счётчик пауза", "pause"),
        ("Счетчик, ПАУЗА!", "pause"),  # регистр, ё и знаки не важны
        ("ну короче счётчик давай пауза пожалуйста", "pause"),  # лишние слова вокруг
        ("счётчику продолжай", "resume"),  # кодовое слово в другом падеже
        ("counter pause", "pause"),
        ("counter plus one", "increment"),
        ("счётчик плюс один", "increment"),
    ],
)
def test_match(text, action):
    assert match(text, config())["action"] == action


@pytest.mark.parametrize(
    "text",
    [
        "пауза",  # без кодового слова — обычная речь
        "сделаем паузу, счётчик",  # фраза до кодового слова
        "счётчик раз два три четыре пауза",  # слишком далеко от кодового слова
        "счётчик сброс",  # сброс выключен по умолчанию
        "",
    ],
)
def test_no_match(text):
    assert match(text, config()) is None


def test_longest_phrase_wins():
    assert match("счётчик плюс один", config())["phrase"] == "плюс один"


def test_reset_only_when_allowed():
    assert match("счётчик сброс", config(allow_reset=True))["action"] == "reset"


def test_scene_command_and_custom_wake_word():
    cfg = config(wake_words=["бот"], scenes=[{"phrases": ["сцена игра"], "scene": "Игра"}])
    assert match("бот сцена игра", cfg) == {"action": "scene", "phrase": "сцена игра", "scene": "Игра"}
    assert match("счётчик сцена игра", cfg) is None


def test_user_phrases_replace_defaults():
    cfg = config(phrases=default_config()["phrases"] | {"pause": ["стоп"]})
    assert match("счётчик стоп", cfg)["action"] == "pause"
    assert match("счётчик пауза", cfg) is None


# --- настройки ---


def test_off_by_default():
    assert clean_config(None) == default_config()
    assert default_config()["enabled"] is False and default_config()["allow_reset"] is False


def test_clean_config_fixes_bad_values():
    cfg = clean_config({
        "enabled": "yes",
        "wake_words": ["  ", 5],
        "phrases": {"pause": "пауза", "resume": ["  дальше  ", "дальше", ""]},
        "scenes": [{"phrases": ["игра"], "scene": ""}, "мусор", {"phrases": ["ад"], "scene": " Ад "}],
    })
    assert cfg["enabled"] is False
    assert cfg["wake_words"] == voice_commands.DEFAULT_WAKE_WORDS
    assert cfg["phrases"]["pause"] == voice_commands.DEFAULT_PHRASES["pause"]
    assert cfg["phrases"]["resume"] == ["дальше"]
    assert cfg["scenes"] == [{"phrases": ["ад"], "scene": "Ад"}]


@pytest.mark.parametrize(
    "changes",
    [
        {"wake_words": [" "]},
        {"wake_words": ["x" * 100]},
        {"scenes": [{"phrases": ["игра"], "scene": " "}]},
        {"scenes": [{"phrases": ["игра"], "scene": "x" * 300}]},
        {"phrases": default_config()["phrases"] | {"pause": ["x" * 100]}},
    ],
)
def test_validate_rejects(changes):
    with pytest.raises(VoiceCommandsError):
        voice_commands.validate(config(**changes))


# --- срабатывание ---


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def make_voice(settings, **changes):
    settings.set(voice_commands.SETTING, config(**changes))
    fired = []

    async def on_command(command):
        fired.append(command["action"])

    clock = Clock()
    return VoiceCommands(settings, on_command, clock=clock), fired, clock


def test_only_final_text(settings):
    voice, fired, _ = make_voice(settings)
    assert asyncio.run(voice.feed("счётчик пауза", False)) is None
    assert asyncio.run(voice.feed("счётчик пауза", True))["action"] == "pause"
    assert fired == ["pause"]


def test_disabled_does_nothing(settings):
    voice, fired, _ = make_voice(settings, enabled=False)
    assert asyncio.run(voice.feed("счётчик пауза", True)) is None
    assert fired == []


def test_cooldown_per_command(settings):
    voice, fired, clock = make_voice(settings)

    async def run():
        await voice.feed("счётчик пауза", True)
        await voice.feed("счётчик пауза", True)  # повтор той же фразы — пропуск
        await voice.feed("счётчик продолжить", True)  # другая команда — сразу
        clock.now += voice_commands.COOLDOWN
        await voice.feed("счётчик пауза", True)

    asyncio.run(run())
    assert fired == ["pause", "resume", "pause"]


def test_needs_obs_only_for_enabled_scene_commands(settings):
    voice = VoiceCommands(settings)
    assert not voice.needs_obs()
    settings.set(voice_commands.SETTING, config(scenes=[{"phrases": ["игра"], "scene": "Игра"}]))
    assert voice.needs_obs()
    settings.set(voice_commands.SETTING, config(enabled=False, scenes=[{"phrases": ["игра"], "scene": "Игра"}]))
    assert not voice.needs_obs()


# --- сервер ---


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(obs_link, "RECV_TIMEOUT", 0.05)


@pytest.fixture
def fake_obs():
    with FakeObs() as fake:
        yield fake


@pytest.fixture
def app_client(counter, models_dir, settings, tmp_path, fake_sd, fake_obs):
    (models_dir / SMALL).mkdir()
    settings.set("obs_ws_port", fake_obs.port)
    voice = VoiceCommands(settings)
    app = create_app(
        Hub(counter), FakeRecognizer(models_dir / SMALL), settings, Sound(settings, tmp_path / "s"),
        voice_commands=voice,
    )
    with TestClient(app, base_url="http://localhost") as client:
        client.voice = voice
        client.say = lambda text: client.portal.call(voice.feed, text, True)
        yield client


def test_api_defaults_and_save(app_client, settings_path):
    data = app_client.get("/api/voice-commands").json()
    assert data["enabled"] is False and data["last"] is None
    body = data | {"enabled": True, "wake_words": ["бот"]}
    data = app_client.post("/api/voice-commands", json=body).json()
    assert data["enabled"] is True and data["wake_words"] == ["бот"]
    assert Settings(settings_path).get(voice_commands.SETTING)["wake_words"] == ["бот"]


def test_api_rejects_bad_config(app_client):
    response = app_client.post("/api/voice-commands", json={"enabled": True, "wake_words": [" "]})
    assert response.status_code == 400


def test_pause_and_resume_by_voice(app_client):
    app_client.post("/api/voice-commands", json=config())
    app_client.say("счётчик пауза")
    assert app_client.get("/api/pause").json() == {"paused": True}
    app_client.say("счётчик продолжить")  # на паузе команды слушаются
    assert app_client.get("/api/pause").json() == {"paused": False}


def test_increment_by_voice_and_broadcast(app_client):
    app_client.post("/api/voice-commands", json=config())
    with app_client.websocket_connect("ws://localhost/ws") as ws:
        skip_greeting(ws)
        app_client.say("счётчик плюс один")
        while (message := ws.receive_json())["type"] != "voice_command":
            pass
    assert message["action"] == "increment" and message["ok"] is True
    assert app_client.get("/api/state").json() == {"count": 1}
    assert app_client.get("/api/voice-commands").json()["last"]["phrase"] == "плюс один"


def test_reset_by_voice_only_when_allowed(app_client):
    app_client.post("/api/voice-commands", json=config())
    app_client.post("/api/increment")
    app_client.say("счётчик сброс")
    assert app_client.get("/api/state").json() == {"count": 1}
    app_client.post("/api/voice-commands", json=config(allow_reset=True))
    app_client.say("счётчик сброс")
    assert app_client.get("/api/state").json() == {"count": 0}


def test_scene_by_voice_connects_obs_and_switches(app_client, fake_obs):
    app_client.post("/api/voice-commands", json=config(scenes=[{"phrases": ["сцена игра"], "scene": "Игра"}]))
    wait_for(lambda: app_client.get("/api/obs").json()["status"]["connected"])
    app_client.say("счётчик сцена игра")
    switches = [r for r in fake_obs.requests if r["requestType"] == "SetCurrentProgramScene"]
    assert switches[0]["requestData"] == {"sceneName": "Игра"}
    assert app_client.voice.last["ok"] is True


def test_scene_without_obs_reports_error(app_client, fake_obs):
    app_client.voice.save(config(scenes=[{"phrases": ["сцена игра"], "scene": "Игра"}]))  # связь не включали
    app_client.say("счётчик сцена игра")
    assert app_client.voice.last["ok"] is False and app_client.voice.last["error"]
