"""Поиск матов в распознанном тексте по списку корней из words.txt."""

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\w+")

# Корни, загруженные load_words(); используются count_profanity по умолчанию.
_roots: tuple[str, ...] = ()


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def load_words(path: Path) -> tuple[str, ...]:
    """Читает корни из файла: по одному на строку, пустые строки и # пропускаются."""
    global _roots
    roots = []
    try:
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                roots.append(normalize(line))
    except OSError as e:
        log.error("Не удалось прочитать список слов %s: %s", path, e)
    _roots = tuple(dict.fromkeys(roots))  # без повторов, порядок сохраняем
    log.info("Загружено корней: %d (%s)", len(_roots), path)
    return _roots


def count_profanity(text: str, roots: tuple[str, ...] | None = None) -> int:
    """Количество слов в тексте, начинающихся с одного из корней."""
    roots = _roots if roots is None else tuple(roots)
    if not roots:
        return 0
    words = _WORD_RE.findall(normalize(text))
    return sum(1 for word in words if word.startswith(roots))
