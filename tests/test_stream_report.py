"""Отчёт после стрима: текст, настройки с секретами, отправка (сеть поддельная) и конец трансляции в OBS."""

import asyncio
import io
import json
import threading
import urllib.error

import pytest
from fastapi.testclient import TestClient

from app import i18n, obs, obs_link, stream_report
from app.server import Hub, create_app
from app.settings import Settings
from app.sound import Sound
from app.stream_report import StreamReport
from test_obs import FakeObs, _event
from test_obs_link import Recorder, wait_for
from test_server import SMALL, FakeRecognizer

WEBHOOK = "https://discord.com/api/webhooks/123456/abcDEF_secret-tail9"
TOKEN = "123456789:AAEexampleexampleexample_tok1"


class FakeNet:
    """Подмена post_json: запоминает запросы, может ответить ошибкой."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.fail: dict[str, Exception] = {}  # часть адреса → исключение

    def __call__(self, url, payload):
        self.calls.append((url, payload))
        for part, error in self.fail.items():
            if part in url:
                raise error
        return b'{"ok": true}'


@pytest.fixture(autouse=True)
def net(monkeypatch):
    fake = FakeNet()
    monkeypatch.setattr(stream_report, "post_json", fake)

    def no_network(*args, **kwargs):
        raise AssertionError("настоящий запрос в сеть")

    monkeypatch.setattr(stream_report.urllib.request, "urlopen", no_network)
    return fake


@pytest.fixture(autouse=True)
def russian(monkeypatch):
    monkeypatch.setattr(i18n, "system_language", lambda: i18n.RU)


class Clock:
    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_hub(counter) -> Hub:
    return Hub(counter)


def add(hub: Hub, delta: int, words: list[str] = ()) -> None:
    asyncio.run(hub.increment(delta, words=words))


def test_text_has_session_summary(counter, settings):
    hub = make_hub(counter)
    clock = Clock()
    report = StreamReport(hub, settings, clock=clock)
    add(hub, 3, ["бля", "бля", "хуй"])
    add(hub, 1, ["сук"])
    hub.goal = 3
    clock.now += 2 * 3600 + 5 * 60
    text = report.text()
    lines = text.splitlines()
    assert lines[0] == "Счётчик матов: итоги стрима"
    assert "Длительность: 2 ч 05 мин" in lines
    assert "Счёт: 4" in lines
    assert "Чаще всего: б** — 2, с** — 1, х** — 1" in lines  # звёздочками, по частоте
    assert "Цель 3: достигнута" in lines
    assert any(line.startswith("Самая долгая серия без мата: ") for line in lines)


def test_text_uncensored_goal_missed_and_extra(counter, settings, monkeypatch):
    hub = make_hub(counter)
    report = StreamReport(hub, settings)
    report.save({"censor": False})
    add(hub, 2, ["бля", "бля"])
    hub.goal = 10
    monkeypatch.setattr(hub.extra, "items", lambda: [{"name": "Паразиты", "count": 7}])
    lines = report.text().splitlines()
    assert "Чаще всего: бля — 2" in lines
    assert "Цель 10: не достигнута (2 из 10)" in lines
    assert "Другие счётчики: Паразиты — 7" in lines


def test_text_in_english(counter, settings):
    settings.set(i18n.SETTING, i18n.EN)
    hub = make_hub(counter)
    report = StreamReport(hub, settings)
    lines = report.text().splitlines()
    assert lines[0] == "Swear Counter: stream report"
    assert "Count: 0" in lines and "Duration: 0 s" in lines
    assert not any("Most frequent" in line for line in lines)  # слов не было
    assert not any("Goal" in line for line in lines)  # цели нет


def test_streak_counts_current_run(counter, settings):
    hub = make_hub(counter)
    report = StreamReport(hub, settings)
    hub.timer.record = 30.0
    hub.timer.elapsed = lambda: 125.0  # текущая серия длиннее рекорда
    assert "Самая долгая серия без мата: 2 мин 05 с" in report.text()


def test_duration_from_reset_and_stream_start(counter, settings):
    hub = make_hub(counter)
    clock = Clock()
    report = StreamReport(hub, settings, clock=clock)
    hub.reset_listeners.append(report.on_reset)
    clock.now += 600
    asyncio.run(hub.reset())  # сессия с этого момента
    clock.now += 60
    assert "Длительность: 1 мин 00 с" in report.text()
    report.on_stream_started()
    clock.now += 30
    assert "Длительность: 30 с" in report.text()


def test_censor():
    assert stream_report.censor("хуй") == "х**"
    assert stream_report.censor("х") == "*"


def test_options_ignore_bad_values(settings):
    settings.set(stream_report.SETTING, {"discord_webhook": "http://evil", "telegram_token": 5, "auto": "yes"})
    opts = stream_report.options(settings)
    assert opts == {"discord_webhook": "", "telegram_token": "", "telegram_chat": "", "auto": False, "censor": True}
    settings.set(stream_report.SETTING, "мусор")
    assert stream_report.options(settings)["censor"] is True


@pytest.mark.parametrize("changes", [
    {"discord_webhook": "https://example.com/api/webhooks/1/x"},
    {"discord_webhook": "https://discord.com/api/webhooks/1/x\r\nHost: a"},
    {"telegram_token": "not a token"},
    {"telegram_chat": "chat id"},
])
def test_save_rejects_bad_values(counter, settings, changes):
    report = StreamReport(make_hub(counter), settings)
    with pytest.raises(stream_report.ReportError):
        report.save(changes)


def test_send_to_both(counter, settings, net):
    hub = make_hub(counter)
    report = StreamReport(hub, settings)
    report.save({"discord_webhook": WEBHOOK, "telegram_token": TOKEN, "telegram_chat": "-100123"})
    add(hub, 1, ["бля"])
    last = report.send()
    assert last["results"] == {"discord": {"ok": True}, "telegram": {"ok": True}}
    (discord_url, discord), (telegram_url, telegram) = net.calls
    assert discord_url == WEBHOOK and discord["allowed_mentions"] == {"parse": []}
    assert "Счёт: 1" in discord["content"]
    assert telegram_url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert telegram["chat_id"] == "-100123" and telegram["text"] == discord["content"]
    assert settings.get(stream_report.LAST_SETTING) == last


def test_send_without_targets(counter, settings, net):
    report = StreamReport(make_hub(counter), settings)
    report.save({"telegram_token": TOKEN})  # без чата Telegram не годится
    with pytest.raises(stream_report.ReportError, match="Не задано"):
        report.send()
    assert net.calls == []


def test_send_errors_hide_secrets(counter, settings, net):
    report = StreamReport(make_hub(counter), settings)
    report.save({"discord_webhook": WEBHOOK, "telegram_token": TOKEN, "telegram_chat": "@my_channel"})
    body = io.BytesIO(json.dumps({"ok": False, "description": "Bad Request: chat not found"}).encode())
    net.fail["telegram"] = urllib.error.HTTPError("https://api.telegram.org/bot" + TOKEN, 400, "Bad", {}, body)
    net.fail["discord"] = urllib.error.URLError("timed out")
    results = report.send()["results"]
    assert results["telegram"] == {"ok": False, "error": "Telegram ответил ошибкой 400: Bad Request: chat not found"}
    assert results["discord"] == {"ok": False, "error": "нет связи с Discord (timed out)"}
    assert TOKEN not in json.dumps(results) and "secret" not in json.dumps(results)


def test_state_masks_secrets(counter, settings):
    report = StreamReport(make_hub(counter), settings)
    report.save({"discord_webhook": WEBHOOK, "telegram_token": TOKEN, "telegram_chat": "-100123"})
    state = report.state()
    dumped = json.dumps(state)
    assert WEBHOOK not in dumped and TOKEN not in dumped
    assert state["discord"] == {"set": True, "hint": "…ail9"}
    assert state["telegram"] == {"set": True, "hint": "…tok1", "chat": "-100123"}
    report.save({"discord_webhook": None, "telegram_token": ""})  # None — оставить, "" — удалить
    assert report.state()["discord"]["set"] and not report.state()["telegram"]["set"]


def test_stream_stopped_sends_only_when_auto(counter, settings, net):
    report = StreamReport(make_hub(counter), settings)
    report.save({"discord_webhook": WEBHOOK})
    report.on_stream_stopped()
    assert net.calls == [] and not report.auto_enabled()
    report.save({"auto": True})
    done = threading.Event()
    real_send = report.send
    report.send = lambda auto=False: (real_send(auto=auto), done.set())
    report.on_stream_stopped()
    assert done.wait(5)
    assert len(net.calls) == 1 and settings.get(stream_report.LAST_SETTING)["auto"] is True


# --- События OBS ---


def test_output_stopped():
    stopped = _event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STOPPED")
    assert obs.output_stopped(stopped, "StreamStateChanged")
    assert not obs.output_started(stopped, "StreamStateChanged")
    assert not obs.output_stopped(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STOPPING"), "StreamStateChanged")


def test_link_reports_stop(monkeypatch):
    monkeypatch.setattr(obs_link, "RECV_TIMEOUT", 0.05)
    rec = Recorder()
    stopped: list[str] = []
    with FakeObs() as server:
        link = obs_link.ObsLink(rec.outputs.append, rec.statuses.append, on_output_stopped=stopped.append)
        link.configure(True, server.port, "")
        link.start()
        wait_for(lambda: link.connected)
        server.push(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTED"))
        server.push(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STOPPING"))
        server.push(_event("RecordStateChanged", "OBS_WEBSOCKET_OUTPUT_STOPPED"))
        server.push(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STOPPED"))
        wait_for(lambda: len(stopped) == 2)
        link.stop()
    assert rec.outputs == ["stream"]  # старт как раньше
    assert stopped == ["record", "stream"]


# --- API ---


@pytest.fixture
def client(counter, models_dir, settings, tmp_path, fake_sd):
    (models_dir / SMALL).mkdir()
    hub = Hub(counter)
    app = create_app(hub, FakeRecognizer(models_dir / SMALL), settings, Sound(settings, tmp_path / "s"))
    with TestClient(app, base_url="http://localhost") as client:
        client.hub = hub
        yield client


def test_api_off_by_default(client):
    state = client.get("/api/stream-report").json()
    assert state == {
        "discord": {"set": False, "hint": ""},
        "telegram": {"set": False, "hint": "", "chat": ""},
        "auto": False, "censor": True, "last": None,
    }
    assert client.get("/api/obs").json()["status"]["enabled"] is False


def test_api_save_preview_send(client, net, settings_path):
    data = client.post("/api/stream-report", json={"discord_webhook": WEBHOOK}).json()
    assert data["discord"]["set"] and WEBHOOK not in json.dumps(data)
    assert Settings(settings_path).get(stream_report.SETTING)["discord_webhook"] == WEBHOOK
    client.post("/api/increment")
    assert "Счёт: 1" in client.get("/api/stream-report/preview").json()["text"]
    data = client.post("/api/stream-report/send").json()
    assert data["last"]["results"] == {"discord": {"ok": True}} and len(net.calls) == 1


def test_api_errors(client):
    assert client.post("/api/stream-report/send").status_code == 400
    assert client.post("/api/stream-report", json={"telegram_token": "x"}).status_code == 400


def test_api_auto_turns_obs_link_on(client):
    client.post("/api/stream-report", json={"discord_webhook": WEBHOOK, "auto": True})
    assert client.get("/api/obs").json()["status"]["enabled"] is True
    client.post("/api/stream-report", json={"auto": False})
    assert client.get("/api/obs").json()["status"]["enabled"] is False
