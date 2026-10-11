"""Связь с OBS в сервере: настройки, сброс при начале трансляции, смена сцены, /api/count и /ws/events."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import obs_link, server
from app.server import Hub, create_app
from app.settings import Settings
from test_obs import FakeObs, _event
from test_obs_link import wait_for
from test_server import FakeRecognizer, SMALL

SCENES = {"scenes": [{"sceneName": "Ад", "sceneIndex": 1}, {"sceneName": "Игра", "sceneIndex": 0}]}


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(obs_link, "RECV_TIMEOUT", 0.05)


@pytest.fixture
def fake_obs():
    with FakeObs(responses={"GetSceneList": SCENES}) as fake:
        yield fake


@pytest.fixture
def make_client(counter, models_dir, settings, tmp_path, fake_sd, fake_obs):
    from app.sound import Sound

    (models_dir / SMALL).mkdir()
    settings.set("obs_ws_port", fake_obs.port)
    clients = []

    def make(**options):
        if options:
            settings.set("obs_link", options)
        hub = Hub(counter)
        app = create_app(hub, FakeRecognizer(models_dir / SMALL), settings, Sound(settings, tmp_path / "s"))
        client = TestClient(app, base_url="http://localhost").__enter__()
        clients.append(client)
        client.hub = hub
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def test_obs_options_cleans_bad_values(settings):
    settings.set("obs_link", {"reset_stream": "yes", "reset_record": True, "scene": 5, "scene_at": -1})
    assert server.obs_options(settings) == {"reset_stream": False, "reset_record": True, "scene": "", "scene_at": 0}
    settings.set("obs_link", "мусор")
    assert server.obs_options(settings)["reset_record"] is False


def test_link_off_by_default(make_client, fake_obs):
    client = make_client()
    data = client.get("/api/obs").json()
    assert data == {
        "reset_stream": False, "reset_record": False, "scene": "", "scene_at": 0,
        "status": {"enabled": False, "connected": False, "error": ""},
    }
    assert fake_obs.identify is None


def test_post_saves_and_connects(make_client, settings, settings_path):
    client = make_client()
    data = client.post("/api/obs", json={"reset_stream": True, "scene": "Ад", "scene_at": 50}).json()
    assert data["reset_stream"] is True and data["status"]["enabled"] is True
    assert Settings(settings_path).get("obs_link")["scene_at"] == 50
    wait_for(lambda: client.get("/api/obs").json()["status"]["connected"])


@pytest.mark.parametrize("body", [{"scene_at": -1}, {"scene_at": 10**9}, {"scene": "x" * 300}, {"reset_stream": "maybe"}])
def test_post_rejects_bad_values(make_client, body):
    assert make_client().post("/api/obs", json=body).status_code in (400, 422)


def test_scene_only_with_threshold_needs_link():
    assert not server.obs_link_needed({"reset_stream": False, "reset_record": False, "scene": "Ад", "scene_at": 0})
    assert server.obs_link_needed({"reset_stream": False, "reset_record": False, "scene": "Ад", "scene_at": 5})


def test_reset_on_stream_start(make_client, fake_obs):
    client = make_client(reset_stream=True)
    client.post("/api/increment")
    with client.websocket_connect("ws://localhost/ws") as ws:
        while ws.receive_json()["type"] != "style":
            pass
        wait_for(lambda: client.get("/api/obs").json()["status"]["connected"])
        fake_obs.push(_event("RecordStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTED"))  # запись не включена
        fake_obs.push(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTED"))
        while (message := ws.receive_json())["type"] != "state":
            pass
    assert message["count"] == 0


def test_obs_status_broadcast(make_client):
    client = make_client()
    with client.websocket_connect("ws://localhost/ws") as ws:
        while ws.receive_json()["type"] != "style":
            pass
        client.post("/api/obs", json={"reset_record": True})
        while (message := ws.receive_json())["type"] != "obs":
            pass
    assert message["connected"] is True


def test_scene_switch_once_at_threshold(make_client, fake_obs):
    client = make_client(scene="Ад", scene_at=2)
    wait_for(lambda: client.get("/api/obs").json()["status"]["connected"])
    for _ in range(4):
        client.post("/api/increment")

    def switches():
        return [r for r in fake_obs.requests if r["requestType"] == "SetCurrentProgramScene"]

    wait_for(lambda: switches())
    client.post("/api/reset")
    client.post("/api/increment")
    client.post("/api/increment")
    wait_for(lambda: len(switches()) == 2)
    assert switches()[0]["requestData"] == {"sceneName": "Ад"}


def test_scenes_one_off_and_through_link(make_client):
    client = make_client()
    assert client.get("/api/obs/scenes").json() == {"scenes": ["Ад", "Игра"]}
    client.post("/api/obs", json={"reset_stream": True})
    wait_for(lambda: client.get("/api/obs").json()["status"]["connected"])
    assert client.get("/api/obs/scenes").json() == {"scenes": ["Ад", "Игра"]}


def test_scenes_obs_not_running(make_client, settings, fake_obs):
    client = make_client()
    fake_obs.__exit__(None, None, None)
    resp = client.get("/api/obs/scenes")
    assert resp.status_code == 400 and "не отвечает" in resp.json()["detail"]


def test_count_plain_text(make_client):
    client = make_client()
    client.post("/api/increment")
    resp = client.get("/api/count")
    assert resp.text == "1" and resp.headers["content-type"].startswith("text/plain")


def test_events_ws_only_count_and_pause(make_client):
    client = make_client()
    with client.websocket_connect("ws://localhost/ws/events") as ws:
        assert ws.receive_json() == {"type": "state", "count": 0}
        client.post("/api/increment")  # increment, затем timer — его здесь нет
        client.post("/api/pause", json={"paused": True})
        assert ws.receive_json()["type"] == "increment"
        assert ws.receive_json()["type"] == "pause"


def test_events_ws_rejects_foreign_origin(make_client):
    client = make_client()
    with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect(
        "ws://localhost/ws/events", headers={"Origin": "https://evil.example"}
    ) as ws:
        ws.receive_json()
    assert e.value.code == 1008
