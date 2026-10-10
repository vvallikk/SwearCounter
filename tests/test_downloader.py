"""Скачивание моделей: архив берётся из локального файла (file://), без интернета."""

import asyncio
import dataclasses
import zipfile

import pytest

from app.stt import CATALOG, downloader as downloader_module
from app.stt.downloader import ModelDownloader

MODEL = CATALOG[0]


def make_archive(path, model_id, with_model=True, nested=True):
    """Архив как у Vosk: папка модели с am/ и conf/ внутри."""
    prefix = f"{model_id}/" if nested else ""
    with zipfile.ZipFile(path, "w") as zf:
        if with_model:
            zf.writestr(f"{prefix}am/final.mdl", b"model")
            zf.writestr(f"{prefix}conf/model.conf", b"conf")
        else:
            zf.writestr(f"{prefix}readme.txt", b"not a model")
    return path


def model_from(archive):
    return dataclasses.replace(MODEL, url=archive.as_uri())


def download(model):
    """Скачивает модель и возвращает (модели, для которых вызван on_done; загрузчик)."""
    done = []

    async def on_done(m):
        done.append(m.id)

    async def scenario():
        loader = ModelDownloader(on_done)
        loader.start(model)
        await asyncio.gather(*(d.task for d in loader._downloads.values()))
        return loader

    return done, asyncio.run(scenario())


def test_download_installs_model(models_dir, tmp_path):
    model = model_from(make_archive(tmp_path / "m.zip", MODEL.id))

    done, loader = download(model)

    assert done == [MODEL.id]
    assert (models_dir / MODEL.id / "am" / "final.mdl").read_bytes() == b"model"
    assert loader.state(MODEL.id) is None
    # Временные файлы убраны.
    assert sorted(p.name for p in models_dir.iterdir()) == [MODEL.id]


def test_archive_with_files_in_root(models_dir, tmp_path):
    model = model_from(make_archive(tmp_path / "m.zip", MODEL.id, nested=False))

    done, _ = download(model)

    assert done == [MODEL.id]
    assert (models_dir / MODEL.id / "conf" / "model.conf").is_file()


def test_archive_without_model_is_error(models_dir, tmp_path):
    model = model_from(make_archive(tmp_path / "m.zip", MODEL.id, with_model=False))

    done, loader = download(model)

    assert done == []
    state = loader.state(MODEL.id)
    assert state["status"] == "error"
    assert "нет модели Vosk" in state["error"]
    assert not MODEL.path.exists()
    assert list(models_dir.iterdir()) == []


def test_missing_file_is_error(models_dir, tmp_path):
    model = model_from(tmp_path / "нет-такого.zip")

    done, loader = download(model)

    assert done == []
    assert loader.state(MODEL.id)["status"] == "error"
    assert list(models_dir.iterdir()) == []


def test_cancel_stops_download(models_dir, tmp_path, monkeypatch):
    model = model_from(make_archive(tmp_path / "m.zip", MODEL.id))
    monkeypatch.setattr(downloader_module, "CHUNK_BYTES", 1)  # много кусков: успеем отменить
    done = []

    async def on_done(m):
        done.append(m.id)

    async def scenario():
        loader = ModelDownloader(on_done)
        loader.start(model)
        assert loader.cancel(MODEL.id)
        await asyncio.gather(*(d.task for d in loader._downloads.values()))
        return loader

    loader = asyncio.run(scenario())

    assert done == []
    assert loader.state(MODEL.id) is None
    assert list(models_dir.iterdir()) == []


def test_cancel_unknown_model(models_dir):
    assert ModelDownloader().cancel(MODEL.id) is False


def test_progress_is_reported(models_dir, tmp_path, monkeypatch):
    archive = make_archive(tmp_path / "m.zip", MODEL.id)
    seen = []
    original = downloader_module._fetch

    def spy(download, path):
        original(download, path)
        seen.append(download.state())

    monkeypatch.setattr(downloader_module, "_fetch", spy)
    download(model_from(archive))

    size = archive.stat().st_size
    assert seen == [
        {"status": "downloading", "progress": 1.0, "done_bytes": size, "total_bytes": size, "error": None}
    ]


@pytest.mark.parametrize("status", ["downloading", "extracting"])
def test_second_start_while_downloading_is_ignored(models_dir, status):
    async def scenario():
        loader = ModelDownloader()
        current = downloader_module._Download(MODEL)
        current.status = status
        loader._downloads[MODEL.id] = current
        loader.start(MODEL)
        return loader._downloads[MODEL.id] is current

    assert asyncio.run(scenario())
