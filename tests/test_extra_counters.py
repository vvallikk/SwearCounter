"""Дополнительные счётчики: хранение, свой список слов, распознавание, API и оверлей-сообщения."""

import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient

from app import extra_counters
from app.extra_counters import CounterError, ExtraCounters, ExtraTrackers
from app.server import create_app
from conftest import skip_greeting
from test_server import word_lists  # noqa: F401  — та же фикстура списков слов


@pytest.fixture
def lists_dir(tmp_path):
    directory = tmp_path / "lists"
    directory.mkdir()
    (directory / "swears.txt").write_text("бля\n", encoding="utf-8")
    (directory / "parasites.txt").write_text("# Название: Паразиты\nкороче\nтипа\n", encoding="utf-8")
    return directory


@pytest.fixture
def list_path(lists_dir):
    def resolve(list_id):
        path = lists_dir / list_id
        if not path.exists():
            raise KeyError(list_id)
        return path

    return resolve


def test_add_update_remove_and_persist(tmp_path, list_path):
    path = tmp_path / "counters.json"
    counters = ExtraCounters(path, list_path)
    first = counters.add("  Паразиты \n", "parasites.txt")
    assert first == {"id": "c1", "name": "Паразиты", "list": "parasites.txt", "preset": "swearcounter", "label": "", "count": 0}
    counters.add("Маты", "swears.txt")
    counters.update("c1", preset="neon", label="Паразиты:")
    counters.add_count("c1", 3)
    counters.remove("c2")
    assert counters.add("Ещё", "swears.txt")["id"] == "c2"  # номер после самого большого
    reloaded = ExtraCounters(path, list_path)
    assert reloaded.items()[0] == {**first, "preset": "neon", "label": "Паразиты:", "count": 3}
    assert reloaded.ids() == ["c1", "c2"]


def test_legacy_counter_without_preset_keeps_classic(tmp_path, list_path):
    """Файл, записанный до смены оформления по умолчанию: счётчик остаётся в «Классике»."""
    path = tmp_path / "counters.json"
    path.write_text(
        '{"counters": [{"id": "c1", "name": "Старый", "list": "swears.txt", "count": 2},'
        ' {"id": "c2", "name": "Свой", "list": "swears.txt", "preset": "my-pack", "count": 0}]}',
        encoding="utf-8",
    )
    items = ExtraCounters(path, list_path).items()
    assert [item["preset"] for item in items] == ["classic", "my-pack"]


@pytest.mark.parametrize("name, list_id, message", [
    ("", "swears.txt", "название"),
    ("x" * 41, "swears.txt", "длиннее"),
    ("Маты", "nope.txt", "списка нет"),
])
def test_add_rejects_bad_values(list_path, name, list_id, message):
    with pytest.raises(CounterError, match=message):
        ExtraCounters(None, list_path).add(name, list_id)


def test_limit(list_path):
    counters = ExtraCounters(None, list_path)
    for i in range(extra_counters.MAX_COUNTERS):
        counters.add(f"С{i}", "swears.txt")
    with pytest.raises(CounterError, match="не больше"):
        counters.add("Лишний", "swears.txt")


def test_broken_file_starts_empty(tmp_path, list_path):
    path = tmp_path / "counters.json"
    path.write_text("{мусор", encoding="utf-8")
    assert ExtraCounters(path, list_path).items() == []
    path.write_text(json.dumps({"counters": [{"id": "c1", "name": "A", "list": "x.txt", "count": -5}]}), encoding="utf-8")
    assert ExtraCounters(path, list_path).items()[0]["count"] == 0


def test_find_uses_own_list_and_rereads_changes(lists_dir, list_path):
    counters = ExtraCounters(None, list_path)
    counters.add("Паразиты", "parasites.txt")
    assert counters.find("c1", "короче бля типа") == ["короче", "типа"]
    file = lists_dir / "parasites.txt"
    file.write_text("ну\n", encoding="utf-8")
    stat = file.stat()
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    assert counters.find("c1", "ну короче") == ["ну"]
    file.unlink()
    assert counters.find("c1", "ну") == []  # файл списка пропал — счётчик молчит
    assert counters.find("нет", "ну") == []


def test_trackers_follow_counters(list_path):
    counters = ExtraCounters(None, list_path)
    counters.add("Паразиты", "parasites.txt")
    counters.add("Маты", "swears.txt")
    added = []

    async def add(counter_id, words):
        added.append((counter_id, words))

    async def scenario():
        trackers = ExtraTrackers(counters, add)
        await trackers.feed("короче бля типа", True)
        counters.remove("c2")
        await trackers.feed("бля короче", True)

    asyncio.run(scenario())
    assert added == [("c1", ["короче", "типа"]), ("c2", ["бля"]), ("c1", ["короче"])]


def test_trackers_skip_on_pause(list_path):
    counters = ExtraCounters(None, list_path)
    counters.add("Паразиты", "parasites.txt")
    added = []

    async def add(counter_id, words):
        added.append(words)

    asyncio.run(ExtraTrackers(counters, add, paused=lambda: True).feed("короче", True))
    assert added == []


# --- сервер ---


@pytest.fixture
def client(hub, recognizer, settings, sound, fake_sd, word_lists):  # noqa: F811
    app = create_app(hub, recognizer, settings, sound, word_lists=word_lists)
    with TestClient(app, base_url="http://localhost") as client:
        yield client


@pytest.fixture
def recognizer(models_dir):
    from test_server import SMALL, FakeRecognizer

    (models_dir / SMALL).mkdir()
    return FakeRecognizer(models_dir / SMALL)


@pytest.fixture
def sound(settings, tmp_path):
    from app.sound import Sound

    return Sound(settings, tmp_path / "sounds")


@pytest.fixture
def hub(counter):
    from app.server import Hub

    return Hub(counter)


def test_api_lifecycle_and_broadcasts(client, hub):
    with client.websocket_connect("ws://localhost/ws") as ws:
        greeting = skip_greeting(ws)
        assert greeting[-1] == {"type": "counters", "counters": []}
        resp = client.post("/api/counters", json={"name": "Паразиты", "list": "parasites.txt"})
        assert resp.json()["counters"][0]["id"] == "c1"
        assert ws.receive_json()["counters"][0]["name"] == "Паразиты"

        assert client.post("/api/counters/c1/increment").json() == {"count": 1}
        assert ws.receive_json() == {"type": "extra_increment", "id": "c1", "count": 1, "delta": 1}
        assert hub.counter.value == 0  # основной счётчик не тронут

        client.post("/api/counters/c1", json={"preset": "neon", "label": " Паразиты:\n"})
        changed = ws.receive_json()["counters"][0]
        assert (changed["preset"], changed["label"]) == ("neon", "Паразиты:")

        client.post("/api/counters/c1/reset")
        assert ws.receive_json()["counters"][0]["count"] == 0
        assert client.delete("/api/counters/c1").json() == {"counters": []}
        assert ws.receive_json() == {"type": "counters", "counters": []}


def test_counter_has_own_size_and_plate(client, settings):
    client.post("/api/counters", json={"name": "Паразиты", "list": "parasites.txt"})
    client.post("/api/overlay/scale", json={"number": 70, "label": 90, "target": "c1"})
    state = client.post("/api/overlay/plate", json={"plate": "pill", "target": "c1"}).json()
    assert state["sources"] == {"c1": {"number": 70, "label": 90, "plate": "pill"}}
    assert (state["number_scale"], state["plate"]) == (100, "none")
    with client.websocket_connect("ws://localhost/ws") as ws:
        skip_greeting(ws)
        client.delete("/api/counters/c1")
        assert ws.receive_json()["sources"] == {}  # удалённый счётчик не оставляет настроек
    assert settings.get("overlay_sources") == {}


@pytest.mark.parametrize("body", [{"preset": "Bad Id"}, {"label": "x" * 41}, {"list": "nope.txt"}, {"name": ""}])
def test_update_rejects_bad_values(client, body):
    client.post("/api/counters", json={"name": "Паразиты", "list": "parasites.txt"})
    assert client.post("/api/counters/c1", json=body).status_code == 400


def test_unknown_counter_404(client):
    assert client.post("/api/counters/c9/increment").status_code == 404
    assert client.delete("/api/counters/c9").status_code == 404
    assert client.post("/api/counters/c9", json={"label": ""}).status_code == 404


def test_speech_increment_skipped_on_pause(client, hub):
    client.post("/api/counters", json={"name": "Паразиты", "list": "parasites.txt"})
    client.post("/api/pause", json={"paused": True})
    assert asyncio.run(hub.increment_extra("c1", 2, speech=True)) == 0
    assert client.post("/api/counters/c1/increment").json() == {"count": 1}  # кнопка работает
