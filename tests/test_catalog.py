"""Каталог моделей: поиск по id и признак «установлена»."""

import json

from app.stt.catalog import (
    CATALOG,
    CLOUD,
    EN,
    RU,
    SHERPA_NEMO_CTC,
    SHERPA_T_ONE,
    SHERPA_TRANSDUCER,
    SHERPA_WHISPER,
    VOSK,
    find_model,
    installed_models,
)

SMALL = "vosk-model-small-ru-0.22"
LARGE = "vosk-model-ru-0.42"


def test_catalog_ids_are_unique():
    ids = [m.id for m in CATALOG]
    assert len(ids) == len(set(ids))


def test_find_model():
    assert find_model(SMALL).id == SMALL
    assert find_model("нет-такой") is None


def test_nothing_installed_in_empty_models_dir(models_dir):
    assert installed_models() == []
    assert not find_model(SMALL).installed


def test_installed_models_follow_folders_in_catalog_order(models_dir):
    (models_dir / LARGE).mkdir()
    assert [m.id for m in installed_models()] == [LARGE]

    (models_dir / SMALL).mkdir()
    # Порядок как в каталоге, а не как появились папки.
    assert [m.id for m in installed_models()] == [SMALL, LARGE]


def test_file_with_model_name_is_not_installed(models_dir):
    (models_dir / SMALL).write_text("не папка", encoding="utf-8")
    assert not find_model(SMALL).installed


def test_to_dict_reports_installed_flag(models_dir):
    (models_dir / SMALL).mkdir()
    data = find_model(SMALL).to_dict()
    assert data["id"] == SMALL
    assert data["installed"] is True
    assert find_model(LARGE).to_dict()["installed"] is False
    assert {"title", "name", "summary", "description", "disk", "download_size", "memory", "load_time", "url"} <= data.keys()
    assert {"engine", "files", "model_files"} <= data.keys()
    json.dumps(data)  # уходит на страницу управления как есть


# Какие файлы нужны каждому движку sherpa-onnx (см. engines.py).
REQUIRED_FILES = {
    SHERPA_TRANSDUCER: {"encoder", "decoder", "joiner", "tokens"},
    SHERPA_T_ONE: {"model", "tokens"},
    SHERPA_NEMO_CTC: {"model", "tokens", "vad"},
    SHERPA_WHISPER: {"encoder", "decoder", "tokens", "vad"},
    CLOUD: {"vad"},  # звук распознаёт сервис, локально нужен только детектор речи
}


def test_every_model_has_known_engine_and_files():
    for model in CATALOG:
        if model.engine == VOSK:
            assert model.model_files == {}, model.id
        else:
            assert set(model.model_files) == REQUIRED_FILES[model.engine], model.id


def test_default_model_is_still_small_vosk():
    """Первая модель — модель по умолчанию; у тех, кто обновился, она не должна смениться."""
    assert CATALOG[0].id == SMALL
    assert [m for m in CATALOG if m.language == RU and not m.cloud][-1].id == LARGE


def test_models_grouped_by_language():
    """Сначала все русские модели, потом английские: страница показывает модели одного языка."""
    languages = [m.language for m in CATALOG]
    assert set(languages) == {RU, EN}
    assert languages == sorted(languages, key=[RU, EN].index)
    assert find_model("vosk-model-small-en-us-0.15").to_dict()["language"] == EN
