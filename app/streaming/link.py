"""Основа постоянной связи с платформой: поток, повтор подключений, статус.

Связь живёт в своём потоке (как app/obs_link.py): сеть синхронная, а чат может быть
недоступен часами. Выключенная платформа не подключается вовсе.
"""

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

RETRY = 15.0  # пауза перед новой попыткой после ошибки

OFF, CONNECTING, CONNECTED, ERROR = "off", "connecting", "connected", "error"


class LinkError(Exception):
    """Подключиться не получилось; текст показывается пользователю."""

    def __init__(self, message: str, retry: float | None = None):
        super().__init__(message)
        self.retry = retry  # None — обычная пауза RETRY


class Link:
    name = "link"

    def __init__(self, on_status: Callable[[str, dict], None] = lambda name, state: None, retry: float = RETRY):
        self._on_status = on_status
        self._retry = retry
        self._config = None  # None — выключено
        self._changed = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self.status = OFF
        self.error = ""

    def state(self) -> dict:
        return {"status": self.status, "error": self.error if self.status == ERROR else ""}

    @property
    def connected(self) -> bool:
        return self.status == CONNECTED

    def configure(self, config) -> None:
        """config — любое сравнимое значение (кортеж, dict); None выключает связь."""
        if config != self._config:
            self._config = config
            self._changed.set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"{self.name}-link", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._changed.set()
        if self._thread is not None:
            self._thread.join(5)

    def _session(self, config) -> None:
        """Одно подключение: возвращается, когда изменились настройки или связь остановлена.

        Бросает LinkError, если подключение оборвалось или не удалось.
        """
        raise NotImplementedError

    def _should_stop(self) -> bool:
        return self._changed.is_set() or self._stopping.is_set()

    def _run(self) -> None:
        while not self._stopping.is_set():
            self._changed.clear()
            config = self._config
            if config is None:
                self._set_status(OFF, "")
                self._changed.wait()
                continue
            self._set_status(CONNECTING, "")
            pause = self._retry
            try:
                self._session(config)
            except LinkError as e:
                self._set_status(ERROR, str(e))
                pause = e.retry if e.retry is not None else self._retry
            except OSError as e:
                self._set_status(ERROR, f"Нет связи: {e}")
            except Exception:  # noqa: BLE001 любой сбой не должен убивать поток связи
                log.exception("Сбой связи %s", self.name)
                self._set_status(ERROR, "Внутренняя ошибка, подробности в журнале")
            else:
                continue  # настройки изменились или остановка: сразу по новому кругу
            self._changed.wait(pause)

    def _set_status(self, status: str, error: str) -> None:
        if (status, error) != (self.status, self.error):
            self.status, self.error = status, error
            if status == ERROR:
                log.info("%s: %s", self.name, error)
            self._on_status(self.name, self.state())
