"""Счётчик (counter.json) и настройки (settings.json)."""

import asyncio
import json

from app.counter import Counter
from app.settings import Settings


# --- Counter ---


def test_counter_starts_at_zero_without_file(counter):
    assert counter.value == 0


def test_counter_add_persists_and_leaves_no_tmp(counter, counter_path):
    assert asyncio.run(counter.add()) == 1
    assert asyncio.run(counter.add(3)) == 4

    assert json.loads(counter_path.read_text(encoding="utf-8")) == {"count": 4}
    assert not counter_path.with_suffix(".json.tmp").exists()
    assert Counter(counter_path).value == 4


def test_counter_reset_persists(counter, counter_path):
    asyncio.run(counter.add(5))
    assert asyncio.run(counter.reset()) == 0
    assert Counter(counter_path).value == 0


def test_counter_concurrent_adds_are_not_lost(counter, counter_path):
    async def many():
        await asyncio.gather(*(counter.add() for _ in range(50)))

    asyncio.run(many())
    assert counter.value == 50
    assert Counter(counter_path).value == 50


def test_counter_ignores_broken_file(counter_path):
    for content in ("{не json", '{"count": "много"}', "{}", "[1, 2]"):
        counter_path.write_text(content, encoding="utf-8")
        assert Counter(counter_path).value == 0, content


def test_counter_clamps_negative_value(counter_path):
    counter_path.write_text('{"count": -7}', encoding="utf-8")
    assert Counter(counter_path).value == 0


# --- Settings ---


def test_settings_default_without_file(settings):
    assert settings.get("model") is None
    assert settings.get("model", "по умолчанию") == "по умолчанию"


def test_settings_set_persists_unicode(settings, settings_path):
    settings.set("device", "Микрофон (Realtek(R) Audio)")
    settings.set("load_seconds", {"vosk-model-small-ru-0.22": 1.5})

    # Русские имена сохраняются как есть, без \u-экранирования.
    assert "Микрофон" in settings_path.read_text(encoding="utf-8")
    assert not settings_path.with_suffix(".json.tmp").exists()

    reloaded = Settings(settings_path)
    assert reloaded.get("device") == "Микрофон (Realtek(R) Audio)"
    assert reloaded.get("load_seconds") == {"vosk-model-small-ru-0.22": 1.5}


def test_settings_ignore_broken_or_non_dict_file(settings_path):
    for content in ("{битый", "[1, 2, 3]", '"строка"'):
        settings_path.write_text(content, encoding="utf-8")
        assert Settings(settings_path).get("model") is None, content


def test_settings_save_over_broken_file(settings_path):
    settings_path.write_text("{битый", encoding="utf-8")
    settings = Settings(settings_path)
    settings.set("model", "vosk-model-ru-0.42")
    assert Settings(settings_path).get("model") == "vosk-model-ru-0.42"
