"""Поиск матов: корни из файла, совпадение по началу слова, регистр и ё/е."""

import pytest

from app import profanity
from app.profanity import count_profanity, load_words

# Как после load_words: корни уже нормализованы (нижний регистр, е вместо ё).
ROOTS = ("бля", "хрен", "ежик")


@pytest.fixture(autouse=True)
def _restore_roots(monkeypatch):
    # load_words меняет глобальный список корней; после теста возвращаем прежний.
    monkeypatch.setattr(profanity, "_roots", ())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("привет как дела", 0),
        ("бля", 1),
        ("блять блин бляха", 2),  # «блин» не начинается с «бля»
        ("БЛЯ Хреновый", 2),  # регистр не важен
        ("ну хрен, хрен!", 2),  # знаки препинания не мешают
        ("охренеть", 0),  # корень должен быть в начале слова
        ("ежики и ЁЖИКИ", 2),  # ё в тексте считается за е
    ],
)
def test_count_profanity(text, expected):
    assert count_profanity(text, ROOTS) == expected


def test_count_profanity_without_roots_is_zero():
    assert count_profanity("бля", ()) == 0
    assert count_profanity("бля") == 0  # корни ещё не загружены


def test_load_words_parses_file(tmp_path):
    path = tmp_path / "words.txt"
    # BOM от Блокнота, комментарии, пустые строки, пробелы, повторы, ё и верхний регистр.
    path.write_text(
        "﻿# маты\nбля\n\n   хрен  \n# ещё\nБЛЯ\nЁжик\n",
        encoding="utf-8",
    )
    assert load_words(path) == ("бля", "хрен", "ежик")


def test_load_words_sets_default_roots(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("хрен\n", encoding="utf-8")
    load_words(path)
    assert count_profanity("хрен с ним") == 1


def test_load_words_missing_file(tmp_path):
    assert load_words(tmp_path / "нет.txt") == ()
    assert count_profanity("бля") == 0
