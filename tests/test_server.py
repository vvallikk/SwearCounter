"""HTTP API и WebSocket (без /api/sound: звук переписывается отдельно)."""

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.counter import Counter
from app import server
from app.server import Hub, create_app
from app.settings import Settings
from app.sound import Sound
from app.stt import CATALOG
from conftest import GREETING, HYPERX, REALTEK, STEAM, skip_greeting

ROOT = Path(__file__).resolve().parent.parent
SMALL = "vosk-model-small-ru-0.22"
LARGE = "vosk-model-ru-0.42"


class FakeRecognizer:
    """Те же поля и методы, что использует сервер у MicRecognizer."""

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
    with TestClient(app, base_url="http://localhost") as client:
        yield client


# --- счётчик ---


def test_recognizer_started_and_stopped_with_app(hub, recognizer, settings, sound, fake_sd):
    app = create_app(hub, recognizer, settings, sound)
    with TestClient(app, base_url="http://localhost"):
        assert recognizer.calls == [("start",)]
    assert recognizer.calls == [("start",), ("stop",)]


def test_state_returns_saved_count(counter_path, recognizer, settings, sound, fake_sd):
    counter_path.write_text('{"count": 7}', encoding="utf-8")
    app = create_app(Hub(Counter(counter_path)), recognizer, settings, sound)
    with TestClient(app, base_url="http://localhost") as client:
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
    assert models == {m.id: m.id == SMALL for m in CATALOG}


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


def test_download_button_only_downloads(downloader, client, recognizer, models_dir):
    response = client.post(f"/api/speech/download/{LARGE}")

    assert response.status_code == 200
    assert downloader[0].started == [LARGE]
    assert response.json()["wanted"] is None
    finish_download(client, downloader, models_dir, LARGE)
    assert recognizer.calls == [("start",)]  # включают кликом по модели


def test_first_downloaded_model_is_switched_on_without_choice(downloader, client, recognizer, models_dir):
    recognizer.status = "no_model"
    client.post(f"/api/speech/download/{LARGE}")
    finish_download(client, downloader, models_dir, LARGE)
    assert recognizer.calls[-1] == ("set_model", models_dir / LARGE)


def test_download_unknown_or_installed_model(downloader, client):
    assert client.post("/api/speech/download/нет-такой").status_code == 404
    assert client.post(f"/api/speech/download/{SMALL}").status_code == 200
    assert downloader[0].started == []


def test_delete_model(client, recognizer, models_dir):
    (models_dir / LARGE / "am").mkdir(parents=True)
    (models_dir / LARGE / "am" / "final.mdl").write_bytes(b"model")

    response = client.delete(f"/api/speech/model/{LARGE}")

    assert response.status_code == 200
    assert not (models_dir / LARGE).exists()
    assert list(models_dir.iterdir()) == [models_dir / SMALL]  # временной папки не осталось
    large = next(m for m in response.json()["models"] if m["id"] == LARGE)
    assert large["installed"] is False


def test_delete_current_model_refused(client, recognizer, models_dir):
    response = client.delete(f"/api/speech/model/{SMALL}")
    assert response.status_code == 409
    assert (models_dir / SMALL).is_dir()


def test_delete_model_errors(downloader, client, models_dir):
    assert client.delete("/api/speech/model/нет-такой").status_code == 404
    assert client.delete(f"/api/speech/model/{LARGE}").status_code == 404  # не скачана
    client.post(f"/api/speech/download/{LARGE}")
    assert client.delete(f"/api/speech/model/{LARGE}").status_code == 409  # скачивается


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


# --- пауза распознавания ---


def test_pause_is_off_by_default(client):
    assert client.get("/api/pause").json() == {"paused": False}


def test_pause_stops_only_speech(client, hub):
    import asyncio

    assert client.post("/api/pause", json={"paused": True}).json() == {"paused": True}
    assert asyncio.run(hub.increment(2, speech=True)) == 0
    # Кнопка «+1» и горячие клавиши на паузе работают.
    assert client.post("/api/increment").json() == {"count": 1}
    assert client.post("/api/pause", json={"paused": False}).json() == {"paused": False}
    assert asyncio.run(hub.increment(2, speech=True)) == 3


def test_pause_is_broadcast(client):
    with client.websocket_connect("ws://localhost/ws") as ws:
        greeting = skip_greeting(ws)
        assert greeting[1] == {"type": "pause", "paused": False}
        client.post("/api/pause", json={"paused": True})
        assert ws.receive_json() == {"type": "pause", "paused": True}
        assert ws.receive_json()["running"] is False  # таймер «без мата» встал
        client.post("/api/pause", json={"paused": True})  # уже на паузе: рассылать нечего
        client.post("/api/pause", json={"paused": False})
        assert ws.receive_json() == {"type": "pause", "paused": False}
        assert ws.receive_json()["running"] is True


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
    with client.websocket_connect("ws://localhost/ws") as ws:
        assert ws.receive_json() == {"type": "state", "count": 1}


def test_ws_broadcasts_increment_and_reset(client):
    with client.websocket_connect("ws://localhost/ws") as first, client.websocket_connect("ws://localhost/ws") as second:
        for ws in (first, second):
            assert ws.receive_json()["type"] == "state"

        client.post("/api/increment")
        client.post("/api/reset")

        for ws in (first, second):
            assert receive_until(ws, "increment") == {"type": "increment", "count": 1, "delta": 1}
            assert receive_until(ws, "state") == {"type": "state", "count": 0}


def test_ws_disconnect_removes_client(client, hub):
    with client.websocket_connect("ws://localhost/ws") as ws:
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
    with client.websocket_connect("ws://localhost/ws") as ws:
        skip_greeting(ws)
        client.post("/api/sound/volume", json={"volume": 55})
        message = ws.receive_json()
        assert message["type"] == "sound" and message["volume"] == 55


# --- оформление оверлея ---


def test_ws_greeting_includes_sound_and_style(client):
    with client.websocket_connect("ws://localhost/ws") as ws:
        types_ = [ws.receive_json()["type"] for _ in GREETING]
    assert types_ == ["state", "pause", "timer", "sound", "style"]


def test_preset_is_saved_and_broadcast(client, settings_path):
    with client.websocket_connect("ws://localhost/ws") as ws:
        skip_greeting(ws)
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


def test_personal_ferret_preset_is_not_builtin():
    assert "ferret" not in PRESET_IDS


@pytest.mark.parametrize("preset", ["", "Neon", "../etc", "a" * 33])
def test_invalid_preset_rejected(client, preset):
    assert client.post("/api/overlay/preset", json={"preset": preset}).status_code == 400


def test_label_is_saved_and_broadcast(client, settings_path):
    with client.websocket_connect("ws://localhost/ws") as ws:
        skip_greeting(ws)
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
    from app import SUPPORT_LINKS, __version__

    assert client.get("/api/version").json() == {
        "version": __version__, "support": SUPPORT_LINKS, "order_email": server.ORDER_EMAIL,
    }


def test_support_links_are_valid(client):
    from app import SUPPORT_LINKS

    for link in SUPPORT_LINKS:
        assert link["name"] and link["url"].startswith("https://")
        # QR-код отдаётся вместе со страницей управления.
        res = client.get(f"/control/{link['qr']}")
        assert res.status_code == 200 and res.content.startswith(b"\x89PNG")


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
    monkeypatch.setattr(updater_module, "fetch_releases", lambda: [release])
    updater = updater_module.Updater(settings, install_dir=tmp_path, frozen=False)
    app = create_app(hub, recognizer, settings, sound, updater=updater)
    with TestClient(app, base_url="http://localhost") as client:
        yield client, updater


def test_update_state(client):
    state = client.get("/api/update").json()
    assert state["status"] == "idle" and state["auto"] is True and state["can_install"] is False


def test_update_check_is_broadcast(update_client):
    client, _ = update_client
    with client.websocket_connect("ws://localhost/ws") as ws:
        skip_greeting(ws)
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


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "https://evil.example"}, {"Origin": "http://localhost.evil.example:8765"}, {"Origin": "null"},
     {"Origin": "http://localhost:3000", "Host": "localhost:8765"},
     {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}],
)
def test_foreign_origin_cannot_change_state(client, headers):
    client.post("/api/increment")
    for url in ("/api/reset", "/api/increment", "/api/update/apply"):
        assert client.post(url, headers=headers).status_code == 403
    assert client.get("/api/state", headers=headers).json() == {"count": 1}


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765"},
     {"Origin": "http://localhost:8766", "Host": "localhost:8766"},
     {"Origin": "http://[::1]:8765", "Host": "[::1]:8765"},
     {"Sec-Fetch-Site": "same-origin"}, {}],
)
def test_own_pages_can_change_state(client, headers):
    assert client.post("/api/increment", headers=headers).status_code == 200
    assert client.get("/api/state").json() == {"count": 1}


# --- списки слов ---


@pytest.fixture
def word_lists(settings, tmp_path, monkeypatch):
    from app import profanity
    from app.wordlists import WordLists

    monkeypatch.setattr(profanity, "_roots", ())
    monkeypatch.setattr(profanity, "_source", None)
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "swears.txt").write_text("# Название: Маты (18+)\nбля\n", encoding="utf-8")
    (bundled / "parasites.txt").write_text("# Название: Слова-паразиты\nкороче\nтипа\n", encoding="utf-8")
    lists = WordLists(settings, tmp_path / "wordlists", bundled)
    lists.prepare()
    return lists


@pytest.fixture
def words_client(hub, recognizer, settings, sound, fake_sd, word_lists):
    app = create_app(hub, recognizer, settings, sound, word_lists=word_lists)
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def test_words_state(words_client):
    assert words_client.get("/api/words").json() == {
        "lists": [
            {"id": "parasites.txt", "name": "Слова-паразиты", "words": 2},
            {"id": "swears.txt", "name": "Маты (18+)", "words": 1},
        ],
        "active": "swears.txt",
    }


def test_select_word_list(words_client, settings_path):
    from app.profanity import count_profanity

    r = words_client.post("/api/words/active", json={"id": "parasites.txt"})
    assert r.status_code == 200
    assert r.json()["active"] == "parasites.txt"
    assert Settings(settings_path).get("word_list") == "parasites.txt"
    assert count_profanity("короче бля") == 1


@pytest.mark.parametrize("bad", ["нет.txt", "../settings.json"])
def test_select_unknown_word_list(words_client, bad):
    assert words_client.post("/api/words/active", json={"id": bad}).status_code == 404
    assert words_client.get("/api/words").json()["active"] == "swears.txt"


def test_open_word_list_and_folder(words_client, word_lists, monkeypatch):
    opened = []
    monkeypatch.setattr("os.startfile", opened.append, raising=False)
    assert words_client.post("/api/words/open", json={"id": "swears.txt"}).status_code == 200
    assert words_client.post("/api/words/open", json={}).status_code == 200
    assert opened == [word_lists.directory / "swears.txt", word_lists.directory]


def test_open_unknown_word_list(words_client, monkeypatch):
    opened = []
    monkeypatch.setattr("os.startfile", opened.append, raising=False)
    assert words_client.post("/api/words/open", json={"id": "../counter.json"}).status_code == 404
    assert opened == []


def test_open_word_list_error(words_client, monkeypatch):
    def fail(path):
        raise OSError("нет редактора")

    monkeypatch.setattr("os.startfile", fail, raising=False)
    assert words_client.post("/api/words/open", json={}).status_code == 500


def test_words_api_absent_without_word_lists(client):
    assert client.get("/api/words").status_code == 404


def test_foreign_origin_cannot_switch_word_list(words_client):
    r = words_client.post("/api/words/active", json={"id": "parasites.txt"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert words_client.get("/api/words").json()["active"] == "swears.txt"


@pytest.mark.parametrize("url", ["/control/", "/control/control.js", "/overlay/", "/overlay/presets.js"])
def test_pages_revalidated_not_cached(client, url):
    # После обновления программы браузер не должен брать старые скрипты из кеша.
    r = client.get(url)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert client.get(url, headers={"If-None-Match": r.headers["etag"]}).status_code == 304


# --- обязательное обновление ---


@pytest.fixture
def locked_client(hub, recognizer, settings, sound, fake_sd, tmp_path):
    from app import updater as updater_module

    updater = updater_module.Updater(settings, install_dir=tmp_path, frozen=True, current="0.2.0")
    updater.info = {"latest": "9.0.0", "url": "https://x/z.zip", "size": 1, "notes": "", "html_url": "", "force": True}
    updater.status = "available"
    app = create_app(hub, recognizer, settings, sound, updater=updater)
    with TestClient(app, base_url="http://localhost") as client:
        yield client, updater


def test_forced_update_blocks_counting_and_changes(locked_client, hub):
    client, _ = locked_client
    assert client.get("/api/update").json()["locked"] is True
    before = hub.counter.value
    resp = client.post("/api/increment")
    assert resp.status_code == 423 and "обязательное" in resp.json()["detail"]
    assert client.post("/api/reset").status_code == 423
    assert client.post("/api/overlay/preset", json={"preset": "neon"}).status_code == 423
    assert client.portal.call(hub.increment, 3) == before  # распознанные слова тоже не считаются
    assert hub.counter.value == before
    # Читать можно, оверлей работает.
    assert client.get("/api/state").status_code == 200
    assert client.get("/overlay/").status_code == 200


def test_forced_update_leaves_update_api_open(locked_client, monkeypatch):
    from app import updater as updater_module

    client, _ = locked_client
    assert client.post("/api/update/auto", json={"enabled": False}).status_code == 200
    assert client.delete("/api/update/download").status_code == 404
    # Обязательный релиз сняли (или пометку убрали) — проверка снимает блокировку.
    monkeypatch.setattr(updater_module, "fetch_releases", lambda: [])
    assert client.post("/api/update/check").json()["locked"] is False
    assert client.post("/api/increment").status_code == 200


def test_unlocked_after_forced_info_cleared(locked_client, hub):
    client, updater = locked_client
    updater.info = None
    assert client.post("/api/increment").status_code == 200


# --- предпросмотр оверлея ---


def test_open_overlay_in_browser(client, monkeypatch):
    from app import server

    opened = []
    monkeypatch.setattr(server.webbrowser, "open", opened.append)
    r = client.post("/api/overlay/open")
    assert r.status_code == 200
    assert opened == ["http://localhost/overlay/"] and r.json() == {"url": opened[0]}


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8765", "localhost.evil.example", ""])
def test_foreign_host_is_rejected(client, host):
    """DNS rebinding: чужой сайт указывает свой домен на 127.0.0.1, но Host у запроса — его."""
    for method, url in (("get", "/api/state"), ("post", "/api/increment"), ("get", "/control/")):
        res = client.request(method, url, headers={"Host": host})
        assert res.status_code == 400
    assert client.get("/api/state").json() == {"count": 0}


@pytest.mark.parametrize("host", ["localhost:8765", "127.0.0.1:8765", "[::1]:8765", "LOCALHOST"])
def test_local_host_is_allowed(client, host):
    assert client.get("/api/state", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "https://evil.example"}, {"Origin": "null"}, {"Host": "evil.example"}],
)
def test_ws_rejects_foreign_pages(client, headers):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect("ws://localhost/ws", headers=headers) as ws:
        ws.receive_json()
    assert e.value.code == 1008


@pytest.mark.parametrize("headers", [{}, {"Origin": "http://localhost:8765"}, {"Origin": "http://127.0.0.1:8765"}])
def test_ws_accepts_own_pages_and_obs(client, headers):
    with client.websocket_connect("ws://localhost/ws", headers=headers) as ws:
        assert ws.receive_json()["type"] == "state"


def test_order_hidden_without_email(client, monkeypatch):
    monkeypatch.setattr(server, "ORDER_EMAIL", "")
    opened = []
    monkeypatch.setattr(server.webbrowser, "open", opened.append)
    res = client.post("/api/order", json={"email": "me@example.com", "description": "Красный огонь"})
    assert res.status_code == 404 and opened == []


@pytest.fixture
def order(monkeypatch):
    monkeypatch.setattr(server, "ORDER_EMAIL", "author@example.com")
    monkeypatch.setattr(server.mail, "has_mail_app", lambda: True)
    opened = []
    monkeypatch.setattr(server.webbrowser, "open", lambda url: opened.append(url) or True)
    return opened


def test_order_opens_mail_app(client, order):
    from urllib.parse import parse_qs, urlsplit

    res = client.post("/api/order", json={"email": " me@example.com ", "description": "Хорёк & огонь?\nИ звук"})
    assert res.status_code == 200
    answer = res.json()
    assert answer["opened"] is True and answer["webmail"] is None
    assert answer["email"] == "author@example.com" and answer["subject"] == server.ORDER_SUBJECT
    parts = urlsplit(order[0])
    assert parts.scheme == "mailto" and parts.path == "author@example.com"
    query = parse_qs(parts.query)
    assert query["subject"] == [server.ORDER_SUBJECT]
    body = query["body"][0]
    assert body == answer["body"]
    assert "Почта для связи: me@example.com" in body
    assert "Хорёк & огонь?\nИ звук" in body
    assert server.__version__ in body


def test_order_without_mail_app_offers_webmail(client, order, monkeypatch):
    monkeypatch.setattr(server.mail, "has_mail_app", lambda: False)
    res = client.post("/api/order", json={"email": "me@gmail.com", "description": "Огненные цифры"})
    answer = res.json()
    assert answer["opened"] is False and order == []
    assert answer["webmail"]["name"] == "Gmail" and answer["webmail"]["filled"] is True
    assert answer["webmail"]["url"].startswith("https://mail.google.com/")


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "не почта", "description": "Красный огонь"},
        {"email": "a@b", "description": "Красный огонь"},
        {"email": "me@example.com", "description": "   "},
        {"email": "me@example.com", "description": "x" * (server.ORDER_DESCRIPTION_MAX + 1)},
        {"email": ("x" * 250) + "@example.com", "description": "Красный огонь"},
    ],
)
def test_order_validates_fields(client, order, payload):
    assert client.post("/api/order", json=payload).status_code == 400
    assert order == []


def test_order_needs_fields(client, order):
    assert client.post("/api/order", json={"email": "me@example.com"}).status_code == 422


# --- автозапуск ---


def test_autostart_defaults(client):
    data = client.get("/api/autostart").json()
    assert (data["windows"], data["obs"], data["stream"], data["obs_port"]) == (False, "off", "off", 4455)


def test_autostart_saves_settings_and_registry(client, settings_path, run_key):
    resp = client.post(
        "/api/autostart",
        json={"windows": False, "obs": "launch", "stream": "notify", "obs_port": 4456, "obs_password": "secret"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["obs"] == "launch" and data["stream"] == "notify" and data["obs_port"] == 4456
    assert data["has_password"] and "secret" not in resp.text
    assert run_key.value.endswith("--watch")
    saved = Settings(settings_path)
    assert saved.get("obs_ws_password") == "secret"

    # Без пароля в запросе сохранённый остаётся.
    client.post("/api/autostart", json={"windows": True, "obs": "off", "stream": "off", "obs_port": 4456})
    assert Settings(settings_path).get("obs_ws_password") == "secret"
    assert run_key.value.endswith("--autostart")


@pytest.mark.parametrize(
    "body",
    [
        {"windows": False, "obs": "maybe", "stream": "off", "obs_port": 4455},
        {"windows": False, "obs": "off", "stream": "off", "obs_port": 70000},
    ],
)
def test_autostart_rejects_bad_values(client, body, run_key):
    assert client.post("/api/autostart", json=body).status_code == 400
    assert run_key.value is None


def test_autostart_registry_error_restores_settings(client, settings, run_key):
    run_key.fail = PermissionError("Отказано в доступе")
    resp = client.post("/api/autostart", json={"windows": True, "obs": "off", "stream": "off", "obs_port": 4455})
    assert resp.status_code == 500
    assert "реестр" in resp.json()["detail"]
    assert client.get("/api/autostart").json()["windows"] is False


def test_obs_check_uses_saved_password(client, settings, monkeypatch):
    calls = []

    def fake_check(port, password):
        calls.append((port, password))
        return True

    monkeypatch.setattr(server.obs, "check", fake_check)
    settings.set("obs_ws_password", "saved")
    assert client.post("/api/autostart/obs-check", json={"obs_port": 4455}).json() == {"streaming": True}
    client.post("/api/autostart/obs-check", json={"obs_port": 4460, "obs_password": "typed"})
    assert calls == [(4455, "saved"), (4460, "typed")]


def test_obs_check_error(client, monkeypatch):
    def fake_check(port, password):
        raise server.obs.ObsError("OBS не отвечает")

    monkeypatch.setattr(server.obs, "check", fake_check)
    resp = client.post("/api/autostart/obs-check", json={"obs_port": 4455})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "OBS не отвечает"


# --- таймер «без мата» ---

def test_api_timer(client):
    state = client.get("/api/timer").json()
    assert set(state) == {"elapsed", "record", "running"}
    assert state["running"] is True


def test_timer_broadcast_after_increment_and_reset(client):
    with client.websocket_connect("ws://localhost/ws") as ws:
        greeting = skip_greeting(ws)
        assert greeting[2]["type"] == "timer"
        client.post("/api/increment")
        assert ws.receive_json()["type"] == "increment"
        message = ws.receive_json()
        assert (message["type"], message["elapsed"], message["running"]) == ("timer", 0.0, True)
        client.post("/api/reset")
        assert ws.receive_json()["type"] == "state"
        assert ws.receive_json() == {"type": "timer", "elapsed": 0.0, "record": 0.0, "running": True}
