"""Личные оформления: установка zip-наборов, проверки архива и API сервера."""

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import custom_presets as module
from app.custom_presets import CustomPresets, builtin_preset_ids, pack_folder
from app.server import Hub, create_app
from app.settings import Settings
from app.sound import Sound

ROOT = Path(__file__).resolve().parent.parent
BUILTIN = builtin_preset_ids(ROOT / "overlay")
MANIFEST = {
    "id": "vasya-gold",
    "title": "Золото Васи",
    "description": "Золотые цифры и монетки.",
    "color": "#ffd700",
    "owner": "Вася",
    "animation": "explosion",
    "sound": "coin.wav",
}


def make_zip(files: dict[str, bytes | str | dict | list], folder: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            if isinstance(content, (dict, list)):
                content = json.dumps(content, ensure_ascii=False)
            if isinstance(content, str):
                content = content.encode("utf-8")
            archive.writestr(folder + name, content)
    return buffer.getvalue()


def pack(**manifest) -> bytes:
    return make_zip(
        {
            "preset.json": {**MANIFEST, **manifest},
            "style.css": ':root[data-preset="vasya-gold"] .value { color: gold; }',
            "animation.js": 'registerOverlayAnimation("vasya-gold", (d, api) => api.floatPlus(d));',
            "coin.wav": b"RIFF....WAVE",
            "img/coin.png": b"\x89PNG",
        }
    )


@pytest.fixture
def presets(tmp_path):
    return CustomPresets(tmp_path / "presets", BUILTIN)


def test_builtin_ids_read_from_presets_js():
    assert {"classic", "neon", "explosion"} <= BUILTIN
    assert "ferret" not in BUILTIN  # личный набор, не встроенный


def test_install_and_list(presets):
    info = presets.install(pack())
    assert info == {
        "id": "vasya-gold",
        "title": "Золото Васи",
        "description": "Золотые цифры и монетки.",
        "color": "#ffd700",
        "owner": "Вася",
        "animation": "explosion",
        "custom": True,
        "sound": "/overlay/custom/vasya-gold/coin.wav",
        "style": "/overlay/custom/vasya-gold/style.css",
        "script": "/overlay/custom/vasya-gold/animation.js",
    }
    assert presets.list() == [info]
    assert (presets.directory / "vasya-gold" / "img" / "coin.png").read_bytes() == b"\x89PNG"


def test_minimal_pack(presets):
    info = presets.install(make_zip({"preset.json": {"id": "plain", "title": "Просто"}}))
    assert info["color"] == "#ffffff"
    assert info["style"] is info["script"] is info["sound"] is info["animation"] is None
    assert info["owner"] == ""


def test_pack_inside_single_folder(presets):
    # «Сжать папку» в Проводнике кладёт всё в одну общую папку.
    data = make_zip({"preset.json": {"id": "boxed", "title": "В папке"}, "style.css": ""}, folder="Мой набор/")
    assert presets.install(data)["style"] == "/overlay/custom/boxed/style.css"


def test_reinstall_replaces_old_files(presets):
    presets.install(pack())
    presets.install(make_zip({"preset.json": {**MANIFEST, "sound": None}}))
    folder = presets.directory / "vasya-gold"
    assert sorted(p.name for p in folder.iterdir()) == ["preset.json"]
    assert len(presets.list()) == 1


def test_remove(presets):
    presets.install(pack())
    presets.remove("vasya-gold")
    assert presets.list() == []
    assert not (presets.directory / "vasya-gold").exists()
    with pytest.raises(KeyError):
        presets.remove("vasya-gold")


@pytest.mark.parametrize("bad", ["../settings", "classic", ".hidden", ""])
def test_remove_rejects_unknown(presets, bad):
    presets.install(pack())
    with pytest.raises(KeyError):
        presets.remove(bad)
    assert presets.ids() == {"vasya-gold"}


@pytest.mark.parametrize(
    "data, message",
    [
        (b"not a zip", "не zip"),
        (make_zip({"style.css": ""}), "нет preset.json"),
        (make_zip({"preset.json": "{oops"}), "не читается"),
        (make_zip({"preset.json": ["id"]}), "объектом"),
        (make_zip({"preset.json": {"id": "Bad Id", "title": "x"}}), "id в preset.json"),
        (make_zip({"preset.json": {"id": "neon", "title": "x"}}), "занят"),
        (make_zip({"preset.json": {"id": "ok"}}), "нет title"),
        (make_zip({"preset.json": {"id": "ok", "title": "x" * 41}}), "title"),
        (make_zip({"preset.json": {"id": "ok", "title": "x", "color": "red"}}), "color"),
        (make_zip({"preset.json": {"id": "ok", "title": "x", "animation": "<script>"}}), "animation"),
        (make_zip({"preset.json": {"id": "ok", "title": "x", "sound": "../a.mp3"}}), "sound"),
        (make_zip({"preset.json": {"id": "ok", "title": "x", "sound": "a.exe"}}), "sound"),
        (make_zip({"preset.json": {"id": "ok", "title": "x", "sound": "a.mp3"}}), "нет в архиве"),
        (make_zip({"preset.json": {"id": "ok", "title": "x"}, "run.exe": b"MZ"}), "не подходит"),
        (make_zip({"preset.json": {"id": "ok", "title": "x"}, "../evil.css": ""}), "Недопустимый путь"),
        (make_zip({"preset.json": {"id": "ok", "title": "x"}, "/abs.css": ""}), "Недопустимый путь"),
        (make_zip({"preset.json": {"id": "ok", "title": "x"}, "C:/win.css": ""}), "Недопустимый путь"),
        (make_zip({"__MACOSX/._preset.json": ""}), "пустой"),
    ],
)
def test_bad_packs_rejected(presets, data, message):
    with pytest.raises(ValueError, match=message):
        presets.install(data)
    assert presets.list() == []


def test_traversal_writes_nothing_outside(presets, tmp_path):
    with pytest.raises(ValueError):
        presets.install(make_zip({"preset.json": {"id": "ok", "title": "x"}, "../../evil.js": "x"}))
    assert not (tmp_path / "evil.js").exists()


def test_size_and_count_limits(presets, monkeypatch):
    monkeypatch.setattr(module, "MAX_PACK_BYTES", 1000)
    with pytest.raises(ValueError, match="больше"):
        presets.install(make_zip({"preset.json": {"id": "ok", "title": "x"}, "big.png": b"\0" * 5000}))
    monkeypatch.setattr(module, "MAX_PACK_FILES", 2)
    files = {"preset.json": {"id": "ok", "title": "x"}, "a.png": b"", "b.png": b""}
    with pytest.raises(ValueError, match="файлов"):
        presets.install(make_zip(files))


def test_presets_count_limit(presets, monkeypatch):
    monkeypatch.setattr(module, "MAX_PRESETS", 1)
    presets.install(pack())
    presets.install(pack())  # переустановка того же — не новый набор
    with pytest.raises(ValueError, match="Уже установлено"):
        presets.install(make_zip({"preset.json": {"id": "other", "title": "x"}}))


def test_broken_folders_are_skipped(presets):
    presets.install(pack())
    (presets.directory / "junk").mkdir()
    (presets.directory / "renamed").mkdir()
    (presets.directory / "renamed" / "preset.json").write_text(json.dumps({"id": "other", "title": "x"}))
    (presets.directory / "neon").mkdir()  # встроенный id нельзя подменить и вручную
    (presets.directory / "neon" / "preset.json").write_text(json.dumps({"id": "neon", "title": "x"}))
    assert presets.ids() == {"vasya-gold"}


def test_list_without_directory(tmp_path):
    assert CustomPresets(tmp_path / "missing").list() == []


# --- Упаковка папки и экспорт ---


def test_pack_folder_installs_back(presets, tmp_path):
    folder = tmp_path / "src" / "my-folder"
    (folder / "img").mkdir(parents=True)
    (folder / "preset.json").write_text(json.dumps(MANIFEST, ensure_ascii=False), encoding="utf-8")
    (folder / "coin.wav").write_bytes(b"RIFF....WAVE")
    (folder / "img" / "coin.png").write_bytes(b"png-data")
    (folder / "Thumbs.db").write_bytes(b"junk")
    (folder / ".git").mkdir()
    (folder / ".git" / "config").write_text("x")
    info, data = pack_folder(folder, BUILTIN)
    assert info["id"] == "vasya-gold"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert sorted(archive.namelist()) == ["vasya-gold/coin.wav", "vasya-gold/img/coin.png", "vasya-gold/preset.json"]
    presets.install(data)
    assert (presets.directory / "vasya-gold" / "img" / "coin.png").read_bytes() == b"png-data"


@pytest.mark.parametrize(
    "files, message",
    [
        ({}, "нет preset.json"),
        ({"preset.json": "{"}, "не читается"),
        ({"preset.json": json.dumps({**MANIFEST, "id": "classic"})}, "встроенным"),
        ({"preset.json": json.dumps(MANIFEST)}, "Звука coin.wav нет"),
        ({"preset.json": json.dumps({**MANIFEST, "sound": None}), "run.exe": "x"}, "не подходит"),
    ],
)
def test_pack_folder_rejects_what_install_would(tmp_path, files, message):
    folder = tmp_path / "pack"
    folder.mkdir()
    for name, content in files.items():
        (folder / name).write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        pack_folder(folder, BUILTIN)


def test_export_roundtrip(presets, tmp_path):
    presets.install(pack())
    data = presets.export("vasya-gold")
    other = CustomPresets(tmp_path / "other", BUILTIN)
    other.install(data)
    assert other.list() == presets.list()


def test_export_unknown(presets):
    with pytest.raises(KeyError):
        presets.export("nope")


def test_pack_preset_script(tmp_path, capsys):
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import pack_preset
    finally:
        sys.path.pop(0)
    folder = tmp_path / "pack"
    folder.mkdir()
    (folder / "preset.json").write_text(json.dumps({"id": "mini", "title": "Мини"}), encoding="utf-8")
    assert pack_preset.main([str(folder)]) == 0
    assert (tmp_path / "mini.zip").is_file()
    (folder / "preset.json").write_text("{}", encoding="utf-8")
    assert pack_preset.main([str(folder)]) == 1
    assert "Ошибка" in capsys.readouterr().err


# --- API сервера ---


@pytest.fixture
def presets_client(counter, recognizer_stub, settings, tmp_path, fake_sd, presets):
    app = create_app(Hub(counter), recognizer_stub, settings, Sound(settings, tmp_path / "sounds"), custom_presets=presets)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def recognizer_stub(models_dir):
    from test_server import SMALL, FakeRecognizer

    (models_dir / SMALL).mkdir()
    return FakeRecognizer(models_dir / SMALL)


def install(client, data: bytes):
    return client.put("/api/presets/custom", content=data, headers={"Content-Type": "application/zip"})


def skip_greeting(ws):
    for _ in range(3):
        ws.receive_json()


def test_api_install_serves_files_and_script(presets_client):
    with presets_client.websocket_connect("/ws") as ws:
        skip_greeting(ws)
        r = install(presets_client, pack())
        assert r.status_code == 200 and r.json()["id"] == "vasya-gold"
        assert ws.receive_json() == {"type": "presets"}
        assert ws.receive_json()["type"] == "style"
    assert [p["id"] for p in presets_client.get("/api/presets/custom").json()] == ["vasya-gold"]
    css = presets_client.get("/overlay/custom/vasya-gold/style.css")
    assert css.status_code == 200 and "gold" in css.text
    assert presets_client.get("/overlay/custom/vasya-gold/img/coin.png").content == b"\x89PNG"
    script = presets_client.get("/overlay/custom-presets.js")
    assert script.headers["content-type"].startswith("text/javascript")
    assert script.text.startswith("window.registerCustomPresets([")
    assert '"owner": "Вася"' in script.text
    # Встроенные файлы оверлея по-прежнему отдаются.
    assert presets_client.get("/overlay/presets.js").status_code == 200


def test_api_rejects_bad_pack(presets_client):
    r = install(presets_client, b"nope")
    assert r.status_code == 400 and "zip" in r.json()["detail"]


def test_api_rejects_oversized_pack(presets_client, monkeypatch):
    from app import server

    monkeypatch.setattr(server, "MAX_PACK_BYTES", 10)
    assert install(presets_client, pack()).status_code == 413


def test_api_remove_resets_active_preset(presets_client, settings_path):
    install(presets_client, pack())
    presets_client.post("/api/overlay/preset", json={"preset": "vasya-gold"})
    with presets_client.websocket_connect("/ws") as ws:
        skip_greeting(ws)
        assert presets_client.delete("/api/presets/custom/vasya-gold").json() == []
        assert ws.receive_json() == {"type": "presets"}
        assert ws.receive_json()["preset"] == "classic"
    assert Settings(settings_path).get("overlay_preset") == "classic"
    assert presets_client.get("/overlay/custom/vasya-gold/style.css").status_code == 404


def test_api_remove_keeps_other_active_preset(presets_client):
    install(presets_client, pack())
    presets_client.post("/api/overlay/preset", json={"preset": "neon"})
    presets_client.delete("/api/presets/custom/vasya-gold")
    assert presets_client.get("/api/overlay").json()["preset"] == "neon"


def test_api_remove_unknown(presets_client):
    assert presets_client.delete("/api/presets/custom/nope").status_code == 404


def test_api_foreign_origin_cannot_install(presets_client):
    r = presets_client.put("/api/presets/custom", content=pack(), headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert presets_client.get("/api/presets/custom").json() == []


def test_script_without_custom_presets(fake_sd, counter, recognizer_stub, settings, tmp_path):
    app = create_app(Hub(counter), recognizer_stub, settings, Sound(settings, tmp_path / "sounds"))
    with TestClient(app) as client:
        assert client.get("/overlay/custom-presets.js").text == "window.registerCustomPresets([]);\n"
        assert client.get("/api/presets/custom").status_code == 404


def test_api_install_from_link(presets_client, monkeypatch):
    from app import preset_links

    seen = []
    monkeypatch.setattr(preset_links, "download", lambda url: seen.append(url) or pack())
    r = presets_client.post("/api/presets/custom/url", json={"url": "https://disk.yandex.ru/d/AbCd"})
    assert r.status_code == 200 and r.json()["id"] == "vasya-gold"
    assert seen == ["https://disk.yandex.ru/d/AbCd"]
    assert [p["id"] for p in presets_client.get("/api/presets/custom").json()] == ["vasya-gold"]


def test_api_install_from_link_errors(presets_client, monkeypatch):
    from app import preset_links

    def fail(url):
        raise ValueError("Google Диск не отдал файл")

    monkeypatch.setattr(preset_links, "download", fail)
    r = presets_client.post("/api/presets/custom/url", json={"url": "https://drive.google.com/file/d/1/view"})
    assert r.status_code == 400 and "Google" in r.json()["detail"]
    monkeypatch.setattr(preset_links, "download", lambda url: b"not a zip")
    r = presets_client.post("/api/presets/custom/url", json={"url": "https://example.com/a.zip"})
    assert r.status_code == 400 and "zip" in r.json()["detail"]
    r = presets_client.post("/api/presets/custom/url", json={"url": "https://example.com/a.zip"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_api_export_saves_to_downloads(presets_client, monkeypatch, tmp_path):
    from app import server

    revealed = []
    monkeypatch.setattr(server, "downloads_dir", lambda: tmp_path)
    monkeypatch.setattr(server, "reveal", revealed.append)
    install(presets_client, pack())
    r = presets_client.post("/api/presets/custom/vasya-gold/export")
    assert r.status_code == 200
    path = tmp_path / "vasya-gold.zip"
    assert r.json() == {"path": str(path)} and revealed == [path]
    assert CustomPresets(tmp_path / "check", BUILTIN).install(path.read_bytes())["id"] == "vasya-gold"
    assert presets_client.post("/api/presets/custom/nope/export").status_code == 404
