"""FastAPI-приложение: API, WebSocket для оверлеев и статика."""

import asyncio
import logging
import re
import threading
from contextlib import asynccontextmanager

from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .counter import Counter
from .paths import CONTROL_DIR, OVERLAY_DIR
from .settings import Settings
from .sound import MAX_SOUND_BYTES, Sound
from .stt import CATALOG, VoskRecognizer, audio_devices, find_model

log = logging.getLogger(__name__)


class Hub:
    """Счётчик плюс список подключённых WebSocket-клиентов."""

    def __init__(self, counter: Counter):
        self.counter = counter
        self.clients: set[WebSocket] = set()
        # Общий замок: изменение счёта и рассылка идут строго по очереди,
        # чтобы клиенты получали события в правильном порядке.
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, greeting: list[dict] = ()) -> None:
        """Подключает клиента и отправляет ему счёт и сообщения greeting."""
        async with self._lock:
            await ws.send_json({"type": "state", "count": self.counter.value})
            for message in greeting:
                await ws.send_json(message)
            self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def increment(self, delta: int = 1) -> int:
        async with self._lock:
            count = await self.counter.add(delta)
            await self._broadcast({"type": "increment", "count": count, "delta": delta})
            return count

    async def reset(self) -> int:
        async with self._lock:
            count = await self.counter.reset()
            await self._broadcast({"type": "state", "count": count})
            return count

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            await self._broadcast(message)

    async def _broadcast(self, message: dict) -> None:
        clients = list(self.clients)
        results = await asyncio.gather(
            *(ws.send_json(message) for ws in clients), return_exceptions=True
        )
        # Клиенты, которым не удалось отправить, считаются отключёнными.
        for ws, result in zip(clients, results):
            if isinstance(result, Exception):
                self.clients.discard(ws)


class ModelChoice(BaseModel):
    model: str


class DeviceChoice(BaseModel):
    device: str | None  # полное имя микрофона; None — системный по умолчанию


class VolumeChoice(BaseModel):
    volume: int


class SoundChoice(BaseModel):
    id: str | None  # звук из библиотеки; None — стандартный


class MonitorChoice(BaseModel):
    enabled: bool


class PresetChoice(BaseModel):
    preset: str


DEFAULT_PRESET = "classic"
# Список пресетов знает только оверлей (overlay/presets.js); сервер проверяет форму id.
PRESET_ID = re.compile(r"[a-z0-9-]{1,32}")


def create_app(
    hub: Hub, recognizer: VoskRecognizer, settings: Settings, sound: Sound
) -> FastAPI:
    switch_lock = asyncio.Lock()

    def sound_message() -> dict:
        return {"type": "sound", **sound.state()}

    def style_message() -> dict:
        return {"type": "style", "preset": settings.get("overlay_preset", DEFAULT_PRESET)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await recognizer.start()
        try:
            yield
        finally:
            await recognizer.stop()

    app = FastAPI(title="Счётчик матов", version=__version__, lifespan=lifespan)

    @app.get("/")
    async def root():
        return RedirectResponse("/control/")

    @app.get("/api/state")
    async def get_state():
        return {"count": hub.counter.value}

    @app.get("/api/version")
    async def get_version():
        return {"version": __version__}

    @app.post("/api/increment")
    async def post_increment():
        return {"count": await hub.increment(1)}

    @app.post("/api/reset")
    async def post_reset():
        return {"count": await hub.reset()}

    @app.get("/api/speech")
    async def get_speech():
        return {
            "models": [m.to_dict() for m in CATALOG],
            "model": recognizer.model_path.name,
            "status": recognizer.status,
            "progress": recognizer.load_progress,
            "mic": recognizer.mic_name,
            "mic_error": recognizer.mic_error,
            "mic_pending": recognizer.mic_pending,
            "monitor": recognizer.monitor,
            "monitor_error": recognizer.monitor_error,
        }

    @app.post("/api/speech/model")
    async def post_speech_model(choice: ModelChoice):
        model = find_model(choice.model)
        if model is None:
            raise HTTPException(404, f"Неизвестная модель {choice.model}")
        if not model.installed:
            raise HTTPException(409, f"Модель {model.title} не скачана: нет папки {model.path}")
        async with switch_lock:
            if model.path != recognizer.model_path or recognizer.status == "error":
                log.info("Переключение модели: %s", model.id)
                await recognizer.set_model(model.path)
                settings.set("model", model.id)
        return await get_speech()

    devices_lock = threading.Lock()  # PortAudio нельзя перезапускать из двух потоков сразу

    def device_list() -> dict:
        with devices_lock:
            audio_devices.refresh()  # микрофон могли подключить после запуска
            return {
                "devices": audio_devices.list_inputs(),
                "default": audio_devices.default_input_name(),
                "selected": settings.get("device"),
            }

    @app.get("/api/devices")
    async def get_devices():
        return await asyncio.to_thread(device_list)

    @app.post("/api/speech/device")
    async def post_speech_device(choice: DeviceChoice):
        if choice.device is not None:
            devices = await asyncio.to_thread(device_list)
            if choice.device not in devices["devices"]:
                raise HTTPException(404, f"Микрофон «{choice.device}» не найден")
        log.info("Переключение микрофона: %s", choice.device or "по умолчанию")
        settings.set("device", choice.device)
        recognizer.set_device(choice.device)
        return await get_speech()

    @app.get("/api/sound")
    async def get_sound():
        return sound.state()

    @app.get("/api/sound/file/{sound_id}")
    async def get_sound_file(sound_id: str):
        path = sound.path(sound_id)
        if path is None:
            raise HTTPException(404, "Такого звука нет")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.put("/api/sound/file")
    async def put_sound_file(request: Request):
        """Добавляет звук в библиотеку и делает его активным."""
        # Файл приходит телом запроса как есть, а имя — в заголовке: так не нужна
        # отдельная библиотека для multipart/form-data.
        if int(request.headers.get("content-length") or 0) > MAX_SOUND_BYTES:
            raise HTTPException(413, f"Файл больше {MAX_SOUND_BYTES // (1024 * 1024)} МБ")
        data = await request.body()
        name = unquote(request.headers.get("x-filename", ""))
        try:
            sound.add(data, request.headers.get("content-type", ""), name)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        await hub.broadcast(sound_message())
        return sound.state()

    @app.delete("/api/sound/file/{sound_id}")
    async def delete_sound_file(sound_id: str):
        try:
            sound.delete(sound_id)
        except KeyError:
            raise HTTPException(404, "Такого звука нет") from None
        await hub.broadcast(sound_message())
        return sound.state()

    @app.post("/api/sound/active")
    async def post_sound_active(choice: SoundChoice):
        try:
            sound.select(choice.id)
        except KeyError:
            raise HTTPException(404, "Такого звука нет") from None
        await hub.broadcast(sound_message())
        return sound.state()

    @app.post("/api/sound/volume")
    async def post_sound_volume(choice: VolumeChoice):
        sound.set_volume(choice.volume)
        await hub.broadcast(sound_message())
        return sound.state()

    @app.post("/api/speech/monitor")
    async def post_speech_monitor(choice: MonitorChoice):
        recognizer.set_monitor(choice.enabled)
        return await get_speech()

    @app.get("/api/overlay")
    async def get_overlay():
        return {"preset": settings.get("overlay_preset", DEFAULT_PRESET)}

    @app.post("/api/overlay/preset")
    async def post_overlay_preset(choice: PresetChoice):
        if not PRESET_ID.fullmatch(choice.preset):
            raise HTTPException(400, "Неверный id пресета")
        settings.set("overlay_preset", choice.preset)
        await hub.broadcast(style_message())
        return await get_overlay()

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        try:
            await hub.connect(ws, [sound_message(), style_message()])
            log.info("Клиент подключён, всего: %d", len(hub.clients))
            # Клиенты ничего не присылают; читаем только чтобы заметить отключение.
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(ws)
            log.info("Клиент отключён, всего: %d", len(hub.clients))

    app.mount("/overlay", StaticFiles(directory=OVERLAY_DIR, html=True), name="overlay")
    app.mount("/control", StaticFiles(directory=CONTROL_DIR, html=True), name="control")
    return app
