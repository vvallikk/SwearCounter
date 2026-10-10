"""Настройки, выбранные на странице управления, с сохранением в settings.json."""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


class Settings:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._data = self._load()

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self._save()

    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            log.warning("Не удалось прочитать %s (%s), настройки по умолчанию", self._path, e)
            return {}

    def _save(self) -> None:
        # Как в counter.py: через временный файл, чтобы не получить битый json.
        tmp = self._path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as e:
            log.error("Не удалось сохранить настройки в %s: %s", self._path, e)
