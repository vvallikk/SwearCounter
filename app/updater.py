"""Обновление программы по релизам GitHub.

Проверка: последний релиз репозитория через API GitHub, без токена.
Установка (только собранный exe): zip релиза качается и распаковывается в
update/ рядом с exe, затем apply.cmd ждёт выхода программы, заменяет только
программные файлы (SwearCounter.exe и _internal) и запускает новую версию.
Данные пользователя рядом с exe (settings.json, counter.json, words.txt,
models, sounds, webview) не трогаются.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import __version__
from .paths import DATA_DIR
from .settings import Settings
from .stt.downloader import DownloadCancelled, fetch_to_file

log = logging.getLogger(__name__)

REPO = "vvallikk/SwearCounter"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_NAME = re.compile(r"SwearCounter-v[\w.\-]+-windows\.zip")
APP_FOLDER = "SwearCounter"  # папка внутри zip релиза (scripts/build.py)
EXE_NAME = "SwearCounter.exe"
CHECK_INTERVAL = 6 * 60 * 60  # автопроверка не чаще, чем раз в 6 часов
PROGRESS_INTERVAL = 0.5
FROZEN = bool(getattr(sys, "frozen", False))
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v1.2.3' или '1.2.3' -> (1, 2, 3); нестандартные теги (rc, beta) -> None."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", text.strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def is_newer(latest: str, current: str) -> bool:
    new, old = parse_version(latest), parse_version(current)
    if new is None or old is None:
        return False
    width = max(len(new), len(old))  # 1.2 == 1.2.0
    return new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def pick_asset(release: dict) -> dict | None:
    for asset in release.get("assets") or []:
        if ASSET_NAME.fullmatch(asset.get("name", "")):
            return asset
    return None


def release_info(release: dict, current: str = __version__) -> dict | None:
    """Сведения об обновлении из ответа GitHub; None, если обновлять не на что."""
    tag = release.get("tag_name") or ""
    asset = pick_asset(release)
    if release.get("draft") or release.get("prerelease") or asset is None:
        return None
    if not is_newer(tag, current):
        return None
    return {
        "latest": tag.lstrip("v"),
        "url": asset["browser_download_url"],
        "size": asset.get("size", 0),
        "notes": release.get("body") or "",
        "html_url": release.get("html_url") or f"https://github.com/{REPO}/releases",
    }


def fetch_latest(url: str = LATEST_URL) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": "SwearCounter", "Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}  # релизов ещё нет
        if e.code in (403, 429):
            raise RuntimeError("GitHub временно ограничил запросы, попробуйте позже") from None
        raise RuntimeError(f"GitHub ответил ошибкой {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise RuntimeError(f"нет связи с GitHub ({reason})") from None


def apply_script(pid: int, source: Path, target: Path, update_dir: Path) -> str:
    """apply.cmd: дождаться выхода программы, заменить программные файлы, запустить."""
    return "\r\n".join(
        [
            "@echo off",
            "chcp 65001 >nul",
            ":wait",
            f'tasklist /FI "PID eq {pid}" /NH 2>nul | find "{pid}" >nul && '
            "(timeout /t 1 /nobreak >nul & goto wait)",
            # Только программа: данные пользователя рядом с exe не трогаем.
            f'robocopy "{source / "_internal"}" "{target / "_internal"}" /MIR /R:10 /W:1 /NFL /NDL /NJH /NJS /NP >nul',
            f'copy /Y "{source / EXE_NAME}" "{target / EXE_NAME}" >nul',
            f'start "" "{target / EXE_NAME}"',
            # Удаляем папку обновления вместе с самим скриптом.
            f'(goto) 2>nul & rmdir /S /Q "{update_dir}"',
            "",
        ]
    )


class Updater:
    def __init__(
        self,
        settings: Settings,
        install_dir: Path = DATA_DIR,
        frozen: bool = FROZEN,
        current: str = __version__,
    ):
        self.settings = settings
        self.install_dir = Path(install_dir)
        self.update_dir = self.install_dir / "update"
        self.frozen = frozen
        self.current = current
        self.status = "idle"  # idle, checking, none, available, downloading, extracting, ready, error
        self.info: dict | None = None
        self.error: str | None = None
        self.done_bytes = 0
        self.total_bytes = 0
        self.cancelled = threading.Event()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        # Подключаются снаружи: рассылка состояния, уведомление трея, выход из программы.
        self.on_change: Callable[[dict], Awaitable[None]] | None = None
        self.on_found: Callable[[str], None] | None = None
        self.quit: Callable[[], None] | None = None

    @property
    def auto(self) -> bool:
        return bool(self.settings.get("update_auto", True))

    def set_auto(self, enabled: bool) -> None:
        self.settings.set("update_auto", enabled)

    @property
    def busy(self) -> bool:
        return self.status in ("checking", "downloading", "extracting")

    def state(self) -> dict:
        progress = self.done_bytes / self.total_bytes if self.total_bytes else 0.0
        return {
            "current": self.current,
            "auto": self.auto,
            "can_install": self.frozen,
            "status": self.status,
            "progress": min(progress, 1.0),
            "error": self.error,
            **(self.info or {}),
        }

    async def _changed(self) -> None:
        if self.on_change is not None:
            await self.on_change(self.state())

    async def _set(self, status: str, error: str | None = None) -> None:
        self.status, self.error = status, error
        await self._changed()

    async def check(self) -> str:
        """Проверяет последний релиз; возвращает новый статус."""
        if self.busy or self.status == "ready":
            return self.status
        await self._set("checking")
        try:
            release = await asyncio.to_thread(fetch_latest)
        except Exception as e:
            log.warning("Проверка обновлений: %s", e)
            await self._set("error", f"Не удалось проверить обновления: {e}")
            return self.status
        self.info = release_info(release, self.current)
        self.settings.set("update_checked_at", time.time())
        self.settings.set("update_last", self.info)
        if self.info is None:
            await self._set("none")
        else:
            log.info("Доступно обновление %s", self.info["latest"])
            await self._set("available")
            if self.on_found is not None:
                self.on_found(self.info["latest"])
        return self.status

    async def auto_check(self, now: float | None = None) -> None:
        """Проверка при запуске: не чаще CHECK_INTERVAL, иначе — по прошлому результату."""
        self.loop = asyncio.get_running_loop()
        if not self.auto:
            return
        now = time.time() if now is None else now
        if now - float(self.settings.get("update_checked_at") or 0) >= CHECK_INTERVAL:
            await self.check()
            return
        last = self.settings.get("update_last")
        if isinstance(last, dict) and is_newer(str(last.get("latest", "")), self.current):
            self.info = last
            await self._set("available")

    def check_threadsafe(self, timeout: float = 30) -> str:
        """Проверка из другого потока (меню трея)."""
        if self.loop is None:
            return "error"
        return asyncio.run_coroutine_threadsafe(self.check(), self.loop).result(timeout)

    def start_download(self) -> None:
        if not self.frozen:
            raise ValueError("Обновление ставится только в собранной программе (exe)")
        if self.info is None:
            raise ValueError("Нет доступного обновления")
        if self.busy or self.status == "ready":
            return
        self.cancelled.clear()
        self.done_bytes = self.total_bytes = 0
        self.status, self.error = "downloading", None
        self._task = asyncio.create_task(self._download())

    def cancel(self) -> bool:
        if self.status not in ("downloading", "extracting"):
            return False
        self.cancelled.set()
        return True

    async def stop(self) -> None:
        self.cancelled.set()
        if self._task is not None and not self._task.done():
            await asyncio.gather(self._task, return_exceptions=True)

    async def _download(self) -> None:
        await self._changed()
        job = asyncio.create_task(asyncio.to_thread(self._install))
        while not job.done():
            await asyncio.wait({job}, timeout=PROGRESS_INTERVAL)
            await self._changed()
        try:
            job.result()
        except DownloadCancelled:
            log.info("Скачивание обновления прервано")
            await self._set("available")
            return
        except Exception as e:
            log.error("Не удалось скачать обновление: %s", e)
            await self._set("error", f"Не удалось скачать обновление: {e}")
            return
        log.info("Обновление %s скачано", self.info["latest"])
        await self._set("ready")

    def _install(self) -> None:
        shutil.rmtree(self.update_dir, ignore_errors=True)
        self.update_dir.mkdir(parents=True)
        archive = self.update_dir / "update.zip.part"
        new_dir = self.update_dir / "new"
        try:
            fetch_to_file(self.info["url"], archive, self)
            self.status = "extracting"
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(new_dir)
            if self.cancelled.is_set():
                raise DownloadCancelled
            if not (new_dir / APP_FOLDER / EXE_NAME).is_file():
                raise ValueError(f"в архиве нет {APP_FOLDER}/{EXE_NAME}")
        except BaseException:
            shutil.rmtree(self.update_dir, ignore_errors=True)
            raise
        finally:
            archive.unlink(missing_ok=True)

    def apply(self) -> None:
        """Запускает apply.cmd; программа должна выйти сразу после этого (self.exit)."""
        if self.status != "ready":
            raise ValueError("Обновление ещё не скачано")
        script = self.update_dir / "apply.cmd"
        script.write_text(
            apply_script(os.getpid(), self.update_dir / "new" / APP_FOLDER, self.install_dir, self.update_dir),
            encoding="utf-8",
        )
        log.info("Установка обновления %s, перезапуск", self.info["latest"])
        subprocess.Popen(
            ["cmd", "/c", str(script)],
            cwd=self.install_dir,
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )

    def exit(self) -> None:
        if self.quit is not None:
            self.quit()
        else:
            os._exit(0)
