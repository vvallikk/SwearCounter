"""Язык интерфейса: выбор, перевод текстов программы и словарь страницы управления."""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app import i18n
from app.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "settings.json")


@pytest.mark.parametrize("system", [i18n.RU, i18n.EN])
def test_language_defaults_to_system(settings, monkeypatch, system):
    monkeypatch.setattr(i18n, "system_language", lambda: system)
    assert i18n.language(settings) == system


@pytest.mark.parametrize(
    "env, expected",
    [
        ({"LANG": "ru_RU.UTF-8"}, i18n.RU),
        ({"LANG": "uk_UA.UTF-8"}, i18n.RU),
        ({"LANG": "en_US.UTF-8"}, i18n.EN),
        ({"LANG": "de_DE"}, i18n.EN),
        ({"LANG": "en_US.UTF-8", "LC_ALL": "ru_RU.UTF-8"}, i18n.RU),
        ({"LANG": "C.UTF-8"}, i18n.RU),
        ({}, i18n.RU),
    ],
)
def test_system_language_on_unix(monkeypatch, env, expected):
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert i18n.system_language() == expected


def test_language_from_settings(settings, monkeypatch):
    monkeypatch.setattr(i18n, "system_language", lambda: i18n.RU)
    settings.set(i18n.SETTING, i18n.EN)
    assert i18n.language(settings) == i18n.EN
    settings.set(i18n.SETTING, "de")  # неизвестный — снова язык системы
    assert i18n.language(settings) == i18n.RU


def test_tr():
    assert i18n.tr("Выход", i18n.EN) == "Quit"
    assert i18n.tr("Выход", i18n.RU) == "Выход"
    assert i18n.tr("Адрес оверлея скопирован: {}", i18n.EN).format("x") == "Overlay address copied: x"
    assert i18n.tr("Нет в словаре", i18n.EN) == "Нет в словаре"


def test_title():
    assert i18n.title(i18n.EN) == "Swear Counter"
    assert i18n.title(i18n.RU) == i18n.title("??") == "Счётчик матов"


def test_translations_keep_placeholders():
    for ru, en in i18n._EN.items():
        assert ru.count("{}") == en.count("{}"), ru


class _Texts(HTMLParser):
    """Русские тексты и подсказки страницы управления."""

    def __init__(self):
        super().__init__()
        self.texts: set[str] = set()
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for name, value in attrs:
            if name in ("title", "placeholder", "aria-label") and value:
                self._add(value)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self._add(data)

    def _add(self, text):
        text = re.sub(r"\s+", " ", text).strip()
        if re.search("[а-яё]", text, re.I):
            self.texts.add(text)


def test_control_page_texts_have_translations():
    # Новый текст на странице управления без перевода остался бы в английском режиме русским.
    parser = _Texts()
    parser.feed((ROOT / "control" / "index.html").read_text(encoding="utf-8"))
    script = (ROOT / "control" / "i18n.js").read_text(encoding="utf-8")
    missing = [t for t in sorted(parser.texts) if f'"{t}"' not in script and f"'{t}'" not in script]
    assert not missing
