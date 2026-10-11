"""Скачивание моделей: архив берётся из локального файла (file://), без интернета."""

import asyncio
import dataclasses
import io
import tarfile
import zipfile

import pytest

from app.stt import CATALOG, downloader as downloader_module
from app.stt.catalog import SHERPA_NEMO_CTC, SHERPA_TRANSDUCER
from app.stt.downloader import ModelDownloader, file_name

MODEL = CATALOG[0]
# Модель sherpa-onnx из одного архива .tar.bz2.
TAR_MODEL = next(m for m in CATALOG if m.engine == SHERPA_TRANSDUCER and m.url)
# Модель из отдельных файлов, без архива.
FILES_MODEL = next(m for m in CATALOG if not m.url)
# Архив и отдельный файл (детектор речи) вместе.
MIXED_MODEL = next(m for m in CATALOG if m.engine == SHERPA_NEMO_CTC)


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


def make_tar(path, model_id, names):
    """Архив .tar.bz2 как у sherpa-onnx: папка модели с файлами внутри."""
    with tarfile.open(path, "w:bz2") as tf:
        for name in names:
            data = f"file {name}".encode()
            info = tarfile.TarInfo(f"{model_id}/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def make_files(folder, names):
    folder.mkdir()
    for name in names:
        (folder / name).write_bytes(f"file {name}".encode())
    return [(folder / name).as_uri() for name in names]


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

    def spy(download, url, path):
        original(download, url, path)
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


def test_tar_archive_installs_sherpa_model(models_dir, tmp_path):
    names = list(TAR_MODEL.model_files.values()) + ["README.md"]
    model = dataclasses.replace(TAR_MODEL, url=make_tar(tmp_path / "m.tar.bz2", TAR_MODEL.id, names).as_uri())

    done, _ = download(model)

    assert done == [TAR_MODEL.id]
    for name in names:
        assert (models_dir / TAR_MODEL.id / name).read_bytes() == f"file {name}".encode()
    assert sorted(p.name for p in models_dir.iterdir()) == [TAR_MODEL.id]


def test_tar_archive_without_model_files_is_error(models_dir, tmp_path):
    model = dataclasses.replace(TAR_MODEL, url=make_tar(tmp_path / "m.tar.bz2", TAR_MODEL.id, ["tokens.txt"]).as_uri())

    done, loader = download(model)

    assert done == []
    error = loader.state(TAR_MODEL.id)["error"]
    assert "нет файлов" in error and TAR_MODEL.model_files["encoder"] in error
    assert list(models_dir.iterdir()) == []


def test_model_from_separate_files(models_dir, tmp_path, monkeypatch):
    names = list(FILES_MODEL.model_files.values())
    model = dataclasses.replace(FILES_MODEL, files=tuple(make_files(tmp_path / "src", names)))
    seen = []
    original = downloader_module._fetch

    def spy(download, url, path):
        original(download, url, path)
        seen.append(download.state())

    monkeypatch.setattr(downloader_module, "_fetch", spy)
    done, _ = download(model)

    assert done == [FILES_MODEL.id]
    assert sorted(p.name for p in (models_dir / FILES_MODEL.id).iterdir()) == sorted(names)
    # Общий размер известен с самого начала, прогресс растёт по всем файлам.
    total = sum(len(f"file {name}") for name in names)
    assert [s["total_bytes"] for s in seen] == [total] * len(names)
    assert seen[-1]["progress"] == 1.0
    assert sorted(p.name for p in models_dir.iterdir()) == [FILES_MODEL.id]


def test_archive_and_extra_file(models_dir, tmp_path):
    vad = MIXED_MODEL.model_files["vad"]
    in_archive = [n for n in MIXED_MODEL.model_files.values() if n != vad]
    model = dataclasses.replace(
        MIXED_MODEL,
        url=make_tar(tmp_path / "m.tar.bz2", MIXED_MODEL.id, in_archive).as_uri(),
        files=tuple(make_files(tmp_path / "src", [vad])),
    )

    done, _ = download(model)

    assert done == [MIXED_MODEL.id]
    assert sorted(p.name for p in (models_dir / MIXED_MODEL.id).iterdir()) == sorted(MIXED_MODEL.model_files.values())
    assert sorted(p.name for p in models_dir.iterdir()) == [MIXED_MODEL.id]


def test_missing_extra_file_is_error(models_dir, tmp_path):
    model = dataclasses.replace(FILES_MODEL, files=((tmp_path / "нет-такого.onnx").as_uri(),))

    done, loader = download(model)

    assert done == []
    assert loader.state(FILES_MODEL.id)["status"] == "error"
    assert list(models_dir.iterdir()) == []


def test_catalog_downloads_cover_model_files():
    """Всё, что нужно движку, скачивается: из архива или отдельным файлом."""
    for model in CATALOG:
        assert model.url or model.files, model.id
        extra = {file_name(url) for url in model.files}
        if not model.url:
            assert set(model.model_files.values()) <= extra, model.id


def test_file_name():
    assert file_name("https://example.com/a/b/encoder.int8.onnx") == "encoder.int8.onnx"
    assert file_name("https://example.com/a/%D1%84.txt?download=1") == "ф.txt"
