"""FastAPI-приложение: API, WebSocket для оверлеев и статика."""

import asyncio
import json
import logging
import os
import re
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager

from urllib.parse import unquote, urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import SUPPORT_LINKS, __version__
from .counter import Counter
from .custom_presets import MAX_PACK_BYTES, CustomPresets
from .paths import CONTROL_DIR, OVERLAY_DIR
from .settings import Settings
from .sound import MAX_SOUND_BYTES, Sound
from .stt import CATALOG, ModelDownloader, ModelInfo, MicRecognizer, audio_devices, find_model
from .updater import Updater
from .wordlists import WordLists

log = logging.getLogger(__name__)


class Hub:
    """Счётчик плюс список подключённых WebSocket-клиентов."""

    def __init__(self, counter: Counter):
        self.counter = counter
        self.clients: set[WebSocket] = set()
        # Общий замок: изменение счёта и рассылка идут строго по очереди,
        # чтобы клиенты получали события в правильном порядке.
        self._lock = asyncio.Lock()
        # Пока возвращает True (обязательное обновление не установлено), счёт не растёт.
        self.locked: Callable[[], bool] = lambda: False

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
            if self.locked():
                return self.counter.value
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


class AutoUpdateChoice(BaseModel):
    enabled: bool


class PresetChoice(BaseModel):
    preset: str


class LabelChoice(BaseModel):
    text: str
    position: str


class PageFiles(StaticFiles):
    """Страницы и скрипты: браузер сверяется с сервером перед каждым использованием.

    Без этого после обновления программы WebView2 и OBS могут взять из кеша старый
    скрипт к новой странице. Сверка по ETag дешёвая: файлы отдаются с localhost.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


class WordListChoice(BaseModel):
    id: str


class WordListOpen(BaseModel):
    id: str | None = None  # файл списка; None — папка со списками


DEFAULT_PRESET = "classic"
# Список пресетов знает только оверлей (overlay/presets.js); сервер проверяет форму id.
PRESET_ID = re.compile(r"[a-z0-9-]{1,32}")
# Подпись рядом с числом («Маты:»): где она стоит относительно числа.
LABEL_POSITIONS = ("left", "right", "top", "bottom")
DEFAULT_LABEL_POSITION = "left"
LABEL_MAX_LENGTH = 40
# Изменять состояние можно только со своих страниц: иначе любой открытый сайт
# простым POST на localhost сбросит счёт или запустит обновление (CSRF).
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def foreign_origin(request: Request) -> bool:
    """Запрос меняет состояние и пришёл не со страницы этого же сервера."""
    if request.method in SAFE_METHODS:
        return False
    origin = request.headers.get("origin")
    if origin is None:
        # Без Origin: браузер всё равно помечает чужие запросы; curl и тесты — без метки.
        return request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none")
    # Тот же адрес до порта: другой локальный сервер (localhost:3000) — тоже чужой.
    parts = urlsplit(origin)
    return parts.hostname not in LOCAL_HOSTS or parts.netloc != request.headers.get("host")

LOCKED_MESSAGE = "Установите обязательное обновление, чтобы продолжить"


def locked_out(request: Request) -> bool:
    """Запрос меняет состояние, а программа ждёт обязательного обновления.

    Остаются доступны чтение и /api/update/* — чтобы скачать и поставить обновление.
    """
    path = request.url.path
    if request.method in SAFE_METHODS or not path.startswith("/api/"):
        return False
    return not (path == "/api/update" or path.startswith("/api/update/"))


def create_app(
    hub: Hub,
    recognizer: MicRecognizer,
    settings: Settings,
    sound: Sound,
    updater: Updater | None = None,
    check_updates: bool = False,
    word_lists: WordLists | None = None,
    custom_presets: CustomPresets | None = None,
) -> FastAPI:
    switch_lock = asyncio.Lock()
    # Модель, которую выбрали последней: если она ещё скачивается, то включится
    # после скачивания. Выбрали другую — скачанная просто останется на диске.
    wanted: dict[str, str | None] = {"model": None}

    async def switch_model(model: ModelInfo) -> None:
        async with switch_lock:
            if model.path != recognizer.model_path or recognizer.status in ("error", "no_model"):
                log.info("Переключение модели: %s", model.id)
                await recognizer.set_model(model.path)
                settings.set("model", model.id)

    async def on_downloaded(model: ModelInfo) -> None:
        if wanted["model"] == model.id:
            await switch_model(model)

    downloader = ModelDownloader(on_downloaded)

    # Без updater (тесты, разработка) установка недоступна, а сеть не трогаем.
    updater = updater or Updater(settings, frozen=False)

    async def on_update_change(state: dict) -> None:
        await hub.broadcast({"type": "update", **state})

    updater.on_change = on_update_change
    hub.locked = lambda: updater.locked

    def sound_message() -> dict:
        return {"type": "sound", **sound.state()}

    def overlay_state() -> dict:
        return {
            "preset": settings.get("overlay_preset", DEFAULT_PRESET),
            "label": settings.get("overlay_label", ""),
            "label_position": settings.get("overlay_label_position", DEFAULT_LABEL_POSITION),
        }

    def style_message() -> dict:
        return {"type": "style", **overlay_state()}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await recognizer.start()
        updater.loop = asyncio.get_running_loop()
        check_task = asyncio.create_task(updater.auto_check()) if check_updates else None
        try:
            yield
        finally:
            if check_task is not None:
                check_task.cancel()
            await updater.stop()
            await downloader.stop()
            await recognizer.stop()

    app = FastAPI(title="Счётчик матов", version=__version__, lifespan=lifespan)

    @app.middleware("http")
    async def reject_foreign_origin(request: Request, call_next):
        if foreign_origin(request):
            log.warning("Отклонён запрос %s %s: %s", request.method, request.url.path, request.headers.get("origin", "чужого сайта"))
            return JSONResponse({"detail": "Запрос с чужого сайта отклонён"}, status_code=403)
        if updater.locked and locked_out(request):
            return JSONResponse({"detail": LOCKED_MESSAGE}, status_code=423)
        return await call_next(request)

    @app.get("/")
    async def root():
        return RedirectResponse("/control/")

    @app.get("/api/state")
    async def get_state():
        return {"count": hub.counter.value}

    @app.get("/api/version")
    async def get_version():
        return {"version": __version__, "support": SUPPORT_LINKS}

    @app.get("/api/update")
    async def get_update():
        return updater.state()

    @app.post("/api/update/check")
    async def post_update_check():
        await updater.check()
        return updater.state()

    @app.post("/api/update/auto")
    async def post_update_auto(choice: AutoUpdateChoice):
        updater.set_auto(choice.enabled)
        return updater.state()

    @app.post("/api/update/download")
    async def post_update_download():
        try:
            updater.start_download()
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return updater.state()

    @app.delete("/api/update/download")
    async def delete_update_download():
        if not updater.cancel():
            raise HTTPException(404, "Обновление не скачивается")
        return updater.state()

    @app.post("/api/update/apply")
    async def post_update_apply():
        try:
            updater.apply()
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        # Выходим чуть позже, чтобы ответ успел уйти странице.
        asyncio.get_running_loop().call_later(0.5, updater.exit)
        return updater.state()

    @app.post("/api/increment")
    async def post_increment():
        return {"count": await hub.increment(1)}

    @app.post("/api/reset")
    async def post_reset():
        return {"count": await hub.reset()}

    @app.get("/api/speech")
    async def get_speech():
        return {
            "models": [m.to_dict() | {"download": downloader.state(m.id)} for m in CATALOG],
            "model": recognizer.model_path.name,
            "status": recognizer.status,
            "progress": recognizer.load_progress,
            "mic": recognizer.mic_name,
            "mic_error": recognizer.mic_error,
            "mic_pending": recognizer.mic_pending,
            "monitor": recognizer.monitor,
            "monitor_error": recognizer.monitor_error,
            # Модель, которая включится сама, когда скачается.
            "wanted": wanted["model"] if downloader.state(wanted["model"] or "") else None,
        }

    @app.post("/api/speech/model")
    async def post_speech_model(choice: ModelChoice):
        model = find_model(choice.model)
        if model is None:
            raise HTTPException(404, f"Неизвестная модель {choice.model}")
        wanted["model"] = model.id
        if model.installed:
            await switch_model(model)
        else:
            downloader.start(model)  # включится в on_downloaded
        return await get_speech()

    @app.delete("/api/speech/download/{model_id}")
    async def delete_speech_download(model_id: str):
        if not downloader.cancel(model_id):
            raise HTTPException(404, "Эта модель не скачивается")
        if wanted["model"] == model_id:
            wanted["model"] = None
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
        return overlay_state()

    @app.post("/api/overlay/preset")
    async def post_overlay_preset(choice: PresetChoice):
        if not PRESET_ID.fullmatch(choice.preset):
            raise HTTPException(400, "Неверный id пресета")
        settings.set("overlay_preset", choice.preset)
        await hub.broadcast(style_message())
        return await get_overlay()

    @app.post("/api/overlay/label")
    async def post_overlay_label(choice: LabelChoice):
        # Подпись — одна строка: переводы строк и табуляции превращаем в пробелы.
        text = " ".join(choice.text.split())
        if len(text) > LABEL_MAX_LENGTH:
            raise HTTPException(400, f"Подпись длиннее {LABEL_MAX_LENGTH} символов")
        if choice.position not in LABEL_POSITIONS:
            raise HTTPException(400, "Неверное положение подписи")
        settings.set("overlay_label", text)
        settings.set("overlay_label_position", choice.position)
        await hub.broadcast(style_message())
        return await get_overlay()

    @app.get("/overlay/custom-presets.js")
    async def get_custom_presets_js():
        """Личные оформления для оверлея: скрипт подключается сразу после presets.js."""
        presets = custom_presets.list() if custom_presets is not None else []
        return Response(
            f"window.registerCustomPresets({json.dumps(presets, ensure_ascii=False)});\n",
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    if custom_presets is not None:

        async def presets_changed() -> None:
            # Оверлеи перезагружаются и подхватывают наборы; страница управления обновляет выбор.
            await hub.broadcast({"type": "presets"})
            builtin = custom_presets.builtin_ids
            current = settings.get("overlay_preset", DEFAULT_PRESET)
            if current not in builtin and current not in custom_presets.ids():
                settings.set("overlay_preset", DEFAULT_PRESET)  # удалили выбранное оформление
            await hub.broadcast(style_message())

        @app.get("/api/presets/custom")
        async def get_custom_presets():
            return custom_presets.list()

        @app.put("/api/presets/custom")
        async def put_custom_preset(request: Request):
            """Ставит личное оформление из zip-архива (тело запроса как есть, как у звука)."""
            if int(request.headers.get("content-length") or 0) > MAX_PACK_BYTES:
                raise HTTPException(413, f"Архив больше {MAX_PACK_BYTES // (1024 * 1024)} МБ")
            data = await request.body()
            try:
                preset = await asyncio.to_thread(custom_presets.install, data)
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
            await presets_changed()
            return preset

        @app.delete("/api/presets/custom/{preset_id}")
        async def delete_custom_preset(preset_id: str):
            try:
                await asyncio.to_thread(custom_presets.remove, preset_id)
            except KeyError:
                raise HTTPException(404, "Такого оформления нет") from None
            await presets_changed()
            return custom_presets.list()

    if word_lists is not None:

        @app.get("/api/words")
        async def get_words():
            return word_lists.state()

        @app.post("/api/words/active")
        async def post_words_active(choice: WordListChoice):
            try:
                word_lists.select(choice.id)
            except KeyError:
                raise HTTPException(404, "Такого списка нет") from None
            return word_lists.state()

        @app.post("/api/words/open")
        async def post_words_open(choice: WordListOpen):
            """Открывает файл списка в редакторе или папку со списками в Проводнике."""
            try:
                path = word_lists.directory if choice.id is None else word_lists.path(choice.id)
            except KeyError:
                raise HTTPException(404, "Такого списка нет") from None
            if not hasattr(os, "startfile"):
                raise HTTPException(501, "Открыть файл можно только в Windows")
            try:
                await asyncio.to_thread(os.startfile, path)
            except OSError as e:
                raise HTTPException(500, f"Не удалось открыть: {e}") from None
            return word_lists.state()

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

    if custom_presets is not None:
        # Файлы наборов (style.css, картинки, звуки). Раньше /overlay, иначе его перехватит тот.
        # Папка нужна сразу: StaticFiles проверяет её при первом запросе.
        custom_presets.directory.mkdir(parents=True, exist_ok=True)
        app.mount(
            "/overlay/custom",
            PageFiles(directory=custom_presets.directory, check_dir=False),
            name="custom-presets",
        )
    app.mount("/overlay", PageFiles(directory=OVERLAY_DIR, html=True), name="overlay")
    app.mount("/control", PageFiles(directory=CONTROL_DIR, html=True), name="control")
    return app
