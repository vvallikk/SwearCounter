"""Каталог моделей: поиск по id и признак «установлена»."""

from app.stt.catalog import CATALOG, find_model, installed_models

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
    assert {"title", "name", "summary", "description", "disk", "memory", "load_time", "url"} <= data.keys()
