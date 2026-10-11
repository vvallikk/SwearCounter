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


def test_stream_started():
    assert obs.stream_started(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTED"))
    assert not obs.stream_started(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTING"))
    assert not obs.stream_started(_event("RecordStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTED"))
    assert not obs.stream_started({"op": 7, "d": {}})


class FakeObs:
    """Сервер WebSocket, отвечающий как OBS: Hello, Identify, GetStreamStatus и события."""

    def __init__(self, password: str | None = None, streaming: bool = False, events: list[dict] = ()):
        self.password = password
        self.streaming = streaming
        self.events = list(events)
        self.identify: dict | None = None
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
        for message in ws:
            request = json.loads(message)["d"]
            ws.send(json.dumps(_event("StreamStateChanged", "OBS_WEBSOCKET_OUTPUT_STARTING")))  # шум до ответа
            ws.send(json.dumps({
                "op": 7,
                "d": {
                    "requestType": request["requestType"],
                    "requestId": request["requestId"],
                    "requestStatus": {"result": True, "code": 100},
                    "responseData": {"outputActive": self.streaming},
                },
            }))
            for event in self.events:
                ws.send(json.dumps(event))


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
