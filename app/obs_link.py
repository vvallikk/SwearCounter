"""Постоянная связь с OBS, пока программа запущена: события начала трансляции и записи
и запросы вроде смены сцены.

Подключение живёт в своём потоке: obs-websocket синхронный, а OBS может быть закрыт
часами — тогда поток просто повторяет попытки. Выключенная связь (ни одна функция OBS
не нужна) к OBS не подключается вовсе.
"""

import logging
import threading
from collections.abc import Callable

from .obs import OP_EVENT, OP_REQUEST_RESPONSE, ObsClient, ObsError, output_started, response_data

log = logging.getLogger(__name__)

RETRY = 5.0  # пауза перед новым подключением, если OBS не отвечает
RECV_TIMEOUT = 0.5  # так часто поток проверяет, не изменились ли настройки
REQUEST_TIMEOUT = 5.0

OUTPUT_EVENTS = {"StreamStateChanged": "stream", "RecordStateChanged": "record"}


class ObsLink:
    def __init__(
        self,
        on_output: Callable[[str], None],
        on_status: Callable[[dict], None] = lambda state: None,
        client_factory: Callable[[int, str], ObsClient] = ObsClient,
        retry: float = RETRY,
    ):
        """on_output("stream" | "record") — выход запустился; on_status — подключились или отвалились.

        Оба вызываются из потока связи.
        """
        self._on_output = on_output
        self._on_status = on_status
        self._client_factory = client_factory
        self._retry = retry
        self._config: tuple[int, str] | None = None  # None — связь выключена
        self._changed = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: ObsClient | None = None
        self._pending: dict[str, list] = {}  # id запроса → [Event, сообщение-ответ]
        self._pending_lock = threading.Lock()
        self.connected = False
        self.error = ""

    def state(self) -> dict:
        enabled = self._config is not None  # выключили — старая ошибка уже не важна
        return {"enabled": enabled, "connected": self.connected, "error": self.error if enabled else ""}

    def configure(self, enabled: bool, port: int, password: str) -> None:
        config = (port, password) if enabled else None
        if config != self._config:
            self._config = config
            self._changed.set()  # переподключиться с новыми настройками

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="obs-link", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._changed.set()
        if self._thread is not None:
            self._thread.join(5)

    def request(self, request_type: str, request_data: dict | None = None) -> dict:
        """Запрос к OBS из любого потока; ответ читает поток связи."""
        client = self._client
        if client is None:
            raise ObsError(self.error or "Нет связи с OBS")
        waiter = [threading.Event(), None]
        with self._pending_lock:
            request_id = client.send_request(request_type, request_data)
            self._pending[request_id] = waiter
        if not waiter[0].wait(REQUEST_TIMEOUT):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise ObsError("OBS не ответил на запрос")
        if waiter[1] is None:
            raise ObsError("Связь с OBS прервалась")
        return response_data(waiter[1])

    def _run(self) -> None:
        while not self._stopping.is_set():
            self._changed.clear()
            config = self._config
            if config is None:
                self._set_status(False, "")
                self._changed.wait()
                continue
            try:
                with self._client_factory(*config) as client:
                    self._client = client
                    log.info("Связь с OBS установлена")
                    self._set_status(True, "")
                    for message in client.messages(RECV_TIMEOUT):
                        if self._changed.is_set():
                            break
                        if message is not None:
                            self._handle(message)
            except ObsError as e:
                if self.connected or self.error != str(e):
                    log.info("Нет связи с OBS: %s", e)
                self._set_status(False, str(e))
                self._changed.wait(self._retry)
            finally:
                self._client = None
                self._fail_pending()

    def _handle(self, message: dict) -> None:
        if message.get("op") == OP_REQUEST_RESPONSE:
            with self._pending_lock:
                waiter = self._pending.pop((message.get("d") or {}).get("requestId"), None)
            if waiter is not None:
                waiter[1] = message
                waiter[0].set()
        elif message.get("op") == OP_EVENT:
            for event_type, output in OUTPUT_EVENTS.items():
                if output_started(message, event_type):
                    log.info("OBS: запущен выход %s", output)
                    self._on_output(output)

    def _fail_pending(self) -> None:
        with self._pending_lock:
            waiters, self._pending = list(self._pending.values()), {}
        for waiter in waiters:
            waiter[0].set()  # ответ None — запрос не выполнен

    def _set_status(self, connected: bool, error: str) -> None:
        if (connected, error) != (self.connected, self.error):
            self.connected, self.error = connected, error
            self._on_status(self.state())
