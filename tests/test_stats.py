"""Статистика по сессиям: подсчёт, сохранение, сброс, CSV и API."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import server, stats
from app.server import Hub, create_app
from app.stats import Stats
from test_server import SMALL, FakeRecognizer


class Clock:
    def __init__(self):
        self.now = 1_700_000_000.0

    def __call__(self):
        return self.now


def test_session_starts_on_first_word():
    clock = Clock()
    s = Stats(clock=clock)
    assert s.sessions == []
    clock.now += 5
    s.add(2, ["бля", "хрен"])
    clock.now += 60
    s.add(1, ["бля"])
    assert s.sessions == [
        {"start": 1_700_000_005, "end": 1_700_000_065, "count": 3, "words": {"бля": 2, "хрен": 1}},
    ]


def test_manual_add_counts_without_words():
    s = Stats(clock=Clock())
    s.add(1)
    assert s.sessions[0]["count"] == 1 and s.sessions[0]["words"] == {}


def test_new_session_after_reset_and_empty_one_not_saved():
    s = Stats(clock=Clock())
    s.add(1, ["бля"])
    s.new_session()
    s.new_session()  # сброс без слов — пустой сессии нет
    s.add(1, ["хрен"])
    assert [x["words"] for x in s.sessions] == [{"бля": 1}, {"хрен": 1}]


def test_saved_and_restart_starts_new_session(tmp_path):
    path = tmp_path / "stats.json"
    s = Stats(path, clock=Clock())
    s.add(1, ["бля"])
    again = Stats(path, clock=Clock())
    assert again.sessions == s.sessions
    again.add(1, ["бля"])
    assert len(again.sessions) == 2
    assert len(json.loads(path.read_text(encoding="utf-8"))["sessions"]) == 2


@pytest.mark.parametrize("content", ["не json", '{"sessions": [{"start": "x"}]}', "[]", '{"sessions": 5}'])
def test_broken_file_starts_over(tmp_path, content):
    path = tmp_path / "stats.json"
    path.write_text(content, encoding="utf-8")
    assert Stats(path).sessions == []


def test_old_sessions_dropped(monkeypatch):
    monkeypatch.setattr(stats, "MAX_SESSIONS", 3)
    s = Stats(clock=Clock())
    for i in range(5):
        s.add(i + 1)
        s.new_session()
    assert [x["count"] for x in s.sessions] == [3, 4, 5]


def test_state_has_recent_sessions_top_and_totals(monkeypatch):
    monkeypatch.setattr(stats, "RECENT_SESSIONS", 2)
    s = Stats(clock=Clock())
    s.add(2, ["хрен", "бля"])
    s.new_session()
    s.add(1, ["бля"])
    s.new_session()
    s.add(1)
    state = s.state()
    assert [x["count"] for x in state["sessions"]] == [1, 1]
    assert "words" not in state["sessions"][0]
    assert state["top"] == [["бля", 2], ["хрен", 1]]
    assert (state["total"], state["session_count"]) == (4, 3)


def test_clear(tmp_path):
    path = tmp_path / "stats.json"
    s = Stats(path, clock=Clock())
    s.add(1, ["бля"])
    s.clear()
    assert Stats(path).sessions == []


def test_csv():
    clock = Clock()
    s = Stats(clock=clock)
    s.add(1, ["хрен"])
    clock.now += 600
    s.add(2, ["бля", "бля"])
    lines = s.csv().split("\r\n")
    assert lines[0] == "Начало;Конец;Минут;Слов;Какие слова"
    cells = lines[1].split(";")
    assert cells[2:] == ["10", "3", "бля 2, хрен 1"]
    assert lines[2] == ""


# --- в связке с сервером ---


def test_hub_feeds_stats(counter):
    hub = Hub(counter)
    asyncio.run(hub.increment(2, speech=True, words=["бля", "хрен"]))
    asyncio.run(hub.increment(1))
    asyncio.run(hub.reset())
    asyncio.run(hub.increment(1, speech=True, words=["бля"]))
    assert [(x["count"], x["words"]) for x in hub.stats.sessions] == [(3, {"бля": 1, "хрен": 1}), (1, {"бля": 1})]


def test_ignored_increments_not_in_stats(counter):
    hub = Hub(counter)
    asyncio.run(hub.set_paused(True))
    asyncio.run(hub.increment(1, speech=True, words=["бля"]))
    hub.locked = lambda: True
    asyncio.run(hub.increment(1))
    assert hub.stats.sessions == []


@pytest.fixture
def client(counter, models_dir, settings, tmp_path, fake_sd):
    from app.sound import Sound

    (models_dir / SMALL).mkdir()
    hub = Hub(counter)
    hub.stats.add(2, ["бля", "бля"])
    app = create_app(hub, FakeRecognizer(models_dir / SMALL), settings, Sound(settings, tmp_path / "s"))
    with TestClient(app, base_url="http://localhost") as c:
        yield c


def test_api_get_and_clear(client):
    state = client.get("/api/stats").json()
    assert state["top"] == [["бля", 2]] and state["total"] == 2
    assert client.delete("/api/stats").json()["session_count"] == 0
    assert client.get("/api/stats").json()["sessions"] == []


def test_api_export_saves_to_downloads(client, monkeypatch, tmp_path):
    revealed = []
    monkeypatch.setattr(server, "downloads_dir", lambda: tmp_path)
    monkeypatch.setattr(server, "reveal", revealed.append)
    r = client.post("/api/stats/export")
    path = tmp_path / "swearcounter-stats.csv"
    assert r.json() == {"path": str(path)} and revealed == [path]
    data = path.read_bytes()
    assert data.startswith("﻿".encode())  # BOM для Excel
    assert "бля 2" in data.decode("utf-8-sig")
