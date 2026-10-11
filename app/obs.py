"""Клиент obs-websocket v5 (встроен в OBS 28+): узнать, идёт ли трансляция, и ждать её начала.

В OBS сервер включается в «Инструменты → Настройки сервера WebSocket».
Протокол: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
"""

import base64
import hashlib
import json
from collections.abc import Iterator
from contextlib import ExitStack

from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI
from websockets.sync.client import ClientConnection, connect

OP_HELLO = 0
OP_IDENTIFY = 1
OP_IDENTIFIED = 2
OP_EVENT = 5
OP_REQUEST = 6
OP_REQUEST_RESPONSE = 7
EVENT_OUTPUTS = 1 << 6  # подписка на StreamStateChanged и другие события выходов
RPC_VERSION = 1
CLOSE_AUTH_FAILED = 4009
CONNECT_TIMEOUT = 5.0


class ObsError(Exception):
    """Понятная пользователю причина, почему не удалось поговорить с OBS."""


def auth_string(password: str, salt: str, challenge: str) -> str:
    """Ответ на вызов авторизации: base64(sha256(base64(sha256(пароль + соль)) + вызов))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def stream_started(message: dict) -> bool:
    """Событие «трансляция началась»."""
    if message.get("op") != OP_EVENT:
        return False
    data = message.get("d") or {}
    event = data.get("eventData") or {}
    return data.get("eventType") == "StreamStateChanged" and event.get("outputState") == "OBS_WEBSOCKET_OUTPUT_STARTED"


class ObsClient:
    """Подключение к OBS; использовать как контекстный менеджер."""

    def __init__(self, port: int, password: str = "", host: str = "127.0.0.1", timeout: float = CONNECT_TIMEOUT):
        self.url = f"ws://{host}:{port}"
        self.password = password
        self.timeout = timeout
        self._ws: ClientConnection | None = None
        self._stack = ExitStack()
        self._request_id = 0

    def __enter__(self) -> "ObsClient":
        try:
            self._ws = self._stack.enter_context(connect(self.url, open_timeout=self.timeout, max_size=2**22))
        except (OSError, TimeoutError, InvalidHandshake, InvalidURI):
            raise ObsError(
                "OBS не отвечает. Проверьте, что OBS запущен и в «Инструменты → Настройки сервера "
                "WebSocket» включён сервер с этим портом"
            ) from None
        try:
            self._identify()
        except TimeoutError:
            self._stack.close()
            raise ObsError("OBS не ответил на подключение") from None
        except BaseException:
            self._stack.close()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self._stack.close()

    def _recv(self, timeout: float | None) -> dict:
        try:
            raw = self._ws.recv(timeout)
        except ConnectionClosed as e:
            if e.rcvd is not None and e.rcvd.code == CLOSE_AUTH_FAILED:
                raise ObsError("OBS не принял пароль: проверьте его в настройках сервера WebSocket") from None
            raise ObsError("OBS закрыл соединение") from None
        try:
            message = json.loads(raw)
        except ValueError:
            raise ObsError("OBS прислал непонятный ответ") from None
        return message if isinstance(message, dict) else {}

    def _send(self, op: int, data: dict) -> None:
        self._ws.send(json.dumps({"op": op, "d": data}))

    def _identify(self) -> None:
        hello = self._recv(self.timeout)
        if hello.get("op") != OP_HELLO:
            raise ObsError("По этому порту отвечает не OBS")
        identify = {"rpcVersion": RPC_VERSION, "eventSubscriptions": EVENT_OUTPUTS}
        auth = (hello.get("d") or {}).get("authentication")
        if auth:
            if not self.password:
                raise ObsError("В OBS для сервера WebSocket задан пароль: укажите его здесь")
            identify["authentication"] = auth_string(self.password, auth["salt"], auth["challenge"])
        self._send(OP_IDENTIFY, identify)
        if self._recv(self.timeout).get("op") != OP_IDENTIFIED:
            raise ObsError("OBS не принял подключение")

    def streaming(self) -> bool:
        """Идёт ли сейчас трансляция."""
        self._request_id += 1
        request_id = str(self._request_id)
        self._send(OP_REQUEST, {"requestType": "GetStreamStatus", "requestId": request_id})
        while True:
            try:
                message = self._recv(self.timeout)
            except TimeoutError:
                raise ObsError("OBS не ответил на запрос") from None
            data = message.get("d") or {}
            if message.get("op") == OP_REQUEST_RESPONSE and data.get("requestId") == request_id:
                return bool((data.get("responseData") or {}).get("outputActive"))

    def messages(self, timeout: float) -> Iterator[dict | None]:
        """Сообщения от OBS; None — за timeout ничего не пришло (можно проверить, не пора ли выйти)."""
        while True:
            try:
                yield self._recv(timeout)
            except TimeoutError:
                yield None


def check(port: int, password: str) -> bool:
    """Проверка подключения со страницы управления; возвращает, идёт ли трансляция."""
    with ObsClient(port, password) as client:
        return client.streaming()
