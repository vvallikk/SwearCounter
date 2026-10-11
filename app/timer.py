"""Таймер «без мата»: сколько удалось продержаться с последнего слова и рекорд за сессию.

Сессия — с запуска программы или последнего сброса счёта. На паузе распознавания таймер
стоит: перерыв или катсцена не должны засчитываться как выдержка. Ничего не сохраняется.
"""

import time
from collections.abc import Callable


class NoSwearTimer:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._accumulated = 0.0  # выдержка до последней паузы
        self._running_since: float | None = clock()
        self.record = 0.0  # лучшая законченная серия

    @property
    def running(self) -> bool:
        return self._running_since is not None

    def elapsed(self) -> float:
        if self._running_since is None:
            return self._accumulated
        return self._accumulated + self._clock() - self._running_since

    def hit(self) -> None:
        """Прозвучало слово: серия закончилась, отсчёт с нуля."""
        self.record = max(self.record, self.elapsed())
        self._restart()

    def reset(self) -> None:
        """Сброс счёта начинает новую сессию: рекорд тоже обнуляется."""
        self.record = 0.0
        self._restart()

    def pause(self) -> None:
        if self._running_since is not None:
            self._accumulated = self.elapsed()
            self._running_since = None

    def resume(self) -> None:
        if self._running_since is None:
            self._running_since = self._clock()

    def _restart(self) -> None:
        self._accumulated = 0.0
        if self._running_since is not None:
            self._running_since = self._clock()

    def message(self) -> dict:
        """Состояние для клиентов: дальше они сами отсчитывают секунды, пока running."""
        return {
            "type": "timer",
            "elapsed": round(self.elapsed(), 1),
            "record": round(self.record, 1),
            "running": self.running,
        }
