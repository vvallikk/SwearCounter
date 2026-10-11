"""Список слов, который идёт с программой: ловит частые формы и не ловит обычные слова."""

import re
from pathlib import Path

import pytest

from app import profanity
from app.profanity import count_profanity, load_words

WORDS = Path(__file__).resolve().parent.parent / "words.txt"


@pytest.fixture(autouse=True)
def _roots(monkeypatch):
    monkeypatch.setattr(profanity, "_roots", ())
    monkeypatch.setattr(profanity, "_source", None)
    load_words(WORDS)
    monkeypatch.setattr(profanity, "_source", None)  # без перечитывания файла


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
def test_swears_counted(word):
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
def test_ordinary_words_not_counted(word):
    assert count_profanity(word) == 0


def test_roots_are_cyrillic_lowercase():
    roots = profanity._roots
    assert roots, "список корней пуст"
    for root in roots:
        assert re.fullmatch(r"[а-яъь]+", root), root
