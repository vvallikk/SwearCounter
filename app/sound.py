"""Звук оповещения: громкость и библиотека своих звуков со страницы управления.

Звуки лежат в папке sounds/, их список — в settings.json. Активен один звук
из библиотеки или стандартный (active = None). Во время события (app/events.py)
можно выбрать и его встроенные звуки; после события выбранный звук события
сам сменяется на стандартный.

Режим «рандом»: на каждый мат играет случайный звук из отмеченных (sound_pool).
"""

import logging
import uuid
from pathlib import Path

from .events import Events
from .settings import Settings

log = logging.getLogger(__name__)

MAX_SOUND_BYTES = 5 * 1024 * 1024
MAX_SOUNDS = 30  # больше в списке неудобно, а место на диске не бесконечное
# Форматы, которые точно проигрывает браузер OBS (Chromium).
SOUND_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/ogg": ".ogg",
}
DEFAULT_VOLUME = 100
STANDARD_ID = "standard"  # стандартный звук в списке режима «рандом»


class Sound:
    def __init__(self, settings: Settings, directory: Path, events: Events | None = None):
        self.settings = settings
        self.directory = Path(directory)
        self.events = events
        self._migrate()

    def _event_sounds(self) -> list[dict]:
        if self.events is None:
            return []
        return [{"id": s.id, "name": s.name, "url": f"/overlay/sounds/{s.file}"} for s in self.events.sounds()]

    def state(self) -> dict:
        active = self.settings.get("sound_active")
        library = self._library()
        event_sounds = self._event_sounds()
        names = {s["id"]: s["name"] for s in library + event_sounds}
        if active not in names:
            active = None  # файл удалили вручную или событие закончилось
        # Отмеченные для «рандома»: удалённые звуки и звуки прошедшего события пропадают сами.
        pool = [i for i in self.settings.get("sound_pool", []) if i in names or i == STANDARD_ID]
        return {
            "volume": self.settings.get("sound_volume", DEFAULT_VOLUME),
            "active": active,
            "active_name": names.get(active),
            "sounds": [{"id": s["id"], "name": s["name"]} for s in library],
            # Звуки идущего события: url — файл, null — случайный из остальных.
            "event_sounds": event_sounds,
            "random": bool(self.settings.get("sound_random", False)),
            "pool": pool,
            # Меняется при каждой смене звука, чтобы оверлей не взял старый из кэша.
            "version": self.settings.get("sound_version", 0),
        }

    def set_volume(self, volume: int) -> None:
        self.settings.set("sound_volume", max(0, min(100, int(volume))))

    def path(self, sound_id: str) -> Path | None:
        entry = self._find(sound_id)
        if entry is None:
            return None
        path = self.directory / entry["file"]
        return path if path.is_file() else None

    def add(self, data: bytes, content_type: str, name: str) -> str:
        """Добавляет звук в библиотеку и делает его активным. ValueError — если не подходит."""
        extension = SOUND_TYPES.get(content_type.split(";")[0].strip().lower())
        if extension is None:
            raise ValueError("Поддерживаются файлы MP3, WAV и OGG")
        if not data:
            raise ValueError("Файл пустой")
        if len(data) > MAX_SOUND_BYTES:
            raise ValueError(f"Файл больше {MAX_SOUND_BYTES // (1024 * 1024)} МБ")
        library = self._library()
        if len(library) >= MAX_SOUNDS:
            raise ValueError(f"В библиотеке уже {MAX_SOUNDS} звуков: удалите ненужные")
        sound_id = uuid.uuid4().hex[:12]
        file = sound_id + extension
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / file).write_bytes(data)
        library.append({"id": sound_id, "file": file, "name": name or file})
        self.settings.set("sound_library", library)
        self.select(sound_id)
        log.info("Добавлен звук: %s (%d КБ)", name, len(data) // 1024)
        return sound_id

    def select(self, sound_id: str | None) -> None:
        """Делает звук активным; None — стандартный. KeyError — если такого нет."""
        event_sound = self.events is not None and sound_id is not None and self.events.find_sound(sound_id)
        if sound_id is not None and self._find(sound_id) is None and not event_sound:
            raise KeyError(sound_id)
        self.settings.set("sound_active", sound_id)
        self._bump_version()

    def set_random(self, enabled: bool, pool: list[str]) -> None:
        """Режим «рандом» и отмеченные звуки. KeyError — если такого звука нет."""
        known = {s["id"] for s in self._library()} | {s["id"] for s in self._event_sounds()} | {STANDARD_ID}
        for sound_id in pool:
            if sound_id not in known:
                raise KeyError(sound_id)
        self.settings.set("sound_random", bool(enabled))
        self.settings.set("sound_pool", list(dict.fromkeys(pool)))  # без повторов, в том же порядке
        self._bump_version()

    def delete(self, sound_id: str) -> None:
        """Удаляет звук; если он был активным, включается стандартный. KeyError — если нет."""
        entry = self._find(sound_id)
        if entry is None:
            raise KeyError(sound_id)
        (self.directory / entry["file"]).unlink(missing_ok=True)
        self.settings.set("sound_library", [s for s in self._library() if s["id"] != sound_id])
        if self.settings.get("sound_active") == sound_id:
            self.settings.set("sound_active", None)
        self._bump_version()
        log.info("Удалён звук: %s", entry["name"])

    def _library(self) -> list[dict]:
        # Записи, чьи файлы удалили вручную, не показываем.
        return [
            s for s in self.settings.get("sound_library", []) if (self.directory / s["file"]).is_file()
        ]

    def _find(self, sound_id: str) -> dict | None:
        return next((s for s in self._library() if s["id"] == sound_id), None)

    def _bump_version(self) -> None:
        self.settings.set("sound_version", self.settings.get("sound_version", 0) + 1)

    def _migrate(self) -> None:
        """Переносит единственный «свой звук» из прежней версии в библиотеку."""
        old = self.settings.get("sound_custom")
        if not old:
            return
        if (self.directory / old["file"]).is_file():
            sound_id = uuid.uuid4().hex[:12]
            library = self.settings.get("sound_library", [])
            library.append({"id": sound_id, "file": old["file"], "name": old["name"]})
            self.settings.set("sound_library", library)
            self.settings.set("sound_active", sound_id)
        self.settings.set("sound_custom", None)
