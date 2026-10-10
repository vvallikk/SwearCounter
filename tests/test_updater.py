import asyncio
import io
import json
import time
import urllib.error
import zipfile

import pytest

from app import updater as updater_module
from app.settings import Settings
from app.updater import Updater, apply_script, fetch_latest, is_newer, parse_version, release_info

ZIP_URL = "https://github.com/vvallikk/SwearCounter/releases/download/v0.3.0/SwearCounter-v0.3.0-windows.zip"


def make_release(tag="v0.3.0", **extra):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/vvallikk/SwearCounter/releases/tag/{tag}",
        "body": "Что нового",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": "checksums.txt", "browser_download_url": "https://example.invalid/sums", "size": 1},
            {"name": f"SwearCounter-{tag}-windows.zip", "browser_download_url": ZIP_URL, "size": 1234},
        ],
        **extra,
    }


def make_zip(with_exe=True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if with_exe:
            zf.writestr("SwearCounter/SwearCounter.exe", b"exe")
        zf.writestr("SwearCounter/_internal/lib.dll", b"dll")
        zf.writestr("SwearCounter/words.txt", "мат")
    return buf.getvalue()


class SlowResponse(io.BytesIO):
    """Отдаёт по байту с паузой: скачивание не успевает закончиться до отмены."""

    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def read(self, size=-1):
        time.sleep(0.01)
        return super().read(1)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@pytest.fixture
def responses(monkeypatch):
    """url -> bytes или исключение; подменяет urlopen."""
    table: dict[str, object] = {}

    def fake_urlopen(request, timeout=None):
        result = table[request.full_url]
        if isinstance(result, Exception):
            raise result
        return result if isinstance(result, SlowResponse) else FakeResponse(result)

    monkeypatch.setattr(updater_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("app.stt.downloader.urllib.request.urlopen", fake_urlopen)
    return table


@pytest.fixture
def updater(settings, tmp_path):
    return Updater(settings, install_dir=tmp_path / "app", frozen=True, current="0.2.0")


# --- версии и ответ GitHub ---


@pytest.mark.parametrize(
    "text, expected",
    [("v1.2.3", (1, 2, 3)), ("0.2.0", (0, 2, 0)), ("v10", (10,)), ("v0.2.0-rc", None), ("latest", None), ("", None)],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize(
    "latest, current, newer",
    [("v0.3.0", "0.2.0", True), ("v0.10.0", "0.9.0", True), ("v0.2.0", "0.2.0", False),
     ("v0.2", "0.2.0", False), ("v0.1.9", "0.2.0", False), ("v0.3.0-rc", "0.2.0", False)],
)
def test_is_newer(latest, current, newer):
    assert is_newer(latest, current) is newer


def test_release_info_picks_zip_asset():
    info = release_info(make_release(), current="0.2.0")
    assert info == {
        "latest": "0.3.0",
        "url": ZIP_URL,
        "size": 1234,
        "notes": "Что нового",
        "html_url": "https://github.com/vvallikk/SwearCounter/releases/tag/v0.3.0",
    }


@pytest.mark.parametrize(
    "release",
    [make_release("v0.2.0"), make_release(prerelease=True), make_release(draft=True),
     make_release(assets=[]), make_release("nightly"), {}],
)
def test_release_info_without_update(release):
    assert release_info(release, current="0.2.0") is None


def test_fetch_latest_parses_json(responses):
    responses[updater_module.LATEST_URL] = json.dumps(make_release()).encode()
    assert fetch_latest()["tag_name"] == "v0.3.0"


def http_error(code):
    return urllib.error.HTTPError(updater_module.LATEST_URL, code, "err", {}, None)


def test_fetch_latest_no_releases_is_empty(responses):
    responses[updater_module.LATEST_URL] = http_error(404)
    assert fetch_latest() == {}


@pytest.mark.parametrize(
    "error, text",
    [(http_error(403), "ограничил"), (http_error(500), "500"), (urllib.error.URLError("offline"), "нет связи")],
)
def test_fetch_latest_errors(responses, error, text):
    responses[updater_module.LATEST_URL] = error
    with pytest.raises(RuntimeError, match=text):
        fetch_latest()


# --- проверка ---


def test_check_finds_update_and_remembers_it(updater, responses, settings_path):
    responses[updater_module.LATEST_URL] = json.dumps(make_release()).encode()
    found, changes = [], []

    async def on_change(state):
        changes.append(state["status"])

    updater.on_found = found.append
    updater.on_change = on_change
    assert asyncio.run(updater.check()) == "available"
    assert found == ["0.3.0"]
    assert changes == ["checking", "available"]
    state = updater.state()
    assert state["latest"] == "0.3.0" and state["current"] == "0.2.0" and state["can_install"]
    saved = Settings(settings_path)
    assert saved.get("update_last")["latest"] == "0.3.0"
    assert saved.get("update_checked_at") > 0


def test_check_up_to_date(updater, responses):
    responses[updater_module.LATEST_URL] = json.dumps(make_release("v0.2.0")).encode()
    assert asyncio.run(updater.check()) == "none"
    assert "latest" not in updater.state()


def test_check_error(updater, responses):
    responses[updater_module.LATEST_URL] = http_error(403)
    assert asyncio.run(updater.check()) == "error"
    assert "ограничил" in updater.state()["error"]


def test_auto_check_skips_network_within_interval(updater, settings, responses):
    settings.set("update_checked_at", 1000.0)
    settings.set("update_last", release_info(make_release(), current="0.2.0"))
    asyncio.run(updater.auto_check(now=1000.0 + 60))  # responses пуст: сеть не трогаем
    assert updater.status == "available" and updater.info["latest"] == "0.3.0"


def test_auto_check_ignores_old_remembered_release(settings, tmp_path, responses):
    settings.set("update_checked_at", 1000.0)
    settings.set("update_last", release_info(make_release(), current="0.2.0"))
    updater = Updater(settings, install_dir=tmp_path, frozen=True, current="0.3.0")  # уже обновились
    asyncio.run(updater.auto_check(now=1000.0 + 60))
    assert updater.status == "idle"


def test_auto_check_after_interval(updater, settings, responses):
    settings.set("update_checked_at", 1000.0)
    responses[updater_module.LATEST_URL] = json.dumps(make_release()).encode()
    asyncio.run(updater.auto_check(now=1000.0 + updater_module.CHECK_INTERVAL))
    assert updater.status == "available"


def test_auto_check_disabled(updater, responses):
    updater.set_auto(False)
    asyncio.run(updater.auto_check(now=10**10))
    assert updater.status == "idle" and updater.state()["auto"] is False


# --- скачивание и установка ---


async def check_and_download(updater):
    await updater.check()
    updater.start_download()
    await updater._task


def test_download_unpacks_update(updater, responses):
    responses[updater_module.LATEST_URL] = json.dumps(make_release()).encode()
    responses[ZIP_URL] = make_zip()
    asyncio.run(check_and_download(updater))
    assert updater.status == "ready"
    new = updater.update_dir / "new" / "SwearCounter"
    assert (new / "SwearCounter.exe").read_bytes() == b"exe"
    assert not list(updater.update_dir.glob("*.part"))
    assert updater.state()["progress"] == 1.0


def test_download_rejects_archive_without_exe(updater, responses):
    responses[updater_module.LATEST_URL] = json.dumps(make_release()).encode()
    responses[ZIP_URL] = make_zip(with_exe=False)
    asyncio.run(check_and_download(updater))
    assert updater.status == "error" and "SwearCounter.exe" in updater.error
    assert not updater.update_dir.exists()


def test_cancel_download(updater, responses):
    responses[updater_module.LATEST_URL] = json.dumps(make_release()).encode()
    responses[ZIP_URL] = SlowResponse(make_zip())

    async def scenario():
        await updater.check()
        updater.start_download()
        while updater.done_bytes == 0:
            await asyncio.sleep(0.001)
        assert updater.cancel()
        await updater._task

    asyncio.run(scenario())
    assert updater.status == "available"
    assert not updater.update_dir.exists()


def test_download_only_in_frozen_app(settings, tmp_path):
    updater = Updater(settings, install_dir=tmp_path, frozen=False)
    updater.info = release_info(make_release(), current="0.2.0")
    with pytest.raises(ValueError, match="exe"):
        updater.start_download()


def test_apply_requires_downloaded_update(updater):
    with pytest.raises(ValueError):
        updater.apply()


def test_apply_starts_script(updater, responses, monkeypatch):
    responses[updater_module.LATEST_URL] = json.dumps(make_release()).encode()
    responses[ZIP_URL] = make_zip()
    started = []
    monkeypatch.setattr(updater_module.subprocess, "Popen", lambda args, **kw: started.append(args))
    asyncio.run(check_and_download(updater))
    updater.apply()
    script = updater.update_dir / "apply.cmd"
    assert started == [["cmd", "/c", str(script)]]
    assert "SwearCounter.exe" in script.read_text(encoding="utf-8")


def test_apply_script_replaces_only_program_files(tmp_path):
    source = tmp_path / "update" / "new" / "SwearCounter"
    target = tmp_path / "Счётчик"
    text = apply_script(4242, source, target, tmp_path / "update")
    assert '"PID eq 4242"' in text
    assert f'robocopy "{source / "_internal"}" "{target / "_internal"}" /MIR' in text
    assert f'copy /Y "{source / "SwearCounter.exe"}" "{target / "SwearCounter.exe"}"' in text
    assert f'start "" "{target / "SwearCounter.exe"}"' in text
    for user_file in ("settings.json", "counter.json", "words.txt", "models", "sounds", "webview"):
        assert user_file not in text
    assert text.index("PID eq") < text.index("robocopy") < text.index("start ")
