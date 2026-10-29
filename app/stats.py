"""Статистика по сессиям: сколько слов и каких, с сохранением в stats.json.

Сессия — с запуска программы или сброса счёта. Она заводится при первом слове, поэтому
пустые запуски в историю не попадают. Слова хранятся корнями из списка, а не сказанными
формами; прибавки кнопкой «+1» и горячей клавишей идут в счёт сессии без слова.

Режим (настройка stats_mode) решает, что записывать: всё, только число слов в сессиях
(без самих слов) или ничего. Уже накопленная история от режима не зависит: она остаётся,
пока её не очистят.
"""

import csv
import io
import json
import logging
import os
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

MAX_SESSIONS = 500  # старые сессии отбрасываются, чтобы файл не рос бесконечно
RECENT_SESSIONS = 30  # столько последних сессий видно на странице управления
TOP_WORDS = 10

SETTING = "stats_mode"
# full — сессии и корни слов, count — сессии с числом слов, но без самих слов, off — ничего.
MODES = ("full", "count", "off")
DEFAULT_MODE = "full"


def clean_mode(value) -> str:
    """Режим из settings.json; испорченное значение — по умолчанию."""
    return value if value in MODES else DEFAULT_MODE


class Stats:
    def __init__(self, path: Path | None = None, clock: Callable[[], float] = time.time):
        """path=None — только в памяти (тесты)."""
        self._path = Path(path) if path is not None else None
        self._clock = clock
        self.sessions: list[dict] = self._load()
        self._current: dict | None = None  # текущая сессия, заводится при первом слове
        self.mode = DEFAULT_MODE

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(mode)
        self.mode = mode
        if mode == "off":
            # После включения слова пойдут в новую сессию, а не допишутся к прерванной.
            self._current = None

    def add(self, delta: int, words: list[str] = ()) -> None:
        if self.mode == "off":
            return
        if self.mode == "count":
            words = ()
        now = round(self._clock())
        if self._current is None:
            self._current = {"start": now, "end": now, "count": 0, "words": {}}
            self.sessions.append(self._current)
            del self.sessions[:-MAX_SESSIONS]
        session = self._current
        session["end"] = now
        session["count"] += delta
        for word in words:
            session["words"][word] = session["words"].get(word, 0) + 1
        self._save()

    def new_session(self) -> None:
        """Сброс счёта: следующие слова пойдут в новую сессию."""
        self._current = None

    def clear(self) -> None:
        self.sessions.clear()
        self._current = None
        self._save()

    def top_words(self, limit: int = TOP_WORDS) -> list[list]:
        total: Counter[str] = Counter()
        for session in self.sessions:
            total.update(session["words"])
        return [[word, n] for word, n in total.most_common(limit)]

    def state(self) -> dict:
        recent = self.sessions[-RECENT_SESSIONS:]
        return {
            "sessions": [{k: s[k] for k in ("start", "end", "count")} for s in recent],
            "top": self.top_words(),
            "total": sum(s["count"] for s in self.sessions),
            "session_count": len(self.sessions),
            "mode": self.mode,
        }

    def csv(self) -> str:
        """Таблица для Excel: разделитель «;», как ждёт русский Excel."""
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
        writer.writerow(["Начало", "Конец", "Минут", "Слов", "Какие слова"])
        for s in self.sessions:
            words = sorted(s["words"].items(), key=lambda item: (-item[1], item[0]))
            writer.writerow([
                _local_time(s["start"]),
                _local_time(s["end"]),
                round((s["end"] - s["start"]) / 60),
                s["count"],
                ", ".join(f"{word} {n}" for word, n in words),
            ])
        return out.getvalue()

    def _load(self) -> list[dict]:
        if self._path is None:
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [_clean_session(s) for s in data["sessions"]][-MAX_SESSIONS:]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
            log.warning("Не удалось прочитать %s (%s), статистика начнётся заново", self._path, e)
            return []

    def _save(self) -> None:
        if self._path is None:
            return
        # Как в counter.py: временный файл и замена, чтобы не получить битый json.
        tmp = self._path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps({"sessions": self.sessions}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as e:
            log.error("Не удалось сохранить статистику в %s: %s", self._path, e)


def _clean_session(s: dict) -> dict:
    """Сессия из файла; что-то не то — ValueError/TypeError, и файл не читается целиком."""
    words = {str(word): int(n) for word, n in s["words"].items()}
    return {"start": int(s["start"]), "end": int(s["end"]), "count": int(s["count"]), "words": words}


def _local_time(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
