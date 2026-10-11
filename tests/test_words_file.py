"""Встроенные списки слов: ловят частые формы и не ловят обычные слова."""

import re
from pathlib import Path

import pytest

from app import profanity
from app.profanity import count_profanity, load_words, read_roots
from app.wordlists import DEFAULT_LIST

WORDLISTS = Path(__file__).resolve().parent.parent / "wordlists"
LISTS = sorted(WORDLISTS.glob("*.txt"))


@pytest.fixture
def use_list(monkeypatch):
    def use(name):
        load_words(WORDLISTS / name)
        monkeypatch.setattr(profanity, "_source", None)  # без перечитывания файла

    monkeypatch.setattr(profanity, "_roots", ())
    monkeypatch.setattr(profanity, "_source", None)
    return use


@pytest.mark.parametrize(
    "word",
    [
        "бля", "блять", "блядский", "выблядок",
        "хуй", "хуя", "хуёвый", "охуеть", "ахуеть", "нахуй", "похуй", "нихуя", "дохуя",
        "пиздец", "распиздяй", "спиздил", "запиздел",
        "ебать", "ёбаный", "заебал", "отъебись", "наебали", "съебался", "уебище", "долбоёб", "ёпта",
        "мудак", "мудила", "пидорас", "гандон", "залупа", "шлюха", "сука", "суки", "сучара",
    ],
)
def test_swears_counted(use_list, word):
    use_list("swears.txt")
    assert count_profanity(word) == 1


@pytest.mark.parametrize(
    "word",
    [
        "мандарин", "мандат", "худой", "хутор", "хурма", "художник", "хулиган",
        "мудрый", "мудрость", "пиджак", "сукно", "сукровица", "сучок", "херсон", "херувим",
        "яблоко", "оскорбление", "опыт", "поезд", "уехал", "заехал", "наездник",
        "подъезд", "разъехались", "съел", "въезд", "объезд", "дохлый", "охота", "похудел",
    ],
)
def test_ordinary_words_not_counted_as_swears(use_list, word):
    use_list("swears.txt")
    assert count_profanity(word) == 0


@pytest.mark.parametrize("word", ["короче", "типа", "походу", "буквально", "кстати", "вообще", "блин", "капец"])
def test_parasites_counted(use_list, word):
    use_list("parasites.txt")
    assert count_profanity(word) == 1


@pytest.mark.parametrize(
    "word", ["корочка", "тип", "поход", "буква", "реальность", "значительно", "собственность", "нужно", "жест"]
)
def test_ordinary_words_not_counted_as_parasites(use_list, word):
    use_list("parasites.txt")
    assert count_profanity(word) == 0


@pytest.mark.parametrize("path", LISTS, ids=lambda p: p.name)
def test_roots_are_cyrillic_lowercase(path):
    roots = read_roots(path)
    assert roots, "список корней пуст"
    for root in roots:
        assert re.fullmatch(r"[а-яъь]+", root), root


@pytest.mark.parametrize("path", LISTS, ids=lambda p: p.name)
def test_list_has_name(path):
    assert path.read_text(encoding="utf-8").startswith("# Название: ")


def test_default_list_is_bundled():
    assert (WORDLISTS / DEFAULT_LIST).is_file()
