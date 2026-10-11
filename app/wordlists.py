"""Списки слов для подсчёта: .txt-файлы в папке wordlists/, активен один из них.

Встроенные списки лежат в ресурсах программы. При запуске недостающие копируются
в wordlists/ рядом с exe: там их можно править и класть рядом свои. Обновление
программы эту папку не трогает, а новые встроенные списки появятся при запуске.
Название списка для окна программы — строка «# Название: ...» в начале файла.
"""

import logging
import re
import shutil
from pathlib import Path

from . import profanity
from .settings import Settings

log = logging.getLogger(__name__)

DEFAULT_LIST = "swears.txt"
_NAME_RE = re.compile(r"#\s*Название:\s*(.+)", re.IGNORECASE)
_NAME_LINES = 5  # название ищем только в начале файла

# words.txt версий до 1.0.0: один список рядом с exe (см. migrate_words_file).
PLACEHOLDER_ROOTS = {"тестслов", "проверк"}  # тестовые корни, поставлявшиеся вместо матов
MIGRATED_LIST = "my.txt"
MIGRATED_NAME = "Мой список (из words.txt)"


class WordLists:
    def __init__(self, settings: Settings, directory: Path, bundled: Path):
        self.settings = settings
        self.directory = Path(directory)
        self.bundled = Path(bundled)

    def prepare(self, old_words: Path | None = None) -> None:
        """Раскладывает встроенные списки, переносит старый words.txt и загружает активный."""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            if self.bundled.resolve() != self.directory.resolve():
                for source in sorted(self.bundled.glob("*.txt")):
                    target = self.directory / source.name
                    if not target.exists():
                        shutil.copy2(source, target)
        except OSError as e:
            log.error("Не удалось подготовить списки слов в %s: %s", self.directory, e)
        if old_words is not None:
            migrated = migrate_words_file(old_words, self.directory)
            if migrated is not None:
                self.settings.set("word_list", migrated)
        profanity.load_words(self.directory / self.active())

    def lists(self) -> list[dict]:
        result = []
        for path in sorted(self.directory.glob("*.txt"), key=lambda p: p.name.lower()):
            try:
                text = path.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            result.append({"id": path.name, "name": _list_name(text, path), "words": _count_roots(text)})
        return result

    def active(self) -> str:
        """Выбранный список; если его файл удалили — встроенный по умолчанию или первый."""
        ids = [entry["id"] for entry in self.lists()]
        for candidate in (self.settings.get("word_list"), DEFAULT_LIST):
            if candidate in ids:
                return candidate
        return ids[0] if ids else DEFAULT_LIST

    def path(self, list_id: str) -> Path:
        """Файл списка; KeyError, если такого нет (id приходит со страницы, проверяем строго)."""
        if list_id not in {entry["id"] for entry in self.lists()}:
            raise KeyError(list_id)
        return self.directory / list_id

    def select(self, list_id: str) -> None:
        path = self.path(list_id)
        self.settings.set("word_list", list_id)
        log.info("Выбран список слов: %s", list_id)
        profanity.load_words(path)

    def state(self) -> dict:
        return {"lists": self.lists(), "active": self.active()}


def _list_name(text: str, path: Path) -> str:
    for line in text.splitlines()[:_NAME_LINES]:
        match = _NAME_RE.fullmatch(line.strip())
        if match:
            return match.group(1).strip()
    return path.stem


def _count_roots(text: str) -> int:
    lines = (line.strip() for line in text.splitlines())
    return len({profanity.normalize(line) for line in lines if line and not line.startswith("#")})


def migrate_words_file(old: Path, directory: Path) -> str | None:
    """Переносит words.txt версий до 1.0.0 в папку списков.

    Заглушку (тестовые корни) просто удаляет. Список, который пользователь правил сам,
    становится отдельным списком my.txt; возвращает его id, чтобы сделать активным.
    """
    try:
        text = old.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError as e:
        log.error("Не удалось прочитать старый список слов %s: %s", old, e)
        return None
    target = directory / MIGRATED_LIST
    try:
        if set(profanity.read_roots(old)) == PLACEHOLDER_ROOTS:
            old.unlink()
            log.info("Удалён старый список-заглушка %s", old)
            return None
        if target.exists():
            return None
        target.write_text(f"# Название: {MIGRATED_NAME}\n{text}", encoding="utf-8")
        old.unlink()
    except OSError as e:
        log.error("Не удалось перенести старый список слов %s: %s", old, e)
        return None
    log.info("Старый список слов перенесён в %s", target)
    return MIGRATED_LIST
