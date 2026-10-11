"""Клиент obs-websocket против поддельного сервера OBS на localhost."""

import json
import threading

import pytest
from websockets.sync.server import serve

from app import obs

PASSWORD = "supersecretpassword"
SALT = "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI="
CHALLENGE = "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY="


def test_auth_string_matches_protocol_example():
    # Пример из документации obs-websocket.
    assert obs.auth_string(PASSWORD, SALT, CHALLENGE) == "1Ct943GAT+6YQUUX47Ia/ncufilbe6+oD6lY+5kaCu4="


def _event(event_type: str, state: str) -> dict:
    return {"op": 5, "d": {"eventType": event_type, "eventData": {"outputActive": True, "outputState": state}}}


def test_output_started_record():
    started = _event("RecordStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTED")
    assert obs.output_started(started, "RecordStateChanged")
    assert not obs.output_started(started, "StreamStateChanged")


def test_response_data():
    ok = {"op": 7, "d": {"requestStatus": {"result": True}, "responseData": {"a": 1}}}
    assert obs.response_data(ok) == {"a": 1}
    assert obs.response_data({"op": 7, "d": {"requestStatus": {"result": True}}}) == {}
    failed = {"op": 7, "d": {"requestType": "X", "requestStatus": {"result": False, "code": 600, "comment": "нет"}}}
    with pytest.raises(obs.ObsError, match="X: нет"):
        obs.response_data(failed)
    with pytest.raises(obs.ObsError, match="код 204"):
        obs.response_data({"op": 7, "d": {"requestStatus": {"result": False, "code": 204}}})


def test_scene_names_top_first():
    data = {"scenes": [
        {"sceneName": "Низ", "sceneIndex": 0},
        {"sceneName": "Верх", "sceneIndex": 2},
        {"sceneName": "Середина", "sceneIndex": 1},
        {"sceneIndex": 3},
    ]}
    assert obs.scene_names(data) == ["Верх", "Середина", "Низ"]
    assert obs.scene_names({}) == []


def test_stream_started():
    assert obs.stream_started(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTED"))
    assert not obs.stream_started(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTING"))
    assert not obs.stream_started(_event("RecordStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTED"))
    assert not obs.stream_started({"op": 7, "d": {}})


class FakeObs:
    """Сервер WebSocket, отвечающий как OBS: Hello, Identify, запросы и события.

    responses — данные ответа по типу запроса (по умолчанию — состояние трансляции);
    fail — типы запросов, которые OBS «не выполняет»; push — событие уже подключённому клиенту.
    """

    def __init__(
        self,
        password: str | None = None,
        streaming: bool = False,
        events: list[dict] = (),
        responses: dict[str, dict] | None = None,
        fail: set[str] = frozenset(),
    ):
        self.password = password
        self.streaming = streaming
        self.events = list(events)
        self.responses = responses or {}
        self.fail = fail
        self.requests: list[dict] = []
        self.identify: dict | None = None
        self.ws = None
        self.identified = threading.Event()
        self.server = serve(self._handle, "127.0.0.1", 0)
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.thread.join(5)

    def _handle(self, ws):
        hello = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1}
        if self.password is not None:
            hello["authentication"] = {"challenge": CHALLENGE, "salt": SALT}
        ws.send(json.dumps({"op": 0, "d": hello}))
        self.identify = json.loads(ws.recv())["d"]
        if self.password is not None and self.identify.get("authentication") != obs.auth_string(
            self.password, SALT, CHALLENGE
        ):
            ws.close(4009, "Authentication failed")
            return
        ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        self.ws = ws
        self.identified.set()
        for message in ws:
            request = json.loads(message)["d"]
            self.requests.append(request)
            request_type = request["requestType"]
            ws.send(json.dumps(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTING")))  # шум до ответа
            if request_type in self.fail:
                status = {"result": False, "code": 600, "comment": "No source was found"}
            else:
                status = {"result": True, "code": 100}
            ws.send(json.dumps({
                "op": 7,
                "d": {
                    "requestType": request_type,
                    "requestId": request["requestId"],
                    "requestStatus": status,
                    "responseData": self.responses.get(request_type, {"outputActive": self.streaming}),
                },
            }))
            for event in self.events:
                ws.send(json.dumps(event))

    def push(self, message: dict) -> None:
        assert self.identified.wait(5)
        self.ws.send(json.dumps(message))


def test_check_without_password():
    with FakeObs(streaming=True) as server:
        assert obs.check(server.port, "") is True
    assert server.identify["eventSubscriptions"] == obs.EVENT_OUTPUTS
    assert "authentication" not in server.identify


def test_check_with_password():
    with FakeObs(password=PASSWORD) as server:
        assert obs.check(server.port, PASSWORD) is False


def test_wrong_password():
    with FakeObs(password=PASSWORD) as server, pytest.raises(obs.ObsError, match="пароль"):
        obs.check(server.port, "wrong")


def test_password_required():
    with FakeObs(password=PASSWORD) as server, pytest.raises(obs.ObsError, match="укажите"):
        obs.check(server.port, "")


def test_obs_not_running():
    with FakeObs() as server:
        port = server.port
    with pytest.raises(obs.ObsError, match="не отвечает"):
        obs.check(port, "")


def test_messages_yield_events_and_timeouts():
    started = _event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTED")
    with FakeObs(events=[started]) as server, obs.ObsClient(server.port) as client:
        assert client.streaming() is False
        messages = client.messages(timeout=0.2)
        assert next(messages) == started
        assert next(messages) is None


def test_scenes_one_off():
    scenes = {"scenes": [{"sceneName": "Игра", "sceneIndex": 1}, {"sceneName": "Чат", "sceneIndex": 0}]}
    with FakeObs(responses={"GetSceneList": scenes}) as server:
        assert obs.scenes(server.port, "") == ["Игра", "Чат"]


def test_request_with_data_and_failure():
    with FakeObs(fail={"SetCurrentProgramScene"}) as server, obs.ObsClient(server.port) as client:
        with pytest.raises(obs.ObsError, match="No source"):
            client.request("SetCurrentProgramScene", {"sceneName": "Нет"})
    assert server.requests[0]["requestData"] == {"sceneName": "Нет"}
