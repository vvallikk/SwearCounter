"""Списки слов: раскладка встроенных, выбор активного и перенос старого words.txt."""

import pytest

from app import profanity
from app.profanity import count_profanity
from app.settings import Settings
from app.wordlists import MIGRATED_LIST, WordLists, migrate_words_file


@pytest.fixture(autouse=True)
def _restore_roots(monkeypatch):
    monkeypatch.setattr(profanity, "_roots", ())
    monkeypatch.setattr(profanity, "_source", None)
    monkeypatch.setattr(profanity, "_stamp", None)


@pytest.fixture
def bundled(tmp_path):
    path = tmp_path / "bundled"
    path.mkdir()
    (path / "swears.txt").write_text("# Название: Маты (18+)\nбля\nхрен\n", encoding="utf-8")
    (path / "parasites.txt").write_text("# Название: Слова-паразиты\nкороч\n", encoding="utf-8")
    return path


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "settings.json")


@pytest.fixture
def lists(settings, bundled, tmp_path):
    return WordLists(settings, tmp_path / "user", bundled)


def test_prepare_copies_bundled_and_loads_default(lists):
    lists.prepare()
    assert sorted(p.name for p in lists.directory.iterdir()) == ["parasites.txt", "swears.txt"]
    assert lists.active() == "swears.txt"
    assert count_profanity("бля") == 1


def test_english_name_line(lists):
    lists.directory.mkdir()
    (lists.directory / "en.txt").write_text("# Name: English swear words\nfuck\n", encoding="utf-8")
    assert lists.lists() == [{"id": "en.txt", "name": "English swear words", "words": 1}]


def test_prepare_keeps_user_edits(lists):
    lists.directory.mkdir()
    (lists.directory / "swears.txt").write_text("свое\n", encoding="utf-8")
    lists.prepare()
    assert (lists.directory / "swears.txt").read_text(encoding="utf-8") == "свое\n"
    assert count_profanity("своеобразно") == 1


def test_lists_names_and_counts(lists):
    lists.prepare()
    (lists.directory / "друзья.txt").write_text("вася\nВАСЯ\nпетя\n# коля\n", encoding="utf-8")
    assert lists.lists() == [
        {"id": "parasites.txt", "name": "Слова-паразиты", "words": 1},
        {"id": "swears.txt", "name": "Маты (18+)", "words": 2},
        {"id": "друзья.txt", "name": "друзья", "words": 2},  # без названия — имя файла
    ]


def test_select_switches_roots_and_persists(lists, settings, bundled, tmp_path):
    lists.prepare()
    lists.select("parasites.txt")
    assert count_profanity("короче бля") == 1
    assert settings.get("word_list") == "parasites.txt"
    # После перезапуска включается тот же список.
    WordLists(Settings(tmp_path / "settings.json"), lists.directory, bundled).prepare()
    assert count_profanity("короче бля") == 1


@pytest.mark.parametrize("bad", ["нет.txt", "../settings.json", "..\\settings.json", ""])
def test_select_unknown_list(lists, bad):
    lists.prepare()
    with pytest.raises(KeyError):
        lists.select(bad)


def test_active_falls_back_when_file_deleted(lists, settings):
    lists.prepare()
    lists.select("parasites.txt")
    (lists.directory / "parasites.txt").unlink()
    assert lists.active() == "swears.txt"


def test_same_directory_from_sources(settings, bundled):
    # Из исходников встроенная папка и папка пользователя совпадают: копировать нечего.
    WordLists(settings, bundled, bundled).prepare()
    assert count_profanity("бля") == 1


def test_migrate_placeholder_is_removed(tmp_path):
    old = tmp_path / "words.txt"
    old.write_text("# заглушка\nтестслов\nпроверк\n", encoding="utf-8")
    assert migrate_words_file(old, tmp_path) is None
    assert not old.exists()
    assert not (tmp_path / MIGRATED_LIST).exists()


def test_migrate_edited_words_become_own_list(lists, settings, tmp_path):
    old = tmp_path / "words.txt"
    old.write_text("тестслов\nпроверк\nвася\n", encoding="utf-8")
    lists.prepare(old)
    assert not old.exists()
    assert lists.active() == MIGRATED_LIST
    assert {"id": MIGRATED_LIST, "name": "Мой список (из words.txt)", "words": 3} in lists.lists()
    assert count_profanity("васян") == 1


def test_migrate_missing_file(tmp_path):
    assert migrate_words_file(tmp_path / "words.txt", tmp_path) is None
