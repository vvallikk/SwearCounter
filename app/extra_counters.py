"""Дополнительные счётчики: например, слова-паразиты отдельно от матов.

У каждого свой список слов, свой счёт и своё оформление оверлея (/overlay/?counter=<id>).
Цели, таймер, статистика и связь с OBS остаются у основного счётчика.
Хранятся в counters.json; распознанный текст идёт в каждый счётчик через свой SwearTracker.
"""

import json
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import profanity
from .profanity import SwearTracker

log = logging.getLogger(__name__)

MAX_COUNTERS = 5
NAME_MAX_LENGTH = 40
DEFAULT_PRESET = "swearcounter"
DEFAULT_SCALE = 100  # размер числа и подписи, проценты
# Счётчик из файла без оформления был создан, когда по умолчанию было «Классика»: оставляем его таким.
LEGACY_PRESET = "classic"


class CounterError(ValueError):
    """Неверные данные счётчика; текст — для страницы управления."""


class ExtraCounters:
    def __init__(self, path: Path | None = None, list_path: Callable[[str], Path] | None = None):
        """path=None — только в памяти (тесты). list_path: id списка → файл (KeyError, если нет)."""
        self._path = Path(path) if path is not None else None
        self.list_path = list_path
        self._roots: dict[Path, tuple[tuple[int, int] | None, tuple[str, ...]]] = {}
        self._counters: list[dict] = self._load()

    def items(self) -> list[dict]:
        return [dict(c) for c in self._counters]

    def ids(self) -> list[str]:
        return [c["id"] for c in self._counters]

    def get(self, counter_id: str) -> dict:
        for counter in self._counters:
            if counter["id"] == counter_id:
                return counter
        raise KeyError(counter_id)

    def add(self, name: str, list_id: str) -> dict:
        if len(self._counters) >= MAX_COUNTERS:
            raise CounterError(f"Счётчиков не больше {MAX_COUNTERS}")
        numbers = [int(c["id"][1:]) for c in self._counters if c["id"][1:].isdigit()]
        counter = {
            "id": f"c{max(numbers, default=0) + 1}",
            "name": "",
            "list": "",
            "preset": DEFAULT_PRESET,
            "label": "",
            "scale": DEFAULT_SCALE,
            "count": 0,
        }
        self._apply(counter, {"name": name, "list": list_id})
        self._counters.append(counter)
        self._save()
        log.info("Добавлен счётчик %s (%s)", counter["id"], counter["list"])
        return dict(counter)

    def update(self, counter_id: str, **fields) -> dict:
        counter = self.get(counter_id)
        changed = dict(counter)
        self._apply(changed, {k: v for k, v in fields.items() if v is not None})
        counter.update(changed)
        self._save()
        return dict(counter)

    def remove(self, counter_id: str) -> None:
        self._counters.remove(self.get(counter_id))
        self._save()

    def add_count(self, counter_id: str, delta: int) -> int:
        counter = self.get(counter_id)
        counter["count"] = max(0, counter["count"] + delta)
        self._save()
        return counter["count"]

    def reset(self, counter_id: str) -> None:
        self.get(counter_id)["count"] = 0
        self._save()

    def find(self, counter_id: str, text: str) -> list[str]:
        """Корни из списка счётчика, найденные в тексте (как profanity.find_profanity)."""
        try:
            roots = self._list_roots(self.get(counter_id)["list"])
        except KeyError:
            return []
        return profanity.find_profanity(text, roots) if roots else []

    def _list_roots(self, list_id: str) -> tuple[str, ...]:
        if self.list_path is None:
            raise KeyError(list_id)
        path = self.list_path(list_id)
        # Список правят, не закрывая программу: перечитываем, когда файл изменился.
        stamp = profanity._file_stamp(path)
        cached = self._roots.get(path)
        if cached is not None and (cached[0] == stamp or stamp is None):
            return cached[1]
        try:
            roots = profanity.read_roots(path)
        except OSError as e:
            log.error("Не удалось прочитать список слов %s: %s", path, e)
            roots = ()
        self._roots[path] = (stamp, roots)
        return roots

    def _apply(self, counter: dict, fields: dict) -> None:
        """Проверяет и записывает поля в counter; CounterError — если что-то не так."""
        if "name" in fields:
            name = " ".join(str(fields["name"]).split())
            if not name:
                raise CounterError("Введите название счётчика")
            if len(name) > NAME_MAX_LENGTH:
                raise CounterError(f"Название длиннее {NAME_MAX_LENGTH} символов")
            counter["name"] = name
        if "list" in fields:
            if self.list_path is not None:
                try:
                    self.list_path(fields["list"])
                except KeyError:
                    raise CounterError("Такого списка нет") from None
            counter["list"] = fields["list"]
        if "preset" in fields:
            counter["preset"] = fields["preset"]
        if "label" in fields:
            counter["label"] = fields["label"]
        if "scale" in fields:
            counter["scale"] = fields["scale"]

    def _load(self) -> list[dict]:
        if self._path is None:
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            counters = []
            for item in data["counters"][:MAX_COUNTERS]:
                counters.append({
                    "id": str(item["id"]),
                    "name": str(item["name"])[:NAME_MAX_LENGTH],
                    "list": str(item["list"]),
                    "preset": str(item.get("preset") or LEGACY_PRESET),
                    "label": str(item.get("label") or ""),
                    "scale": int(item.get("scale") or DEFAULT_SCALE),
                    "count": max(0, int(item.get("count", 0))),
                })
            return counters
        except FileNotFoundError:
            return []
        except (OSError, ValueError, TypeError, KeyError) as e:
            log.warning("Не удалось прочитать %s (%s), дополнительных счётчиков нет", self._path, e)
            return []

    def _save(self) -> None:
        if self._path is None:
            return
        tmp = self._path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps({"counters": self._counters}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as e:
            log.error("Не удалось сохранить счётчики в %s: %s", self._path, e)


class ExtraTrackers:
    """По SwearTracker на каждый дополнительный счётчик; набор следует за списком счётчиков."""

    def __init__(
        self,
        counters: ExtraCounters,
        add: Callable[[str, list[str]], Awaitable[object]],
        paused: Callable[[], bool] = lambda: False,
    ):
        self.counters = counters
        self.add = add  # add(id счётчика, найденные корни)
        self.paused = paused
        self._trackers: dict[str, SwearTracker] = {}

    async def feed(self, text: str, is_final: bool) -> None:
        ids = self.counters.ids()
        for gone in set(self._trackers) - set(ids):
            self._trackers.pop(gone).stop()
        for counter_id in ids:
            tracker = self._trackers.get(counter_id)
            if tracker is None:
                tracker = self._trackers[counter_id] = SwearTracker(
                    lambda words, cid=counter_id: self.add(cid, words),
                    find=lambda text, cid=counter_id: self.counters.find(cid, text),
                    paused=self.paused,
                )
            await tracker.feed(text, is_final)
