"""Состояние счётчика с сохранением в counter.json."""

import asyncio
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


class Counter:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = asyncio.Lock()
        self._value = self._load()

    @property
    def value(self) -> int:
        return self._value

    async def add(self, delta: int = 1) -> int:
        async with self._lock:
            self._value += delta
            self._save()
            return self._value

    async def reset(self) -> int:
        async with self._lock:
            self._value = 0
            self._save()
            return self._value

    def _load(self) -> int:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return max(0, int(data["count"]))
        except FileNotFoundError:
            return 0
        except (OSError, ValueError, TypeError, KeyError) as e:
            log.warning("Не удалось прочитать %s (%s), начинаем с 0", self._path, e)
            return 0

    def _save(self) -> None:
        # Пишем во временный файл и заменяем, чтобы не получить битый json при сбое.
        tmp = self._path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps({"count": self._value}), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as e:
            log.error("Не удалось сохранить счётчик в %s: %s", self._path, e)
