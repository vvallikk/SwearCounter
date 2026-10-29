"""Звук оповещения: громкость и библиотека своих звуков со страницы управления.

Звуки лежат в папке sounds/, их список — в settings.json. Активен один звук
из библиотеки или стандартный (active = None).

На особом числе и цели (app/goals.py) играет отдельный звук (milestone): фанфары,
тот же, что обычно, стандартный звук пресета или любой из библиотеки.
"""

import logging
import uuid
from pathlib import Path

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
# Звук на особом числе, кроме id из библиотеки. Id в библиотеке — hex, с этими не совпадут.
MILESTONE_FANFARE = "fanfare"  # встроенные фанфары, как было раньше
MILESTONE_SAME = "same"  # тот же звук, что на каждом слове
MILESTONE_STANDARD = "standard"  # стандартный звук пресета
MILESTONE_SPECIAL = (MILESTONE_FANFARE, MILESTONE_SAME, MILESTONE_STANDARD)


class Sound:
    def __init__(self, settings: Settings, directory: Path):
        self.settings = settings
        self.directory = Path(directory)
        self._migrate()

    def state(self) -> dict:
        active = self.settings.get("sound_active")
        library = self._library()
        milestone = self.milestone()
        return {
            "volume": self.settings.get("sound_volume", DEFAULT_VOLUME),
            "active": active,
            "active_name": next((s["name"] for s in library if s["id"] == active), None),
            "sounds": [{"id": s["id"], "name": s["name"]} for s in library],
            "milestone": milestone,
            "milestone_name": next((s["name"] for s in library if s["id"] == milestone), None),
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
        if sound_id is not None and self._find(sound_id) is None:
            raise KeyError(sound_id)
        self.settings.set("sound_active", sound_id)
        self._bump_version()

    def milestone(self) -> str:
        """Звук на особом числе: одно из MILESTONE_SPECIAL или id из библиотеки."""
        value = self.settings.get("sound_milestone", MILESTONE_FANFARE)
        # Звук могли удалить вручную вместе с файлом — тогда снова фанфары.
        if value in MILESTONE_SPECIAL or self._find(value) is not None:
            return value
        return MILESTONE_FANFARE

    def select_milestone(self, value: str) -> None:
        """Выбирает звук на особом числе. KeyError — если такого нет."""
        if value not in MILESTONE_SPECIAL and self._find(value) is None:
            raise KeyError(value)
        self.settings.set("sound_milestone", value)
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
        if self.settings.get("sound_milestone") == sound_id:
            self.settings.set("sound_milestone", MILESTONE_FANFARE)
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
