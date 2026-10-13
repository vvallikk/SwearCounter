"""Хайлайты: метки слов, моменты, таймкоды, экспорт и действия в OBS."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app import highlights, obs_link, server
from app.highlights import Timeline
from app.server import Hub, create_app
from app.sound import Sound
from test_obs import FakeObs, _event
from test_obs_link import wait_for
from test_server import SMALL, FakeRecognizer


class Clock:
    def __init__(self):
        self.now = 1_700_000_000.0

    def __call__(self):
        return self.now


def timeline_with(*steps):
    """Timeline, в который слова добавлены с паузами: steps — (пауза до слова, слова)."""
    clock = Clock()
    t = Timeline(clock=clock)
    for pause, words in steps:
        clock.now += pause
        t.add(1, list(words))
    return t, clock


def test_format_time():
    assert highlights.format_time(0) == "0:00"
    assert highlights.format_time(65.9) == "1:05"
    assert highlights.format_time(3723) == "1:02:03"
    assert highlights.format_time(-5) == "0:00"


def test_add_ignores_decrease_and_dedups_words():
    t = Timeline(clock=Clock())
    assert t.add(-1) is None and t.add(0) is None
    mark = t.add(2, ["бля", "бля", "хрен"])
    assert mark["words"] == ["бля", "хрен"] and mark["n"] == 2


def test_words_close_together_form_one_moment():
    t, _ = timeline_with((20, ["бля"]), (4, ["бля"]), (3, ["хрен"]), (60, ["пипец"]))
    moments = t.moments("start", lead=3)
    assert [m["count"] for m in moments] == [3, 1]
    assert moments[0]["words"] == ["бля", "хрен"]
    assert moments[0]["time"] == pytest.approx(17)  # 20 с от начала минус 3 с «заранее»
    assert moments[1]["time"] == pytest.approx(84)


def test_lead_does_not_cross_previous_moment_or_zero():
    t, _ = timeline_with((1, ["а"]), (12, ["б"]))
    first, second = t.moments("start", lead=30)
    assert first["time"] == 0
    assert second["time"] == pytest.approx(first["last"])


def test_chapters_start_with_zero_and_show_counts():
    t, _ = timeline_with((75, ["бля"]), (2, ["бля"]), (3600, ["хрен"]))
    assert t.chapters("start", lead=5).splitlines() == [
        "0:00 Начало",
        "1:10 Слово ×2: бля",
        "1:01:12 Слово: хрен",
    ]


def test_no_intro_when_first_moment_at_zero():
    t, _ = timeline_with((2, ["бля"]))
    assert t.chapters("start", lead=5) == "0:00 Слово: бля"


def test_anchor_excludes_earlier_marks_and_shifts_offsets():
    t, clock = timeline_with((10, ["прошлый"]))
    clock.now += 100
    t.set_anchor("stream")
    clock.now += 30
    t.add(1, ["бля"])
    assert t.chapters("stream", lead=0).splitlines()[-1] == "0:30 Слово: бля"
    assert "прошлый" not in t.chapters("stream", lead=0)
    assert "прошлый" in t.chapters("start", lead=0)
    assert t.state()["base"] == "stream"
    assert t.moments("record") == []  # записи не было


def test_csv_has_header_and_clips():
    t, _ = timeline_with((30, ["бля"]))
    t.set_clip(t.marks[0], r"C:\clips\a.mkv")
    lines = t.csv("start", lead=0).splitlines()
    assert lines[0] == "Время;Секунд;Слов;Какие слова;Клипы"
    assert lines[1] == r"0:30;30;1;бля;C:\clips\a.mkv"


def test_restart_clears_marks_and_anchors():
    t, clock = timeline_with((5, ["бля"]))
    t.set_anchor("record")
    clock.now += 50
    t.restart()
    assert t.marks == [] and t.anchors == {} and t.origin == clock.now


def test_marks_are_capped(monkeypatch):
    monkeypatch.setattr(highlights, "MAX_MARKS", 3)
    t = Timeline(clock=Clock())
    for i in range(5):
        t.add(1, [str(i)])
    assert [m["words"] for m in t.marks] == [["2"], ["3"], ["4"]]


def test_persists_and_survives_garbage(tmp_path):
    path = tmp_path / "highlights.json"
    clock = Clock()
    t = Timeline(path, clock=clock)
    t.set_anchor("stream")
    t.add(1, ["бля"])
    again = Timeline(path, clock=clock)
    assert again.marks == t.marks and again.anchors == t.anchors and again.origin == t.origin
    path.write_text("{ не json", encoding="utf-8")
    assert Timeline(path, clock=clock).marks == []
    path.write_text(json.dumps({"origin": 1, "anchors": {}, "marks": [{"at": "x"}]}), encoding="utf-8")
    assert Timeline(path, clock=clock).marks == []


def test_clean_options():
    assert highlights.clean_options({"obs": True, "clip": "yes"}) == {"obs": True, "chapter": False, "clip": False}
    assert highlights.clean_options("мусор") == {"obs": False, "chapter": False, "clip": False}
    assert not highlights.link_needed(highlights.clean_options(None))
    assert highlights.link_needed({"obs": False, "chapter": True, "clip": False})


# --- API и OBS ---


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(obs_link, "RECV_TIMEOUT", 0.05)
    monkeypatch.setattr(highlights, "CLIP_SETTLE", 0)


def make_app(counter, models_dir, settings, tmp_path):
    (models_dir / SMALL).mkdir(exist_ok=True)
    return create_app(Hub(counter), FakeRecognizer(models_dir / SMALL), settings, Sound(settings, tmp_path / "s"))


@pytest.fixture
def fake_obs():
    responses = {"GetLastReplayBufferReplay": {"savedReplayPath": r"C:\clips\replay.mkv"}}
    with FakeObs(responses=responses) as fake:
        yield fake


@pytest.fixture
def client(counter, models_dir, settings, tmp_path, fake_sd, fake_obs, monkeypatch):
    settings.set("obs_ws_port", fake_obs.port)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr(server, "downloads_dir", lambda: downloads)
    monkeypatch.setattr(server, "reveal", lambda path: None)
    with TestClient(make_app(counter, models_dir, settings, tmp_path), base_url="http://localhost") as c:
        c.downloads = downloads
        yield c


def test_counted_words_become_marks(client):
    assert client.get("/api/highlights").json()["marks"] == 0
    client.post("/api/increment")
    data = client.get("/api/highlights").json()
    assert data["marks"] == 1 and data["base"] == "start"
    assert data["moments"][0]["count"] == 1
    assert data["options"] == {"obs": False, "chapter": False, "clip": False}


def test_text_and_export(client):
    client.post("/api/increment")
    text = client.get("/api/highlights/text", params={"format": "chapters", "lead": 0}).text
    assert text.startswith("0:00 Слово")
    resp = client.post("/api/highlights/export", json={"format": "csv", "base": "start", "lead": 0})
    saved = (client.downloads / "swearcounter-highlights.csv").read_text(encoding="utf-8-sig")
    assert resp.json()["path"].endswith("swearcounter-highlights.csv")
    assert saved.startswith("Время;Секунд;Слов")


@pytest.mark.parametrize("params", [{"format": "xml"}, {"base": "год"}, {"lead": 999}, {"lead": -1}])
def test_text_rejects_bad_params(client, params):
    assert client.get("/api/highlights/text", params=params).status_code == 400


def test_restart_endpoint(client):
    client.post("/api/increment")
    assert client.delete("/api/highlights").json()["marks"] == 0


def test_options_saved_and_connect_link(client, settings):
    data = client.post("/api/highlights", json={"obs": True}).json()
    assert data["options"]["obs"] is True
    assert settings.get("highlights") == {"obs": True, "chapter": False, "clip": False}
    wait_for(lambda: client.get("/api/highlights").json()["obs"]["connected"])


def test_stream_start_sets_anchor(client, fake_obs):
    client.post("/api/highlights", json={"obs": True})
    wait_for(lambda: client.get("/api/highlights").json()["obs"]["connected"])
    fake_obs.push(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTED"))
    wait_for(lambda: "stream" in client.get("/api/highlights").json()["bases"])
    client.post("/api/increment")
    data = client.get("/api/highlights").json()
    assert data["base"] == "stream" and data["moments"][0]["count"] == 1


def test_anchor_restored_from_running_obs(counter, models_dir, settings, tmp_path, fake_sd):
    responses = {"GetStreamStatus": {"outputActive": True, "outputDuration": 600_000}}
    with FakeObs(responses=responses) as fake:
        settings.set("obs_ws_port", fake.port)
        settings.set("highlights", {"obs": True})
        with TestClient(make_app(counter, models_dir, settings, tmp_path), base_url="http://localhost") as c:
            wait_for(lambda: "stream" in c.get("/api/highlights").json()["bases"])
            anchor = c.get("/api/highlights").json()["bases"]["stream"]
    assert anchor == pytest.approx(time.time() - 600, abs=5)


def test_clip_and_chapter_requested_with_cooldown(client, fake_obs):
    client.post("/api/highlights", json={"chapter": True, "clip": True})
    wait_for(lambda: client.get("/api/highlights").json()["obs"]["connected"])
    client.post("/api/increment")
    client.post("/api/increment")  # сразу же: попадает в паузу между клипами

    def types():
        return [r["requestType"] for r in fake_obs.requests]

    wait_for(lambda: "GetLastReplayBufferReplay" in types())
    assert types().count("SaveReplayBuffer") == 1
    assert types().count("CreateRecordChapter") == 1
    chapter = next(r for r in fake_obs.requests if r["requestType"] == "CreateRecordChapter")
    assert chapter["requestData"] == {"chapterName": "Слово"}
    wait_for(lambda: client.get("/api/highlights").json()["moments"][0]["clips"] == [r"C:\clips\replay.mkv"])


def test_obs_error_is_shown(counter, models_dir, settings, tmp_path, fake_sd):
    with FakeObs(fail={"SaveReplayBuffer"}) as fake:
        settings.set("obs_ws_port", fake.port)
        settings.set("highlights", {"clip": True})
        with TestClient(make_app(counter, models_dir, settings, tmp_path), base_url="http://localhost") as c:
            wait_for(lambda: c.get("/api/highlights").json()["obs"]["connected"])
            c.post("/api/increment")
            wait_for(lambda: "SaveReplayBuffer" in c.get("/api/highlights").json()["error"])
