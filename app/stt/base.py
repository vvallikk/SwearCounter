"""Базовый интерфейс распознавателя речи."""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

# on_text(text, is_final): промежуточный (is_final=False) или окончательный результат.
OnText = Callable[[str, bool], Awaitable[None]]


class Recognizer(ABC):
    """Распознаватель речи, работающий в фоне и отдающий текст через on_text.

    Наследник реализует run(): бесконечный цикл, который получает текст
    и вызывает `await self.on_text(text, is_final)`.

    Реализация: VoskRecognizer (микрофон, модель в отдельном процессе).
    """

    def __init__(self, on_text: OnText):
        self.on_text = on_text
        self._task: asyncio.Task | None = None
        # Для страницы управления: stopped, loading, listening или error.
        self.status = "stopped"

    async def start(self) -> None:
        if self._task is None:
            self.status = "loading"
            self._task = asyncio.create_task(self._run_safe())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.status = "stopped"

    async def _run_safe(self) -> None:
        try:
            await self.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.status = "error"
            log.exception("Распознаватель остановился из-за ошибки")

    @abstractmethod
    async def run(self) -> None:
        """Основной цикл распознавания. Работает до отмены задачи."""
