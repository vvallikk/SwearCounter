"""HTTP API и WebSocket (без /api/sound: звук переписывается отдельно)."""

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.counter import Counter
from app.server import Hub, create_app
from app.settings import Settings
from app.sound import Sound
from app.stt import CATALOG
from conftest import HYPERX, REALTEK, STEAM

ROOT = Path(__file__).resolve().parent.parent
SMALL = "vosk-model-small-ru-0.22"
LARGE = "vosk-model-ru-0.42"


class FakeRecognizer:
    """Те же поля и методы, что использует сервер у VoskRecognizer."""

    def __init__(self, model_path: Path):
        self.model_path = model_path
        self.status = "listening"
        self.load_progress = 0.0
        self.mic_name = REALTEK
        self.mic_error = None
        self.mic_pending = False
        self.monitor = False
        self.monitor_error = None
        self.calls: list[tuple] = []

    async def start(self):
        self.calls.append(("start",))

    async def stop(self):
        self.calls.append(("stop",))

    async def set_model(self, model_path: Path):
        self.calls.append(("set_model", model_path))
        self.model_path = Path(model_path)
        self.status = "loading"

    def set_device(self, device):
        self.calls.append(("set_device", device))
        self.mic_pending = True

    def set_monitor(self, enabled):
        self.calls.append(("set_monitor", enabled))


@pytest.fixture
def recognizer(models_dir):
    (models_dir / SMALL).mkdir()
    return FakeRecognizer(models_dir / SMALL)


@pytest.fixture
def sound(settings, tmp_path):
    return Sound(settings, tmp_path / "sounds")


@pytest.fixture
def hub(counter):
    return Hub(counter)


@pytest.fixture
def client(hub, recognizer, settings, sound, fake_sd):
    app = create_app(hub, recognizer, settings, sound)
    with TestClient(app) as client:
        yield client


# --- счётчик ---


def test_recognizer_started_and_stopped_with_app(hub, recognizer, settings, sound, fake_sd):
    app = create_app(hub, recognizer, settings, sound)
    with TestClient(app):
        assert recognizer.calls == [("start",)]
    assert recognizer.calls == [("start",), ("stop",)]


def test_state_returns_saved_count(counter_path, recognizer, settings, sound, fake_sd):
    counter_path.write_text('{"count": 7}', encoding="utf-8")
    app = create_app(Hub(Counter(counter_path)), recognizer, settings, sound)
    with TestClient(app) as client:
        assert client.get("/api/state").json() == {"count": 7}


def test_increment_and_reset_persist(client, counter_path):
    assert client.post("/api/increment").json() == {"count": 1}
    assert client.post("/api/increment").json() == {"count": 2}
    assert client.get("/api/state").json() == {"count": 2}
    assert Counter(counter_path).value == 2

    assert client.post("/api/reset").json() == {"count": 0}
    assert Counter(counter_path).value == 0


def test_root_redirects_to_control_page(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/control/"


# --- распознавание ---


def test_speech_state(client, recognizer):
    recognizer.mic_error = None
    data = client.get("/api/speech").json()

    assert data["model"] == SMALL
    assert data["status"] == "listening"
    assert data["progress"] == 0.0
    assert data["mic"] == REALTEK
    assert data["mic_error"] is None
    assert data["mic_pending"] is False
    models = {m["id"]: m["installed"] for m in data["models"]}
    assert models == {SMALL: True, LARGE: False}


def test_switch_model_unknown(client, recognizer):
    response = client.post("/api/speech/model", json={"model": "нет-такой"})
    assert response.status_code == 404
    assert recognizer.calls == [("start",)]


class FakeDownloader:
    """Вместо настоящего скачивания: запоминает, что просили, и даёт «закончить» вручную."""

    instances: list["FakeDownloader"] = []

    def __init__(self, on_done):
        self.on_done = on_done
        self.started: list[str] = []
        self.cancelled: list[str] = []
        self.states: dict[str, dict] = {}
        FakeDownloader.instances.append(self)

    def state(self, model_id):
        return self.states.get(model_id)

    def start(self, model):
        self.started.append(model.id)
        self.states[model.id] = {"status": "downloading", "progress": 0.0}

    def cancel(self, model_id):
        if model_id not in self.states:
            return False
        self.cancelled.append(model_id)
        del self.states[model_id]
        return True

    async def stop(self):
        pass


@pytest.fixture
def downloader(monkeypatch):
    from app import server

    FakeDownloader.instances.clear()
    monkeypatch.setattr(server, "ModelDownloader", FakeDownloader)
    return FakeDownloader.instances


def finish_download(client, downloader, models_dir, model_id):
    """Имитирует конец скачивания: папка модели появилась, сервер узнал об этом."""
    (models_dir / model_id).mkdir()
    downloader[0].states.pop(model_id, None)
    model = next(m for m in CATALOG if m.id == model_id)
    client.portal.call(downloader[0].on_done, model)


def test_switch_model_not_installed_starts_download(downloader, client, recognizer, settings):
    response = client.post("/api/speech/model", json={"model": LARGE})

    assert response.status_code == 200
    assert downloader[0].started == [LARGE]
    large = next(m for m in response.json()["models"] if m["id"] == LARGE)
    assert large["download"]["status"] == "downloading"
    assert response.json()["wanted"] == LARGE
    assert recognizer.calls == [("start",)]  # модель переключится только после скачивания
    assert settings.get("model") is None


def test_downloaded_model_is_switched_on(downloader, client, recognizer, models_dir, settings_path):
    client.post("/api/speech/model", json={"model": LARGE})

    finish_download(client, downloader, models_dir, LARGE)

    assert recognizer.calls[-1] == ("set_model", models_dir / LARGE)
    assert Settings(settings_path).get("model") == LARGE


def test_downloaded_model_not_switched_if_other_chosen(downloader, client, recognizer, models_dir):
    client.post("/api/speech/model", json={"model": LARGE})
    data = client.post("/api/speech/model", json={"model": SMALL}).json()  # передумали, пока качалось
    assert data["wanted"] is None

    finish_download(client, downloader, models_dir, LARGE)

    assert recognizer.calls == [("start",)]


def test_cancel_download(downloader, client, recognizer, models_dir):
    client.post("/api/speech/model", json={"model": LARGE})

    response = client.delete(f"/api/speech/download/{LARGE}")

    assert response.status_code == 200
    assert downloader[0].cancelled == [LARGE]
    assert all(m["download"] is None for m in response.json()["models"])
    assert client.delete(f"/api/speech/download/{LARGE}").status_code == 404


def test_model_without_files_starts_after_download(downloader, client, recognizer, models_dir):
    recognizer.status = "no_model"  # первый запуск: ни одной модели не скачано
    client.post("/api/speech/model", json={"model": SMALL})
    assert recognizer.calls[-1] == ("set_model", models_dir / SMALL)


def test_switch_model_saves_choice(client, recognizer, models_dir, settings_path):
    (models_dir / LARGE).mkdir()

    response = client.post("/api/speech/model", json={"model": LARGE})

    assert response.status_code == 200
    assert response.json()["model"] == LARGE
    assert response.json()["status"] == "loading"
    assert recognizer.calls[-1] == ("set_model", models_dir / LARGE)
    assert Settings(settings_path).get("model") == LARGE


def test_switch_to_current_model_does_nothing(client, recognizer, settings):
    response = client.post("/api/speech/model", json={"model": SMALL})
    assert response.status_code == 200
    assert recognizer.calls == [("start",)]


def test_switch_model_requires_model_field(client):
    assert client.post("/api/speech/model", json={}).status_code == 422


# --- микрофоны ---


def test_devices(client, settings, fake_sd):
    settings.set("device", HYPERX)

    data = client.get("/api/devices").json()

    assert data == {"devices": [REALTEK, HYPERX, STEAM], "default": REALTEK, "selected": HYPERX}
    assert fake_sd.refreshes == 1  # список перечитан: микрофон могли подключить


def test_select_device_saves_and_switches(client, recognizer, settings_path):
    response = client.post("/api/speech/device", json={"device": HYPERX})

    assert response.status_code == 200
    assert response.json()["mic_pending"] is True
    assert recognizer.calls[-1] == ("set_device", HYPERX)
    assert Settings(settings_path).get("device") == HYPERX


def test_select_default_device(client, recognizer, settings, settings_path):
    settings.set("device", HYPERX)

    response = client.post("/api/speech/device", json={"device": None})

    assert response.status_code == 200
    assert recognizer.calls[-1] == ("set_device", None)
    assert Settings(settings_path).get("device") is None


def test_select_unknown_device(client, recognizer, settings):
    settings.set("device", HYPERX)

    response = client.post("/api/speech/device", json={"device": "USB микрофон"})

    assert response.status_code == 404
    assert settings.get("device") == HYPERX
    assert ("set_device", "USB микрофон") not in recognizer.calls


def test_select_device_requires_exact_name(client):
    # Часть имени подходит для --device, но не для выбора на странице.
    assert client.post("/api/speech/device", json={"device": "steam"}).status_code == 404


# --- WebSocket ---


def receive_until(ws, kind: str, limit: int = 5) -> dict:
    """Пропускает прочие сообщения (например, о звуке) до сообщения типа kind."""
    for _ in range(limit):
        message = ws.receive_json()
        if message["type"] == kind:
            return message
    raise AssertionError(f"нет сообщения {kind}")


def test_ws_greets_with_state_first(client):
    client.post("/api/increment")
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == {"type": "state", "count": 1}


def test_ws_broadcasts_increment_and_reset(client):
    with client.websocket_connect("/ws") as first, client.websocket_connect("/ws") as second:
        for ws in (first, second):
            assert ws.receive_json()["type"] == "state"

        client.post("/api/increment")
        client.post("/api/reset")

        for ws in (first, second):
            assert receive_until(ws, "increment") == {"type": "increment", "count": 1, "delta": 1}
            assert receive_until(ws, "state") == {"type": "state", "count": 0}


def test_ws_disconnect_removes_client(client, hub):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.get("/api/state")  # даём серверу закончить подключение
        assert len(hub.clients) == 1
    # После закрытия рассылка не падает и клиент забыт.
    assert client.post("/api/increment").json() == {"count": 1}
    assert len(hub.clients) == 0


# --- прослушивание микрофона ---


def test_monitor_toggles_on_recognizer(client, recognizer):
    data = client.post("/api/speech/monitor", json={"enabled": True}).json()
    assert ("set_monitor", True) in recognizer.calls
    assert data["monitor"] is False  # включится, когда воркер подтвердит
    recognizer.monitor = True
    assert client.get("/api/speech").json()["monitor"] is True


def test_reselecting_failed_model_restarts_it(client, recognizer):
    recognizer.status = "error"
    client.post("/api/speech/model", json={"model": SMALL})
    assert ("set_model", recognizer.model_path) in recognizer.calls


# --- звуки оповещения ---

WAV = b"RIFF fake wav"


def upload(client, name="дзынь.wav", data=WAV, content_type="audio/wav"):
    from urllib.parse import quote

    return client.put(
        "/api/sound/file",
        content=data,
        headers={"Content-Type": content_type, "X-Filename": quote(name)},
    )


def test_upload_select_and_delete_sound(client):
    state = upload(client).json()
    sound_id = state["active"]
    assert state["sounds"] == [{"id": sound_id, "name": "дзынь.wav"}]
    assert client.get(f"/api/sound/file/{sound_id}").content == WAV

    assert client.post("/api/sound/active", json={"id": None}).json()["active"] is None
    assert client.post("/api/sound/active", json={"id": sound_id}).json()["active"] == sound_id

    state = client.delete(f"/api/sound/file/{sound_id}").json()
    assert state["sounds"] == [] and state["active"] is None
    assert client.get(f"/api/sound/file/{sound_id}").status_code == 404


def test_upload_rejects_wrong_type(client):
    response = upload(client, data=b"text", content_type="text/plain")
    assert response.status_code == 400
    assert "MP3" in response.json()["detail"]


def test_unknown_sound_is_404(client):
    assert client.post("/api/sound/active", json={"id": "nope"}).status_code == 404
    assert client.delete("/api/sound/file/nope").status_code == 404


def test_volume(client):
    assert client.post("/api/sound/volume", json={"volume": 30}).json()["volume"] == 30
    assert client.get("/api/sound").json()["volume"] == 30


def test_sound_changes_reach_overlays(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # state
        assert ws.receive_json()["type"] == "sound"
        ws.receive_json()  # style
        client.post("/api/sound/volume", json={"volume": 55})
        message = ws.receive_json()
        assert message["type"] == "sound" and message["volume"] == 55


# --- оформление оверлея ---


def test_ws_greeting_includes_sound_and_style(client):
    with client.websocket_connect("/ws") as ws:
        types_ = [ws.receive_json()["type"] for _ in range(3)]
    assert types_ == ["state", "sound", "style"]


def test_preset_is_saved_and_broadcast(client, settings_path):
    with client.websocket_connect("/ws") as ws:
        for _ in range(3):
            ws.receive_json()
        assert client.post("/api/overlay/preset", json={"preset": "neon"}).json()["preset"] == "neon"
        assert ws.receive_json() == {"type": "style", "preset": "neon", "label": "", "label_position": "left"}
    assert client.get("/api/overlay").json()["preset"] == "neon"
    assert Settings(settings_path).get("overlay_preset") == "neon"


def test_default_overlay_style(client):
    assert client.get("/api/overlay").json() == {"preset": "classic", "label": "", "label_position": "left"}


PRESET_IDS = re.findall(r'id: "([^"]+)"', (ROOT / "overlay" / "presets.js").read_text(encoding="utf-8"))


@pytest.mark.parametrize("preset", PRESET_IDS)
def test_every_overlay_preset_is_accepted(client, preset):
    assert client.post("/api/overlay/preset", json={"preset": preset}).json()["preset"] == preset


def test_ferret_preset_is_listed():
    assert "ferret" in PRESET_IDS


@pytest.mark.parametrize("preset", ["", "Neon", "../etc", "a" * 33])
def test_invalid_preset_rejected(client, preset):
    assert client.post("/api/overlay/preset", json={"preset": preset}).status_code == 400


def test_label_is_saved_and_broadcast(client, settings_path):
    with client.websocket_connect("/ws") as ws:
        for _ in range(3):
            ws.receive_json()
        response = client.post("/api/overlay/label", json={"text": "  Маты:\n ", "position": "top"})
        assert response.json() == {"preset": "classic", "label": "Маты:", "label_position": "top"}
        assert ws.receive_json() == {"type": "style", "preset": "classic", "label": "Маты:", "label_position": "top"}
    assert Settings(settings_path).get("overlay_label") == "Маты:"
    assert Settings(settings_path).get("overlay_label_position") == "top"


def test_label_whitespace_is_collapsed(client):
    response = client.post("/api/overlay/label", json={"text": "Маты\tза\n\nстрим", "position": "left"})
    assert response.json()["label"] == "Маты за стрим"


def test_empty_label_is_allowed(client):
    client.post("/api/overlay/label", json={"text": "Маты:", "position": "left"})
    assert client.post("/api/overlay/label", json={"text": "", "position": "left"}).json()["label"] == ""


@pytest.mark.parametrize(
    "body",
    [
        {"text": "а" * 41, "position": "left"},
        {"text": "Маты:", "position": "center"},
        {"text": "Маты:"},
    ],
)
def test_invalid_label_rejected(client, settings_path, body):
    assert client.post("/api/overlay/label", json=body).status_code in (400, 422)
    assert Settings(settings_path).get("overlay_label") is None


def test_version(client):
    from app import __version__

    assert client.get("/api/version").json() == {"version": __version__}


# --- обновления ---


@pytest.fixture
def update_client(hub, recognizer, settings, sound, fake_sd, tmp_path, monkeypatch):
    from app import updater as updater_module

    release = {
        "tag_name": "v9.0.0",
        "html_url": "https://github.com/vvallikk/SwearCounter/releases/tag/v9.0.0",
        "body": "",
        "assets": [{"name": "SwearCounter-v9.0.0-windows.zip", "browser_download_url": "https://x/z.zip", "size": 1}],
    }
    monkeypatch.setattr(updater_module, "fetch_latest", lambda: release)
    updater = updater_module.Updater(settings, install_dir=tmp_path, frozen=False)
    app = create_app(hub, recognizer, settings, sound, updater=updater)
    with TestClient(app) as client:
        yield client, updater


def test_update_state(client):
    state = client.get("/api/update").json()
    assert state["status"] == "idle" and state["auto"] is True and state["can_install"] is False


def test_update_check_is_broadcast(update_client):
    client, _ = update_client
    with client.websocket_connect("/ws") as ws:
        for _ in range(3):
            ws.receive_json()  # state, sound, style
        assert client.post("/api/update/check").json()["latest"] == "9.0.0"
        assert ws.receive_json()["status"] == "checking"
        message = ws.receive_json()
    assert message["type"] == "update" and message["status"] == "available"


def test_update_auto_setting(client, settings_path):
    assert client.post("/api/update/auto", json={"enabled": False}).json()["auto"] is False
    assert Settings(settings_path).get("update_auto") is False


def test_update_download_needs_exe(update_client):
    client, _ = update_client
    client.post("/api/update/check")
    resp = client.post("/api/update/download")
    assert resp.status_code == 400 and "exe" in resp.json()["detail"]


def test_update_cancel_and_apply_without_download(client):
    assert client.delete("/api/update/download").status_code == 404
    assert client.post("/api/update/apply").status_code == 400


def test_update_apply_restarts(update_client, monkeypatch):
    client, updater = update_client
    calls = []
    monkeypatch.setattr(updater, "apply", lambda: calls.append("apply"))
    updater.quit = lambda: calls.append("quit")
    assert client.post("/api/update/apply").status_code == 200
    assert calls == ["apply"]  # выход — чуть позже, после ответа
    deadline = time.monotonic() + 5
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert calls == ["apply", "quit"]
