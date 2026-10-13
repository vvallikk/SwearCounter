"""Хайлайты: метка на каждое засчитанное слово и таймкоды относительно начала эфира.

Каждое слово оставляет метку с временем. Из меток собираются «моменты» (слова подряд
с паузой не больше CLUSTER_GAP секунд сливаются в один) и таймкоды для описания видео на
YouTube или таблицы CSV. Отсчёт идёт от начала трансляции или записи OBS, если связь с OBS
знает, когда они начались, иначе от начала таймлайна (запуск программы или «Начать заново»).

Хранятся только время и корень слова из списка (как в статистике), но не звук и не речь.
Расшифровка не хранится: слово, как его произнесли, программа не знает.
"""

import csv
import io
import json
import logging
import os
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

MAX_MARKS = 5000  # старые метки отбрасываются, чтобы файл не рос бесконечно
CLUSTER_GAP = 10.0  # слова ближе друг к другу, чем на столько секунд, — один момент
MAX_LEAD = 30  # на сколько секунд раньше слова можно ставить таймкод
DEFAULT_LEAD = 3
MAX_MOMENTS = 100  # столько последних моментов видно на странице управления
CLIP_COOLDOWN = 10.0  # не чаще раза в столько секунд сохраняем клип в OBS
CHAPTER_COOLDOWN = 5.0
CLIP_SETTLE = 1.5  # столько секунд OBS дописывает файл клипа после SaveReplayBuffer
BASES = ("stream", "record", "start")  # от чего считать таймкоды
LABEL = "Слово"


class HighlightsError(ValueError):
    pass


def clean_options(saved) -> dict:
    """Настройки хайлайтов; испорченное значение — выключено."""
    saved = saved if isinstance(saved, dict) else {}
    return {key: saved.get(key) is True for key in ("obs", "chapter", "clip")}


def link_needed(options: dict) -> bool:
    """Нужна ли связь с OBS: таймкоды от начала эфира, главы в записи или клипы."""
    return any(options.values())


def format_time(seconds: float) -> str:
    """«1:05» или «1:02:03», как принимают главы YouTube."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def clean_lead(lead: int) -> int:
    if not 0 <= lead <= MAX_LEAD:
        raise HighlightsError(f"Таймкод можно сдвинуть на 0…{MAX_LEAD} секунд раньше слова")
    return lead


def clean_base(base: str) -> str:
    if base not in BASES:
        raise HighlightsError("Отсчёт — от трансляции, записи или начала таймлайна")
    return base


class Timeline:
    def __init__(self, path: Path | None = None, clock: Callable[[], float] = time.time):
        """path=None — только в памяти (тесты)."""
        self._path = Path(path) if path is not None else None
        self._clock = clock
        self.marks: list[dict] = []
        self.anchors: dict[str, float] = {}  # "stream"/"record" → когда начался эфир
        self.origin = self._clock()
        self._load()

    def add(self, delta: int, words: list[str] = ()) -> dict | None:
        """Метка на прибавку; None — убавили счёт, метка не нужна."""
        if delta <= 0:
            return None
        mark = {"at": round(self._clock(), 2), "n": delta, "words": list(dict.fromkeys(words))}
        self.marks.append(mark)
        del self.marks[:-MAX_MARKS]
        self._save()
        return mark

    def set_clip(self, mark: dict, path: str) -> None:
        mark["clip"] = path
        self._save()

    def set_anchor(self, kind: str, at: float | None = None) -> None:
        """Эфир (stream | record) начался в момент at, по умолчанию — сейчас."""
        if kind in ("stream", "record"):
            self.anchors[kind] = self._clock() if at is None else at
            self._save()

    def restart(self) -> None:
        """Начать заново: метки стираются, отсчёт без OBS — с этого момента."""
        self.marks.clear()
        self.anchors.clear()
        self.origin = self._clock()
        self._save()

    def bases(self) -> dict[str, float]:
        """Доступные начала отсчёта: когда начался каждый."""
        return {**self.anchors, "start": self.origin}

    def moments(self, base: str, lead: int = DEFAULT_LEAD) -> list[dict]:
        """Моменты от начала base: время в секундах, число слов, слова и клипы."""
        start = self.bases().get(base)
        if start is None:
            return []
        result: list[dict] = []
        for mark in self.marks:
            offset = mark["at"] - start
            if offset < -0.05:  # запас на округление времени метки
                continue  # метка из прошлого эфира
            offset = max(offset, 0.0)
            if result and offset - result[-1]["last"] <= CLUSTER_GAP:
                moment = result[-1]
                moment["last"] = offset
                moment["count"] += mark["n"]
            else:
                moment = {"first": offset, "last": offset, "count": mark["n"], "words": Counter(), "clips": []}
                result.append(moment)
            moment["words"].update(mark["words"])
            if mark.get("clip") and mark["clip"] not in moment["clips"]:
                moment["clips"].append(mark["clip"])
        previous_last = 0.0
        for moment in result:
            # Таймкод идёт раньше слова, но не залезает на прошлый момент.
            moment["time"] = max(moment["first"] - lead, previous_last, 0.0)
            previous_last = moment["last"]
            moment["words"] = [word for word, _ in moment["words"].most_common()]
        return result

    def state(self, lead: int = DEFAULT_LEAD) -> dict:
        bases = self.bases()
        preferred = max(self.anchors, key=self.anchors.get) if self.anchors else "start"  # последний эфир
        moments = self.moments(preferred, lead)
        return {
            "marks": len(self.marks),
            "bases": {name: round(at) for name, at in bases.items()},
            "base": preferred,
            "moments": [
                {k: (round(v, 1) if isinstance(v, float) else v) for k, v in m.items() if k != "last"}
                for m in moments[-MAX_MOMENTS:]
            ],
        }

    def chapters(self, base: str, lead: int = DEFAULT_LEAD, label: str = LABEL) -> str:
        """Таймкоды для описания видео: «0:00 Начало», «1:23 Слово ×3: блин, чёрт»."""
        lines = []
        moments = self.moments(base, lead)
        if moments and moments[0]["time"] >= 1:
            lines.append("0:00 Начало")  # YouTube требует, чтобы главы начинались с 0:00
        for m in moments:
            line = f"{format_time(m['time'])} {label}"
            if m["count"] > 1:
                line += f" ×{m['count']}"
            if m["words"]:
                line += ": " + ", ".join(m["words"][:5])
            lines.append(line)
        return "\n".join(lines)

    def csv(self, base: str, lead: int = DEFAULT_LEAD) -> str:
        """Таблица для Excel: разделитель «;», как ждёт русский Excel."""
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
        writer.writerow(["Время", "Секунд", "Слов", "Какие слова", "Клипы"])
        for m in self.moments(base, lead):
            writer.writerow(
                [format_time(m["time"]), round(m["time"]), m["count"], ", ".join(m["words"]), " | ".join(m["clips"])]
            )
        return out.getvalue()

    def _load(self) -> None:
        if self._path is None:
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            marks = [_clean_mark(m) for m in data["marks"]][-MAX_MARKS:]
            anchors = {k: float(v) for k, v in data["anchors"].items() if k in ("stream", "record")}
            origin = float(data["origin"])
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
            log.warning("Не удалось прочитать %s (%s), хайлайты начнутся заново", self._path, e)
            return
        self.marks, self.anchors, self.origin = marks, anchors, origin

    def _save(self) -> None:
        if self._path is None:
            return
        # Как в stats.py: временный файл и замена, чтобы не получить битый json.
        tmp = self._path.with_suffix(".json.tmp")
        data = {"origin": self.origin, "anchors": self.anchors, "marks": self.marks}
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as e:
            log.error("Не удалось сохранить хайлайты в %s: %s", self._path, e)


def _clean_mark(m: dict) -> dict:
    mark = {"at": float(m["at"]), "n": int(m["n"]), "words": [str(w) for w in m["words"]]}
    if isinstance(m.get("clip"), str):
        mark["clip"] = m["clip"]
    return mark
