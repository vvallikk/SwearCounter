import asyncio
import hashlib
import io
import json
import time
import urllib.error
import zipfile
from pathlib import Path

import pytest

from app import updater as updater_module
from app.settings import Settings
from app.updater import (
    Updater,
    apply_script,
    fetch_releases,
    is_newer,
    parse_version,
    pick_update,
    release_info,
    release_notes,
    update_policy,
)

ROOT = Path(__file__).resolve().parent.parent
ZIP_URL = "https://github.com/vvallikk/SwearCounter/releases/download/v0.3.0/SwearCounter-v0.3.0-windows.zip"


def make_zip(with_exe=True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if with_exe:
            zf.writestr("SwearCounter/SwearCounter.exe", b"exe")
        zf.writestr("SwearCounter/_internal/lib.dll", b"dll")
        zf.writestr("SwearCounter/wordlists/swears.txt", "мат")
    return buf.getvalue()


# Архивы собираются один раз: у zip внутри время записи, а хеш должен совпасть с релизом.
ZIP = make_zip()
ZIP_NO_EXE = make_zip(with_exe=False)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def make_release(tag="v0.3.0", zip_data=ZIP, **extra):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/vvallikk/SwearCounter/releases/tag/{tag}",
        "body": "Что нового",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": "checksums.txt", "browser_download_url": "https://example.invalid/sums", "size": 1},
            {
                "name": f"SwearCounter-{tag}-windows.zip",
                "browser_download_url": ZIP_URL,
                "size": 1234,
                "digest": digest(zip_data),
            },
        ],
        **extra,
    }


def releases(*items) -> bytes:
    return json.dumps(list(items)).encode()


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
        "sha256": hashlib.sha256(ZIP).hexdigest(),
        "size": 1234,
        "notes": "Что нового",
        "html_url": "https://github.com/vvallikk/SwearCounter/releases/tag/v0.3.0",
        "force": False,
        "for_version": "0.2.0",
    }


def test_release_info_hides_checks_section():
    # Раздел "Проверка файла" (scripts/release_checks.py) нужен на GitHub, а не в окне программы.
    body = "Что нового\n\n<!-- checks -->\n## Проверка файла · File check\n\n- SHA-256: `abc`\n"
    info = release_info(make_release(body=body), current="0.2.0")
    assert info["notes"] == "Что нового"


def test_release_notes_without_checks_section():
    assert release_notes("Что нового\n") == "Что нового"
    assert release_notes("") == ""


@pytest.mark.parametrize(
    "release",
    [make_release("v0.2.0"), make_release(prerelease=True), make_release(draft=True),
     make_release(assets=[]), make_release("nightly"), {}],
)
def test_release_info_without_update(release):
    assert release_info(release, current="0.2.0") is None


def test_fetch_releases_parses_json(responses):
    responses[updater_module.RELEASES_URL] = releases(make_release())
    assert fetch_releases()[0]["tag_name"] == "v0.3.0"


def http_error(code):
    return urllib.error.HTTPError(updater_module.RELEASES_URL, code, "err", {}, None)


def test_fetch_releases_no_releases_is_empty(responses):
    responses[updater_module.RELEASES_URL] = http_error(404)
    assert fetch_releases() == []


@pytest.mark.parametrize(
    "error, text",
    [(http_error(403), "ограничил"), (http_error(500), "500"), (urllib.error.URLError("offline"), "нет связи")],
)
def test_fetch_releases_errors(responses, error, text):
    responses[updater_module.RELEASES_URL] = error
    with pytest.raises(RuntimeError, match=text):
        fetch_releases()


# --- проверка ---


def test_check_finds_update_and_remembers_it(updater, responses, settings_path):
    responses[updater_module.RELEASES_URL] = releases(make_release())
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
    responses[updater_module.RELEASES_URL] = releases(make_release("v0.2.0"))
    assert asyncio.run(updater.check()) == "none"
    assert "latest" not in updater.state()


def test_check_error(updater, responses):
    responses[updater_module.RELEASES_URL] = http_error(403)
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
    responses[updater_module.RELEASES_URL] = releases(make_release())
    updater = Updater(settings, install_dir=tmp_path, frozen=True, current="0.3.0")  # уже обновились
    asyncio.run(updater.auto_check(now=1000.0 + 60))  # прошлый результат — для 0.2.0, проверяем заново
    assert updater.status == "none"


def test_auto_check_after_interval(updater, settings, responses):
    settings.set("update_checked_at", 1000.0)
    responses[updater_module.RELEASES_URL] = releases(make_release())
    asyncio.run(updater.auto_check(now=1000.0 + updater_module.CHECK_INTERVAL))
    assert updater.status == "available"


def test_auto_check_disabled(updater, responses):
    updater.set_auto(False)
    asyncio.run(updater.auto_check(now=10**10))
    assert updater.status == "idle" and updater.state()["auto"] is False


# --- типы обновлений ---

FULL_FORCE = "Что нового\n\n<!-- update: full-force -->\n"


def force_for(*versions):
    return f"<!-- update: force {' '.join(versions)} -->\nЧто нового"


@pytest.mark.parametrize(
    "notes, expected",
    [
        ("Просто заметки", {"type": "minor", "versions": []}),
        ("", {"type": "minor", "versions": []}),
        ("<!-- update: minor -->", {"type": "minor", "versions": []}),
        (FULL_FORCE, {"type": "full-force", "versions": []}),
        ("<!--update:FULL-FORCE-->", {"type": "full-force", "versions": []}),
        (force_for("0.2.0", "v0.2.1"), {"type": "force", "versions": ["0.2.0", "0.2.1"]}),
        ("<!-- update: force 0.2.0, 0.2.1 -->", {"type": "force", "versions": ["0.2.0", "0.2.1"]}),
    ],
)
def test_update_policy(notes, expected):
    assert update_policy(notes) == expected


@pytest.mark.parametrize(
    "notes",
    [
        "<!-- update: force -->",
        "<!-- update: force 0.2.x -->",
        "<!-- update: full-force 0.2.0 -->",
        "<!-- update: forse 0.2.0 -->",
        "<!-- update: -->",
        FULL_FORCE + "<!-- update: minor -->",
    ],
)
def test_update_policy_rejects_bad_marker(notes):
    with pytest.raises(ValueError):
        update_policy(notes)


def test_release_notes_markers_are_valid():
    # Пометка из docs/releases попадает в описание релиза: ошибку ловим до выпуска.
    notes = sorted((ROOT / "docs" / "releases").glob("v*.md"))
    assert notes
    for path in notes:
        update_policy(path.read_text(encoding="utf-8"))


def test_pick_update_takes_newest_minor():
    info = pick_update([make_release("v0.3.0"), make_release("v0.4.0"), make_release("v0.1.0")], "0.2.0")
    assert info["latest"] == "0.4.0" and info["force"] is False


def test_pick_update_none_when_up_to_date():
    assert pick_update([make_release("v0.2.0"), make_release("v0.1.0")], "0.2.0") is None
    assert pick_update([], "0.2.0") is None


def test_full_force_blocks_all_older_versions():
    rels = [make_release("v0.3.0", body=FULL_FORCE)]
    assert pick_update(rels, "0.2.0")["force"] is True
    assert pick_update(rels, "0.1.0")["force"] is True
    assert pick_update(rels, "0.3.0") is None


def test_later_minor_does_not_cancel_force():
    # Обязательная 0.3.0, потом обычная 0.4.0: с 0.2.0 обязательно, причём сразу на 0.4.0.
    rels = [make_release("v0.4.0"), make_release("v0.3.0", body=FULL_FORCE)]
    info = pick_update(rels, "0.2.0")
    assert info["latest"] == "0.4.0" and info["force"] is True
    # А тем, кто уже на 0.3.0, 0.4.0 — обычное обновление.
    assert pick_update(rels, "0.3.0")["force"] is False


@pytest.mark.parametrize("current, forced", [("0.2.0", True), ("0.2", True), ("0.2.1", True), ("0.1.0", False)])
def test_force_specific_versions(current, forced):
    rels = [make_release("v0.3.0", body=force_for("0.2.0", "0.2.1"))]
    assert pick_update(rels, current)["force"] is forced


def test_bad_marker_counts_as_minor():
    rels = [make_release("v0.3.0", body="<!-- update: forse 0.2.0 -->")]
    assert pick_update(rels, "0.2.0")["force"] is False


def test_force_release_without_asset_is_ignored():
    rels = [make_release("v0.3.0", body=FULL_FORCE, assets=[]), make_release("v0.2.5")]
    assert pick_update(rels, "0.2.0")["force"] is False


def test_forced_update_locks_only_built_program(settings, tmp_path, responses):
    responses[updater_module.RELEASES_URL] = releases(make_release(body=FULL_FORCE))
    built = Updater(settings, install_dir=tmp_path, frozen=True, current="0.2.0")
    asyncio.run(built.check())
    assert built.state()["force"] is True and built.state()["locked"] is True
    source = Updater(settings, install_dir=tmp_path, frozen=False, current="0.2.0")
    asyncio.run(source.check())
    assert source.state()["force"] is True and source.state()["locked"] is False


def test_lock_survives_failed_recheck(updater, responses):
    responses[updater_module.RELEASES_URL] = releases(make_release(body=FULL_FORCE))
    asyncio.run(updater.check())
    responses[updater_module.RELEASES_URL] = http_error(500)
    asyncio.run(updater.check())
    assert updater.status == "error" and updater.locked


def test_minor_update_does_not_lock(updater, responses):
    responses[updater_module.RELEASES_URL] = releases(make_release())
    asyncio.run(updater.check())
    assert updater.state()["force"] is False and updater.state()["locked"] is False


def test_auto_check_disabled_still_finds_forced(updater, responses):
    # Галочка «проверять при запуске» не отключает обязательное обновление.
    updater.set_auto(False)
    responses[updater_module.RELEASES_URL] = releases(make_release(body=FULL_FORCE))
    asyncio.run(updater.auto_check(now=10**10))
    assert updater.status == "available" and updater.locked


def test_auto_check_disabled_hides_minor_quietly(updater, responses):
    updater.set_auto(False)
    changes = []

    async def on_change(state):
        changes.append(state["status"])

    updater.on_change = on_change
    responses[updater_module.RELEASES_URL] = releases(make_release())
    asyncio.run(updater.auto_check(now=10**10))
    assert updater.status == "idle" and changes == []


def test_auto_check_disabled_quiet_on_error(updater, responses):
    updater.set_auto(False)
    responses[updater_module.RELEASES_URL] = http_error(403)
    asyncio.run(updater.auto_check(now=10**10))
    assert updater.status == "idle" and updater.error is None


def test_auto_check_remembered_force_keeps_lock(updater, settings, responses):
    settings.set("update_checked_at", 1000.0)
    settings.set("update_last", release_info(make_release(body=FULL_FORCE), current="0.2.0"))
    updater.set_auto(False)
    asyncio.run(updater.auto_check(now=1000.0 + 60))  # responses пуст: сеть не трогаем
    assert updater.status == "available" and updater.locked


def test_auto_check_remembered_nothing_within_interval(updater, settings, responses):
    settings.set("update_checked_at", 1000.0)
    settings.set("update_last", None)
    asyncio.run(updater.auto_check(now=1000.0 + 60))
    assert updater.status == "idle"


def test_auto_check_old_format_rechecks(updater, settings, responses):
    # update_last без for_version (от прошлых версий программы) не доверяем.
    last = release_info(make_release(), current="0.2.0")
    del last["for_version"], last["force"]
    settings.set("update_checked_at", 1000.0)
    settings.set("update_last", last)
    responses[updater_module.RELEASES_URL] = releases(make_release(body=FULL_FORCE))
    asyncio.run(updater.auto_check(now=1000.0 + 60))
    assert updater.locked


# --- скачивание и установка ---


async def check_and_download(updater):
    await updater.check()
    updater.start_download()
    await updater._task


def test_download_unpacks_update(updater, responses):
    responses[updater_module.RELEASES_URL] = releases(make_release())
    responses[ZIP_URL] = ZIP
    asyncio.run(check_and_download(updater))
    assert updater.status == "ready"
    new = updater.update_dir / "new" / "SwearCounter"
    assert (new / "SwearCounter.exe").read_bytes() == b"exe"
    assert not list(updater.update_dir.glob("*.part"))
    assert updater.state()["progress"] == 1.0


def test_download_rejects_archive_without_exe(updater, responses):
    responses[updater_module.RELEASES_URL] = releases(make_release(zip_data=ZIP_NO_EXE))
    responses[ZIP_URL] = ZIP_NO_EXE
    asyncio.run(check_and_download(updater))
    assert updater.status == "error" and "SwearCounter.exe" in updater.error
    assert not updater.update_dir.exists()


def test_download_rejects_damaged_archive(updater, responses):
    responses[updater_module.RELEASES_URL] = releases(make_release())
    responses[ZIP_URL] = ZIP_NO_EXE  # другой архив: хеш не совпадает с релизом
    asyncio.run(check_and_download(updater))
    assert updater.status == "error" and "контрольная сумма" in updater.error
    assert not updater.update_dir.exists()


def test_download_requires_checksum(updater, responses):
    release = make_release()
    del release["assets"][1]["digest"]
    responses[updater_module.RELEASES_URL] = releases(release)
    asyncio.run(check_and_download(updater))
    assert updater.status == "error" and "контрольной суммы" in updater.error


@pytest.mark.parametrize("value", [None, "", "md5:abc", "sha256:xyz", "sha256:" + "a" * 63])
def test_sha256_of_rejects_bad_digest(value):
    assert updater_module.sha256_of({"digest": value}) is None


def test_cancel_download(updater, responses):
    responses[updater_module.RELEASES_URL] = releases(make_release())
    responses[ZIP_URL] = SlowResponse(ZIP)

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
    responses[updater_module.RELEASES_URL] = releases(make_release())
    responses[ZIP_URL] = ZIP
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
    for user_file in ("settings.json", "counter.json", "wordlists", "models", "sounds", "webview"):
        assert user_file not in text
    assert text.index("PID eq") < text.index("robocopy") < text.index("start ")
