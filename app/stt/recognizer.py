"""Распознавание речи с микрофона через Vosk (офлайн).

Сама модель работает в отдельном процессе (worker.py): так её загрузку
можно прервать мгновенно, а память освобождается сразу после завершения процесса.
"""

import asyncio
import logging
import multiprocessing
import time
from collections.abc import Awaitable, Callable
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path

from ..settings import Settings
from .base import OnText, Recognizer
from .catalog import find_model
from .cloud import clean_key
from .worker import run_worker

log = logging.getLogger(__name__)

# Оценка скорости загрузки модели, пока её реальное время ещё не измерено.
# Замер: vosk-model-ru-0.42 (3.7 ГБ на диске) грузится ~95 с.
LOAD_BYTES_PER_SECOND = 40_000_000

# spawn — единственный способ запуска процессов на Windows; задаём явно,
# чтобы поведение не зависело от системы.
_mp = multiprocessing.get_context("spawn")


class MicRecognizer(Recognizer):
    def __init__(
        self,
        on_text: OnText,
        model_path: Path,
        settings: Settings,
        device: int | str | None = None,
        on_level: Callable[[float], Awaitable[None]] | None = None,
    ):
        super().__init__(on_text)
        self.on_level = on_level  # громкость микрофона 0..1, примерно 10 раз в секунду
        self.model_path = Path(model_path)
        self.settings = settings
        self.device = device
        self.mic_name: str | None = None  # микрофон, который сейчас слушаем
        self.mic_error: str | None = None  # почему микрофон не открылся
        self.mic_pending = False  # смена микрофона отправлена, ответа ещё нет
        self.monitor = False  # звук микрофона выводится в динамики/наушники
        self.monitor_error: str | None = None
        self._commands: Connection | None = None
        self._load_started: float | None = None
        self._load_expected = 1.0

    @property
    def load_progress(self) -> float:
        """Оценка загрузки модели от 0 до 1.

        Vosk не сообщает о ходе загрузки, поэтому считаем по времени: сколько
        прошло от ожидаемой длительности (прошлой загрузки этой модели).
        """
        if self.status != "loading" or self._load_started is None:
            return 0.0
        elapsed = time.monotonic() - self._load_started
        return min(elapsed / self._load_expected, 0.99)

    def cloud_provider(self) -> str | None:
        """Сервис выбранной облачной модели; у локальной модели None."""
        model = find_model(self.model_path.name)
        return model.provider if model is not None and model.cloud else None

    def api_key(self) -> str | None:
        """Ключ сервиса выбранной облачной модели; None, если модель не облачная или ключа нет."""
        provider = self.cloud_provider()
        keys = self.settings.get("cloud_keys", {})
        if provider is None or not isinstance(keys, dict):
            return None
        return clean_key(keys.get(provider))

    def _saved_load_seconds(self) -> dict:
        saved = self.settings.get("load_seconds", {})
        return saved if isinstance(saved, dict) else {}  # файл могли испортить вручную

    def _expected_load_seconds(self) -> float:
        saved = self._saved_load_seconds().get(self.model_path.name)
        if isinstance(saved, (int, float)) and saved > 0:
            return saved
        size = sum(f.stat().st_size for f in self.model_path.rglob("*") if f.is_file())
        return max(size / LOAD_BYTES_PER_SECOND, 1.0)

    def _remember_load_seconds(self, seconds: float) -> None:
        load_seconds = dict(self._saved_load_seconds())
        load_seconds[self.model_path.name] = round(seconds, 1)
        self.settings.set("load_seconds", load_seconds)

    async def start(self) -> None:
        # Модель ещё не скачана (первый запуск): ждём, пока её выберут
        # на странице управления — тогда она скачается и запустится.
        if not self.model_path.is_dir():
            self.status = "no_model"
            return
        # Облачной модели нужен ключ сервиса: без него ждём, пока его введут.
        if self.cloud_provider() is not None and self.api_key() is None:
            self.status = "no_key"
            return
        await super().start()

    async def set_model(self, model_path: Path) -> None:
        """Перезапускает распознавание с другой моделью.

        Можно вызывать и во время загрузки: процесс с недогруженной моделью
        завершается сразу, и его память освобождается.
        """
        if self.status == "loading":
            log.info("Загрузка %s отменена", self.model_path.name)
        await self.stop()
        # Иначе до начала новой загрузки прогресс считался бы от старой (сразу 99%).
        self._load_started = None
        self.model_path = Path(model_path)
        await self.start()

    def set_device(self, device: int | str | None) -> None:
        """Переключает микрофон. Модель при этом не перезагружается.

        Прослушивание выключается: новый микрофон начинаем без него.
        """
        self.device = device
        self.monitor = False
        self.monitor_error = None
        if self._commands is not None:
            # Пока модель грузится, микрофон и так откроется после загрузки.
            self.mic_pending = self.status in ("listening", "mic_error")
            try:
                self._commands.send(("device", device))
            except OSError:
                pass  # процесс как раз завершается; новый возьмёт self.device

    def set_monitor(self, enabled: bool) -> None:
        """Включает или выключает прослушивание микрофона."""
        self.monitor_error = None
        if self._commands is None:
            return  # процесса ещё нет; прослушивание включают у работающего микрофона
        try:
            self._commands.send(("monitor", enabled))
        except OSError:
            pass

    async def run(self) -> None:
        self._load_expected = await asyncio.to_thread(self._expected_load_seconds)

        recv_conn, send_conn = _mp.Pipe(duplex=False)
        cmd_recv, cmd_send = _mp.Pipe(duplex=False)
        process = _mp.Process(
            target=run_worker,
            args=(send_conn, cmd_recv, str(self.model_path), self.device, self.api_key()),
            name=self.model_path.name,
            daemon=True,  # при выходе из программы процесс завершится вместе с ней
        )
        log.info("Загрузка модели в память: %s", self.model_path)
        self._load_started = time.monotonic()
        await asyncio.to_thread(process.start)
        # Свой экземпляр передающего конца закрываем: тогда при завершении
        # процесса recv() получит EOFError, а не будет ждать вечно.
        send_conn.close()
        cmd_recv.close()
        self._commands = cmd_send
        try:
            while True:
                try:
                    message = await asyncio.to_thread(recv_conn.recv)
                except EOFError:
                    raise RuntimeError(
                        f"Процесс распознавания неожиданно завершился (код {process.exitcode})"
                    ) from None
                await self._handle(message)
        finally:
            self._commands = None
            self.mic_name = None
            self.mic_pending = False
            self.monitor = False
            cmd_send.close()
            await asyncio.to_thread(_terminate, process)

    async def _handle(self, message: tuple) -> None:
        kind, *data = message
        if kind == "level":
            if self.on_level is not None:
                await self.on_level(data[0])
        elif kind == "text":
            await self.on_text(*data)
        elif kind == "loaded":
            # Считаем от запуска процесса: это время, которое реально ждёт пользователь.
            load_seconds = time.monotonic() - self._load_started
            log.info("Модель загружена за %.1f с", load_seconds)
            self._remember_load_seconds(load_seconds)
        elif kind == "listening":
            name, samplerate = data
            self.status = "listening"
            self.mic_name = name
            self.mic_error = None
            self.mic_pending = False
            log.info("Слушаю микрофон: %s (%d Гц)", name, samplerate)
        elif kind == "monitor":
            self.monitor, self.monitor_error = data
            if self.monitor_error:
                log.error("%s", self.monitor_error)
        elif kind == "mic_error":
            self.status = "mic_error"
            self.mic_name = None
            self.mic_error = data[0]
            self.mic_pending = False
            log.error("Микрофон: %s", data[0])
        elif kind == "error":
            raise RuntimeError(f"Ошибка в процессе распознавания:\n{data[0]}")


def _terminate(process: BaseProcess) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join()
    log.info("Процесс распознавания %s завершён", process.name)
