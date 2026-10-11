"""Скачивание моделей из каталога по клику на странице управления.

Архив качается в models/<id>.part, отдельные файлы модели — в models/.<id>.files.
Всё распаковывается во временную папку и только в конце переименовывается
в models/<id>. Поэтому недокачанная или недораспакованная модель никогда
не считается установленной.
"""

import asyncio
import logging
import shutil
import tarfile
import threading
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from .catalog import VOSK, ModelInfo

log = logging.getLogger(__name__)

CHUNK_BYTES = 1024 * 1024


class DownloadCancelled(Exception):
    pass


class _Download:
    def __init__(self, model: ModelInfo):
        self.model = model
        self.status = "downloading"  # downloading, extracting, error
        self.done_bytes = 0
        self.total_bytes = 0
        self.error: str | None = None
        self.cancelled = threading.Event()
        self.task: asyncio.Task | None = None

    def state(self) -> dict:
        progress = self.done_bytes / self.total_bytes if self.total_bytes else 0.0
        return {
            "status": self.status,
            "progress": min(progress, 1.0),
            "done_bytes": self.done_bytes,
            "total_bytes": self.total_bytes,
            "error": self.error,
        }


class ModelDownloader:
    """Скачивает модели в фоне; on_done(model) вызывается после установки."""

    def __init__(self, on_done: Callable[[ModelInfo], Awaitable[None]] | None = None):
        self.on_done = on_done
        self._downloads: dict[str, _Download] = {}

    def state(self, model_id: str) -> dict | None:
        download = self._downloads.get(model_id)
        return download.state() if download else None

    def start(self, model: ModelInfo) -> None:
        """Начинает скачивание; повторный вызов во время скачивания ничего не делает."""
        current = self._downloads.get(model.id)
        if current is not None and current.status != "error":
            return
        download = _Download(model)
        self._downloads[model.id] = download
        download.task = asyncio.create_task(self._run(download))

    def cancel(self, model_id: str) -> bool:
        """Прерывает скачивание модели; False, если она не скачивается."""
        download = self._downloads.get(model_id)
        if download is None:
            return False
        if download.status == "error":
            self._downloads.pop(model_id, None)  # просто убираем сообщение об ошибке
        else:
            download.cancelled.set()
        return True

    async def stop(self) -> None:
        """Прерывает все скачивания (при выходе из приложения)."""
        for download in self._downloads.values():
            download.cancelled.set()
        tasks = [d.task for d in self._downloads.values() if d.task and not d.task.done()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, download: _Download) -> None:
        model = download.model
        log.info("Скачивание модели %s: %s", model.id, ", ".join(_urls(model)))
        try:
            await asyncio.to_thread(_install, download)
        except DownloadCancelled:
            self._downloads.pop(model.id, None)
            log.info("Скачивание модели %s прервано", model.id)
            return
        except Exception as e:
            download.status = "error"
            download.error = f"Не удалось скачать модель: {e}"
            log.error("%s", download.error)
            return
        self._downloads.pop(model.id, None)
        log.info("Модель %s скачана и распакована", model.id)
        if self.on_done is not None:
            await self.on_done(model)


def _install(download: _Download) -> None:
    model = download.model
    target = model.path
    models_dir = target.parent
    models_dir.mkdir(parents=True, exist_ok=True)
    archive = models_dir / f"{model.id}.part"
    files_dir = models_dir / f".{model.id}.files"
    unpack_dir = models_dir / f".{model.id}.unpacking"
    urls = _urls(model)
    try:
        shutil.rmtree(files_dir, ignore_errors=True)
        files_dir.mkdir()
        if len(urls) > 1:
            # Общий размер узнаём заранее, чтобы прогресс шёл ровно по всем файлам.
            download.total_bytes = sum(_content_length(url) for url in urls)
        if model.url:
            _fetch(download, model.url, archive)
        for url in model.files:
            _fetch(download, url, files_dir / file_name(url))
        download.status = "extracting"
        shutil.rmtree(unpack_dir, ignore_errors=True)
        if model.url:
            _extract(archive, unpack_dir)
        if download.cancelled.is_set():
            raise DownloadCancelled
        # В архивах модель лежит в папке с тем же именем; на всякий случай
        # принимаем и архив, где файлы модели лежат прямо в корне.
        unpacked = unpack_dir / model.id
        source = unpacked if unpacked.is_dir() else unpack_dir
        source.mkdir(parents=True, exist_ok=True)
        for path in files_dir.iterdir():
            path.replace(source / path.name)
        _check(model, source)
        if target.exists():
            shutil.rmtree(target)
        source.rename(target)
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(files_dir, ignore_errors=True)
        shutil.rmtree(unpack_dir, ignore_errors=True)


def _fetch(download: _Download, url: str, path: Path) -> None:
    # Размер одного файла берём из ответа; размер нескольких уже известен (см. _install).
    fetch_to_file(url, path, download, set_total=len(_urls(download.model)) == 1)


def _urls(model: ModelInfo) -> list[str]:
    return ([model.url] if model.url else []) + list(model.files)


def _extract(archive: Path, folder: Path) -> None:
    """Распаковывает .zip или .tar.bz2 (тип узнаём по содержимому, а не по имени)."""
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(folder)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(folder, filter="data")  # filter не даст выйти за пределы папки


def _check(model: ModelInfo, folder: Path) -> None:
    if model.engine == VOSK:
        if not (folder / "am").is_dir() and not (folder / "conf").is_dir():
            raise ValueError("в архиве нет модели Vosk")
        return
    missing = [name for name in model.model_files.values() if not (folder / name).is_file()]
    if missing:
        raise ValueError(f"в скачанной модели нет файлов: {', '.join(missing)}")


def file_name(url: str) -> str:
    """Имя файла из ссылки: последняя часть пути."""
    return urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])


def _content_length(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "SwearCounter"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return int(response.headers.get("Content-Length") or 0)


def fetch_to_file(url: str, path: Path, job, set_total: bool = True) -> None:
    """Качает url в path кусками.

    job — объект с полями cancelled (threading.Event), done_bytes и total_bytes:
    по ним видно прогресс, а установленный cancelled прерывает скачивание.
    set_total=False оставляет total_bytes как есть: когда файлов несколько,
    общий размер считают заранее, а done_bytes копится по всем файлам.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "SwearCounter"})
    with urllib.request.urlopen(request, timeout=30) as response, open(path, "wb") as out:
        if set_total:
            job.total_bytes = int(response.headers.get("Content-Length") or 0)
        while True:
            if job.cancelled.is_set():
                raise DownloadCancelled
            chunk = response.read(CHUNK_BYTES)
            if not chunk:
                break
            out.write(chunk)
            job.done_bytes += len(chunk)
