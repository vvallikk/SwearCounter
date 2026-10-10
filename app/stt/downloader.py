"""Скачивание моделей из каталога по клику на странице управления.

Архив качается в models/<id>.zip.part, распаковывается во временную папку
и только в конце переименовывается в models/<id>. Поэтому недокачанная или
недораспакованная модель никогда не считается установленной.
"""

import asyncio
import logging
import shutil
import threading
import urllib.request
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from .catalog import ModelInfo

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
        log.info("Скачивание модели %s: %s", model.id, model.url)
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
    archive = models_dir / f"{model.id}.zip.part"
    unpack_dir = models_dir / f".{model.id}.unpacking"
    try:
        _fetch(download, archive)
        download.status = "extracting"
        shutil.rmtree(unpack_dir, ignore_errors=True)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(unpack_dir)
        if download.cancelled.is_set():
            raise DownloadCancelled
        # В архивах Vosk модель лежит в папке с тем же именем; на всякий случай
        # принимаем и архив, где файлы модели лежат прямо в корне.
        unpacked = unpack_dir / model.id
        source = unpacked if unpacked.is_dir() else unpack_dir
        if not (source / "am").is_dir() and not (source / "conf").is_dir():
            raise ValueError("в архиве нет модели Vosk")
        if target.exists():
            shutil.rmtree(target)
        source.rename(target)
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(unpack_dir, ignore_errors=True)


def _fetch(download: _Download, archive: Path) -> None:
    request = urllib.request.Request(download.model.url, headers={"User-Agent": "SwearCounter"})
    with urllib.request.urlopen(request, timeout=30) as response, open(archive, "wb") as out:
        download.total_bytes = int(response.headers.get("Content-Length") or 0)
        while True:
            if download.cancelled.is_set():
                raise DownloadCancelled
            chunk = response.read(CHUNK_BYTES)
            if not chunk:
                break
            out.write(chunk)
            download.done_bytes += len(chunk)
