"""Временные события (Хеллоуин и т. п.): включаются сами в свои даты и пропадают после.

Всё, что относится к событию, помечено его id: оформление оверлея с полем event в
overlay/presets.js, звуки в overlay/sounds/<id>/, стили страницы управления под
[data-event="<id>"]. Когда окно дат прошло, ничего из этого не показывается и не играет,
выбранные оформление и звук сами сменяются на обычные. Удалить файлы события из
репозитория можно в любой момент после окончания: код без них работает.

Выключить событие раньше: переключатель на странице управления или в settings.json
"events_off": ["halloween"].
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import date

from .settings import Settings

log = logging.getLogger(__name__)

# Подменить сегодняшнюю дату, чтобы посмотреть событие вне его окна (для разработки):
# SWEARCOUNTER_EVENT_DATE=2026-10-31
DATE_ENV = "SWEARCOUNTER_EVENT_DATE"


def today() -> date:
    raw = os.environ.get(DATE_ENV)
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            log.warning("Неверная дата в %s: %s", DATE_ENV, raw)
    return date.today()


@dataclass(frozen=True)
class EventSound:
    id: str  # "<событие>:<имя>"
    name: str
    file: str | None  # путь от overlay/sounds/; None — случайный из остальных звуков события


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    start: tuple[int, int]  # (месяц, день), включительно
    end: tuple[int, int]  # (месяц, день), включительно
    preset: str  # оформление оверлея, которое есть только во время события
    sounds: tuple[EventSound, ...] = field(default=())
    curse_every: int = 0  # каждое N-е ругательство — «проклятие» (0 — нет)

    def in_window(self, day: date) -> bool:
        return self.start <= (day.month, day.day) <= self.end

    def last_day(self, day: date) -> date:
        return date(day.year, *self.end)


HALLOWEEN = Event(
    id="halloween",
    title="Хеллоуин",
    start=(10, 15),
    end=(11, 1),
    preset="halloween",
    sounds=(
        EventSound("halloween:random", "🎃 Случайный скример", None),
        EventSound("halloween:ghost", "👻 Визг призрака", "halloween/ghost-shriek.ogg"),
        EventSound("halloween:hit", "💥 Удар-скример", "halloween/jumpscare-hit.ogg"),
        EventSound("halloween:hit-low", "💥 Удар-скример (низкий)", "halloween/jumpscare-low.ogg"),
        EventSound("halloween:moan", "👻 Стон призрака", "halloween/ghost-moan.ogg"),
        EventSound("halloween:witch", "🧙 Смех ведьмы", "halloween/witch-cackle.ogg"),
        EventSound("halloween:laugh", "😈 Злой смех", "halloween/evil-laugh.ogg"),
        EventSound("halloween:demon", "😈 Демонический хохот", "halloween/demon-laugh.ogg"),
        EventSound("halloween:door", "🚪 Скрип двери", "halloween/door-creak.ogg"),
    ),
    curse_every=13,
)

EVENTS = (HALLOWEEN,)
EVENT_PRESETS = {e.preset: e for e in EVENTS}


class Events:
    def __init__(self, settings: Settings, events: tuple[Event, ...] = EVENTS):
        self.settings = settings
        self.events = events

    def _off(self) -> set[str]:
        off = self.settings.get("events_off", [])
        return set(off) if isinstance(off, list) else set()

    def active(self) -> list[Event]:
        """События, которые идут сегодня и не выключены."""
        day = today()
        off = self._off()
        return [e for e in self.events if e.in_window(day) and e.id not in off]

    def active_ids(self) -> list[str]:
        return [e.id for e in self.active()]

    def set_enabled(self, event_id: str, enabled: bool) -> None:
        """KeyError — если такого события нет."""
        if not any(e.id == event_id for e in self.events):
            raise KeyError(event_id)
        off = self._off()
        if enabled:
            off.discard(event_id)
        else:
            off.add(event_id)
        self.settings.set("events_off", sorted(off))

    def state(self) -> dict:
        """Для страницы управления: идущие события, их окно дат и включены ли они."""
        day = today()
        off = self._off()
        return {
            "active": self.active_ids(),
            # Выключенное, но идущее событие тоже показываем: его можно включить обратно.
            "events": [
                {"id": e.id, "title": e.title, "until": e.last_day(day).isoformat(), "enabled": e.id not in off}
                for e in self.events
                if e.in_window(day)
            ],
        }

    def preset_available(self, preset_id: str) -> bool:
        """Оформление события есть, только пока событие идёт; остальные — всегда."""
        event = EVENT_PRESETS.get(preset_id)
        return event is None or event in self.active()

    def sounds(self) -> list[EventSound]:
        return [s for e in self.active() for s in e.sounds]

    def find_sound(self, sound_id: str) -> EventSound | None:
        return next((s for s in self.sounds() if s.id == sound_id), None)

    def curse(self, before: int, count: int) -> bool:
        """Счёт перешёл через кратное N во время события — «проклятие» (13, 26, 39…)."""
        return any(e.curse_every and before // e.curse_every < count // e.curse_every for e in self.active())
