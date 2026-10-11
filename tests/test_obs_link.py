"""Постоянная связь с OBS против поддельного сервера: события выходов, запросы, переподключение."""

import threading
import time

import pytest

from app import obs, obs_link
from app.obs_link import ObsLink
from test_obs import FakeObs, _event


def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "не дождались"
        time.sleep(0.02)


class Recorder:
    def __init__(self):
        self.outputs: list[str] = []
        self.statuses: list[dict] = []

    def link(self, **kwargs) -> ObsLink:
        return ObsLink(self.outputs.append, self.statuses.append, **kwargs)


@pytest.fixture
def rec():
    return Recorder()


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(obs_link, "RECV_TIMEOUT", 0.05)


def test_disabled_does_not_connect(rec):
    with FakeObs() as server:
        link = rec.link()
        link.configure(False, server.port, "")
        link.start()
        time.sleep(0.2)
        link.stop()
    assert server.identify is None
    assert link.state() == {"enabled": False, "connected": False, "error": ""}
    assert rec.statuses == []  # состояние не менялось


def test_output_events(rec):
    with FakeObs() as server:
        link = rec.link()
        link.configure(True, server.port, "")
        link.start()
        wait_for(lambda: link.connected)
        server.push(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTING"))
        server.push(_event("RecordStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTED"))
        server.push(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTED"))
        wait_for(lambda: len(rec.outputs) == 2)
        link.stop()
    assert rec.outputs == ["record", "stream"]
    assert rec.statuses[0] == {"enabled": True, "connected": True, "error": ""}


def test_request_through_link(rec):
    scenes = {"scenes": [{"sceneName": "Игра", "sceneIndex": 0}]}
    with FakeObs(responses={"GetSceneList": scenes}, fail={"SetCurrentProgramScene"}) as server:
        link = rec.link()
        link.configure(True, server.port, "")
        link.start()
        wait_for(lambda: link.connected)
        assert link.request("GetSceneList") == scenes
        with pytest.raises(obs.ObsError, match="No source"):
            link.request("SetCurrentProgramScene", {"sceneName": "Нет"})
        link.stop()
    assert server.requests[-1]["requestData"] == {"sceneName": "Нет"}


def test_request_without_connection(rec):
    link = rec.link()
    with pytest.raises(obs.ObsError, match="Нет связи"):
        link.request("GetSceneList")


def test_obs_not_running_reports_error_and_retries(rec):
    with FakeObs() as server:
        port = server.port
    link = rec.link(retry=0.05)
    link.configure(True, port, "")
    link.start()
    wait_for(lambda: link.error)
    assert "не отвечает" in link.state()["error"] and not link.connected
    with FakeObs() as server:
        link.configure(True, server.port, "")  # новый порт — сразу переподключение
        wait_for(lambda: link.connected)
        assert link.error == ""
        link.stop()


def test_disable_disconnects(rec):
    with FakeObs() as server:
        link = rec.link()
        link.configure(True, server.port, "")
        link.start()
        wait_for(lambda: link.connected)
        link.configure(False, server.port, "")
        wait_for(lambda: not link.connected)
        link.stop()
    assert rec.statuses[-1] == {"enabled": False, "connected": False, "error": ""}


def test_same_config_keeps_connection(rec):
    with FakeObs() as server:
        link = rec.link()
        link.configure(True, server.port, "")
        link.start()
        wait_for(lambda: link.connected)
        link.configure(True, server.port, "")
        time.sleep(0.2)
        link.stop()
    assert [s["connected"] for s in rec.statuses] == [True]


def test_pending_request_fails_on_disconnect(rec, monkeypatch):
    with FakeObs() as server:
        link = rec.link()
        link.configure(True, server.port, "")
        link.start()
        wait_for(lambda: link.connected)
        # Ответ не придёт: подменяем отправку, а связь выключаем.
        monkeypatch.setattr(link._client, "send_request", lambda *a: "never")
        result = {}

        def ask():
            try:
                link.request("GetSceneList")
            except obs.ObsError as e:
                result["error"] = str(e)

        thread = threading.Thread(target=ask)
        thread.start()
        wait_for(lambda: "never" in link._pending)
        link.configure(False, server.port, "")
        thread.join(5)
        link.stop()
    assert result["error"] == "Связь с OBS прервалась"
