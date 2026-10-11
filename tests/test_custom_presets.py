"""Личные оформления: установка zip-наборов, проверки архива и API сервера."""

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import custom_presets as module
from app.custom_presets import CustomPresets, builtin_preset_ids
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
    assert {"classic", "neon", "ferret"} <= BUILTIN


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
