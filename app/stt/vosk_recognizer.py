"""Распознавание речи с микрофона через Vosk (офлайн).

Сама модель работает в отдельном процессе (vosk_worker.py): так её загрузку
можно прервать мгновенно, а память освобождается сразу после завершения процесса.
"""

import asyncio
import logging
import multiprocessing
import time
from multiprocessing.process import BaseProcess
from pathlib import Path

from ..settings import Settings
from .base import OnText, Recognizer
from .vosk_worker import run_worker

log = logging.getLogger(__name__)

# Оценка скорости загрузки модели, пока её реальное время ещё не измерено.
# Замер: vosk-model-ru-0.42 (3.7 ГБ на диске) грузится ~95 с.
LOAD_BYTES_PER_SECOND = 40_000_000

# spawn — единственный способ запуска процессов на Windows; задаём явно,
# чтобы поведение не зависело от системы.
_mp = multiprocessing.get_context("spawn")


class VoskRecognizer(Recognizer):
    def __init__(
        self,
        on_text: OnText,
        model_path: Path,
        settings: Settings,
        device: int | str | None = None,
    ):
        super().__init__(on_text)
        self.model_path = Path(model_path)
        self.settings = settings
        self.device = device
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

    def _expected_load_seconds(self) -> float:
        saved = self.settings.get("load_seconds", {}).get(self.model_path.name)
        if saved:
            return saved
        size = sum(f.stat().st_size for f in self.model_path.rglob("*") if f.is_file())
        return max(size / LOAD_BYTES_PER_SECOND, 1.0)

    def _remember_load_seconds(self, seconds: float) -> None:
        load_seconds = dict(self.settings.get("load_seconds", {}))
        load_seconds[self.model_path.name] = round(seconds, 1)
        self.settings.set("load_seconds", load_seconds)

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

    async def run(self) -> None:
        self._load_expected = await asyncio.to_thread(self._expected_load_seconds)

        recv_conn, send_conn = _mp.Pipe(duplex=False)
        process = _mp.Process(
            target=run_worker,
            args=(send_conn, str(self.model_path), self.device),
            name=self.model_path.name,
            daemon=True,  # при выходе из программы процесс завершится вместе с ней
        )
        log.info("Загрузка модели Vosk в память: %s", self.model_path)
        self._load_started = time.monotonic()
        await asyncio.to_thread(process.start)
        # Свой экземпляр передающего конца закрываем: тогда при завершении
        # процесса recv() получит EOFError, а не будет ждать вечно.
        send_conn.close()
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
            await asyncio.to_thread(_terminate, process)

    async def _handle(self, message: tuple) -> None:
        kind, *data = message
        if kind == "text":
            await self.on_text(*data)
        elif kind == "loaded":
            # Считаем от запуска процесса: это время, которое реально ждёт пользователь.
            load_seconds = time.monotonic() - self._load_started
            log.info("Модель загружена за %.1f с", load_seconds)
            self._remember_load_seconds(load_seconds)
        elif kind == "listening":
            name, samplerate = data
            self.status = "listening"
            log.info("Слушаю микрофон: %s (%d Гц)", name, samplerate)
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
