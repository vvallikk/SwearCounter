"""Поиск матов: корни из файла, совпадение по началу слова, регистр и ё/е."""

import os

import pytest

from app import profanity
from app.profanity import count_profanity, load_words

# Как после load_words: корни уже нормализованы (нижний регистр, е вместо ё).
ROOTS = ("бля", "хрен", "ежик")


@pytest.fixture(autouse=True)
def _restore_roots(monkeypatch):
    # load_words меняет глобальный список корней; после теста возвращаем прежний.
    monkeypatch.setattr(profanity, "_roots", ())
    monkeypatch.setattr(profanity, "_source", None)
    monkeypatch.setattr(profanity, "_stamp", None)


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


def _rewrite(path, text):
    # Меняем и содержимое, и время изменения: на быстрых ФС mtime может не успеть сдвинуться.
    path.write_text(text, encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def test_words_reloaded_after_file_change(tmp_path, monkeypatch):
    monkeypatch.setattr(profanity, "RELOAD_CHECK_SECONDS", 0)
    path = tmp_path / "words.txt"
    path.write_text("бля\n", encoding="utf-8")
    load_words(path)
    assert count_profanity("хрен") == 0
    _rewrite(path, "бля\nхрен\n")
    assert count_profanity("хрен") == 1


def test_words_not_rechecked_too_often(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("бля\n", encoding="utf-8")
    load_words(path)
    _rewrite(path, "хрен\n")
    assert count_profanity("хрен") == 0  # секунда ещё не прошла


def test_deleted_words_file_keeps_old_list(tmp_path, monkeypatch):
    monkeypatch.setattr(profanity, "RELOAD_CHECK_SECONDS", 0)
    path = tmp_path / "words.txt"
    path.write_text("бля\n", encoding="utf-8")
    load_words(path)
    path.unlink()
    assert count_profanity("бля") == 1


def test_find_profanity_returns_roots():
    from app.profanity import find_profanity

    assert find_profanity("Бляха, хреново! ну, бля", ROOTS) == ["бля", "хрен", "бля"]
