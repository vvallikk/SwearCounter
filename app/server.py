"""FastAPI-приложение: API, WebSocket для оверлеев и статика."""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from urllib.parse import unquote, urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ORDER_EMAIL, ORDER_SUBJECT, SUPPORT_LINKS, __version__, autostart, goals, hotkeys, i18n, mail, obs, preset_links
from .counter import Counter
from .custom_presets import MAX_PACK_BYTES, CustomPresets
from .extra_counters import CounterError, ExtraCounters
from .obs_link import ObsLink
from .paths import CONTROL_DIR, OVERLAY_DIR
from .settings import Settings
from .stats import Stats
from .sound import MAX_SOUND_BYTES, Sound
from .timer import NoSwearTimer
from .streaming import Streaming, make_router as streaming_router
from .stt import CATALOG, ModelDownloader, ModelInfo, MicRecognizer, audio_devices, find_model, remove_model
from .updater import Updater
from .wordlists import WordLists

log = logging.getLogger(__name__)


# Что получают клиенты /ws/events (Streamer.bot и т. п.): только изменения счёта и паузы,
# без уровня микрофона и таймера, которые идут несколько раз в секунду.
EVENT_TYPES = ("state", "increment", "pause")


class Hub:
    """Счётчик плюс список подключённых WebSocket-клиентов."""

    def __init__(self, counter: Counter):
        self.counter = counter
        self.clients: set[WebSocket] = set()
        self.event_clients: set[WebSocket] = set()  # подключены к /ws/events
        # Общий замок: изменение счёта и рассылка идут строго по очереди,
        # чтобы клиенты получали события в правильном порядке.
        self._lock = asyncio.Lock()
        # Пока возвращает True (обязательное обновление не установлено), счёт не растёт.
        self.locked: Callable[[], bool] = lambda: False
        # Пауза распознавания: сказанное не считается, кнопки и горячие клавиши работают.
        # Не сохраняется: после перезапуска программа снова слушает.
        self.paused = False
        self.timer = NoSwearTimer()
        # Особые числа и цель (app/goals.py): на них оверлей празднует.
        self.milestones: list[int] = []
        self.goal = 0
        # Статистика по сессиям (app/stats.py); в тестах — только в памяти.
        self.stats = Stats()
        # Вызываются после прибавки с (было, стало): например, смена сцены в OBS по порогу.
        self.count_listeners: list[Callable[[int, int], None]] = []
        # Дополнительные счётчики (app/extra_counters.py); в тестах — только в памяти.
        self.extra = ExtraCounters()

    async def connect(self, ws: WebSocket, greeting: list[dict] = (), events_only: bool = False) -> None:
        """Подключает клиента и отправляет ему счёт и сообщения greeting.

        events_only: клиенту дальше идут только сообщения EVENT_TYPES, приветствие — только счёт.
        """
        async with self._lock:
            await ws.send_json({"type": "state", "count": self.counter.value})
            if events_only:
                self.event_clients.add(ws)
                return
            await ws.send_json(self.pause_message())
            await ws.send_json(self.timer.message())
            await ws.send_json(self.goals_message())
            for message in greeting:
                await ws.send_json(message)
            self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)
        self.event_clients.discard(ws)

    async def increment(self, delta: int = 1, speech: bool = False, words: list[str] = ()) -> int:
        """speech: слова из распознавания; на паузе они не считаются. words — их корни для статистики."""
        async with self._lock:
            if self.locked() or (speech and self.paused):
                return self.counter.value
            before = self.counter.value
            count = await self.counter.add(delta)
            self.stats.add(delta, words)
            message = {"type": "increment", "count": count, "delta": delta}
            milestone = goals.reached(self.milestones, self.goal, before, count)
            if milestone is not None:
                message["milestone"] = milestone
            await self._broadcast(message)
            self.timer.hit()
            await self._broadcast(self.timer.message())
            for listener in self.count_listeners:
                listener(before, count)
            return count

    async def increment_extra(self, counter_id: str, delta: int = 1, speech: bool = False) -> int:
        """Прибавка дополнительному счётчику; KeyError, если его нет."""
        async with self._lock:
            if self.locked() or (speech and self.paused):
                return self.extra.get(counter_id)["count"]
            count = self.extra.add_count(counter_id, delta)
            await self._broadcast({"type": "extra_increment", "id": counter_id, "count": count, "delta": delta})
            return count

    def counters_message(self) -> dict:
        return {"type": "counters", "counters": self.extra.items()}

    async def reset(self) -> int:
        async with self._lock:
            count = await self.counter.reset()
            self.stats.new_session()
            await self._broadcast({"type": "state", "count": count})
            self.timer.reset()
            await self._broadcast(self.timer.message())
            return count

    def pause_message(self) -> dict:
        return {"type": "pause", "paused": self.paused}

    def goals_message(self) -> dict:
        return {"type": "goals", "milestones": self.milestones, "goal": self.goal}

    async def set_paused(self, paused: bool) -> bool:
        async with self._lock:
            if self.paused != paused:
                self.paused = paused
                log.info("Распознавание %s", "на паузе" if paused else "снова считает")
                if paused:
                    self.timer.pause()
                else:
                    self.timer.resume()
                await self._broadcast(self.pause_message())
                await self._broadcast(self.timer.message())
            return self.paused

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            await self._broadcast(message)

    async def _broadcast(self, message: dict) -> None:
        clients = list(self.clients)
        if message.get("type") in EVENT_TYPES:
            clients += self.event_clients
        results = await asyncio.gather(
            *(ws.send_json(message) for ws in clients), return_exceptions=True
        )
        # Клиенты, которым не удалось отправить, считаются отключёнными.
        for ws, result in zip(clients, results, strict=True):
            if isinstance(result, Exception):
                self.disconnect(ws)


class CounterCreate(BaseModel):
    name: str
    list: str


class CounterUpdate(BaseModel):
    name: str | None = None
    list: str | None = None
    preset: str | None = None
    label: str | None = None


class GoalsChoice(BaseModel):
    milestones: list[int]
    goal: int = 0


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


class PauseChoice(BaseModel):
    paused: bool


class LanguageChoice(BaseModel):
    language: str


class HotkeyChoice(BaseModel):
    action: str
    combo: str


class AutoUpdateChoice(BaseModel):
    enabled: bool


class AutostartChoice(BaseModel):
    windows: bool
    obs: str
    stream: str
    obs_port: int
    obs_password: str | None = None  # None — оставить сохранённый


class ObsCheck(BaseModel):
    obs_port: int
    obs_password: str | None = None  # None — сохранённый


class ObsOptions(BaseModel):
    reset_stream: bool = False
    reset_record: bool = False
    scene: str = ""
    scene_at: int = 0  # 0 — сцену не переключать


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


class PresetLink(BaseModel):
    url: str


class PresetOrder(BaseModel):
    email: str
    description: str


ORDER_EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# Длинное письмо в mailto: обрезают почтовые программы и сама Windows.
ORDER_DESCRIPTION_MAX = 1500


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


def foreign_host(host: str | None) -> bool:
    """Адрес в заголовке Host не наш: так выглядит DNS rebinding, когда чужой домен
    указывает на 127.0.0.1 и его страница читает ответы программы как свои."""
    return urlsplit(f"//{host or ''}").hostname not in LOCAL_HOSTS


def foreign_ws_origin(origin: str | None) -> bool:
    """WebSocket браузер открывает с любого сайта: пускаем только свои страницы и OBS."""
    return origin is not None and urlsplit(origin).hostname not in LOCAL_HOSTS


def order_body(email: str, description: str) -> str:
    """Текст письма автору с заказом оформления."""
    return (
        f"Почта для связи: {email}\n\n"
        f"Каким должно быть оформление:\n{description}\n\n"
        f"Версия программы: {__version__}"
    )


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

MAX_SCENE_NAME = 256


def obs_options(settings: Settings) -> dict:
    """Что делать по событиям OBS (app/obs_link.py); испорченное значение — выключено."""
    saved = settings.get("obs_link")
    saved = saved if isinstance(saved, dict) else {}
    scene, scene_at = saved.get("scene"), saved.get("scene_at")
    return {
        "reset_stream": saved.get("reset_stream") is True,
        "reset_record": saved.get("reset_record") is True,
        "scene": scene if isinstance(scene, str) else "",
        "scene_at": scene_at if isinstance(scene_at, int) and 0 <= scene_at <= goals.MAX_VALUE else 0,
    }


def obs_link_needed(options: dict) -> bool:
    return options["reset_stream"] or options["reset_record"] or bool(options["scene"] and options["scene_at"])


AUTOSTART_KEYS = ("autostart_windows", "autostart_obs", "autostart_stream", "obs_ws_port", "obs_ws_password")

LOCKED_MESSAGE = "Установите обязательное обновление, чтобы продолжить"


def locked_out(request: Request) -> bool:
    """Запрос меняет состояние, а программа ждёт обязательного обновления.

    Остаются доступны чтение, /api/update/* — чтобы скачать и поставить обновление —
    и язык интерфейса, чтобы прочитать, что случилось.
    """
    path = request.url.path
    if request.method in SAFE_METHODS or not path.startswith("/api/") or path == "/api/ui-language":
        return False
    return not (path == "/api/update" or path.startswith("/api/update/"))


def downloads_dir() -> Path:
    """Папка «Загрузки», куда экспортируются оформления; без неё — домашняя папка."""
    folder = Path.home() / "Downloads"
    return folder if folder.is_dir() else Path.home()


def reveal(path: Path) -> None:
    """Показывает файл в Проводнике (выделенным), чтобы его сразу можно было отправить."""
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", f"/select,{path}"])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])  # выделить файл xdg-open не умеет
    except OSError as e:
        log.warning("Не удалось показать файл %s: %s", path, e)


def open_path(path: Path) -> None:
    """Открывает файл или папку программой по умолчанию."""
    if hasattr(os, "startfile"):
        os.startfile(path)  # noqa: S606 путь из своей папки списков
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def create_app(
    hub: Hub,
    recognizer: MicRecognizer,
    settings: Settings,
    sound: Sound,
    updater: Updater | None = None,
    check_updates: bool = False,
    word_lists: WordLists | None = None,
    custom_presets: CustomPresets | None = None,
    hotkey_listener: hotkeys.Hotkeys | None = None,
    obs_link: ObsLink | None = None,
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
        # Без единой модели (первый запуск) включаем первую скачанную, даже если её не выбирали.
        if wanted["model"] == model.id or recognizer.status == "no_model":
            await switch_model(model)

    downloader = ModelDownloader(on_downloaded)

    # Без updater (тесты, разработка) установка недоступна, а сеть не трогаем.
    updater = updater or Updater(settings, frozen=False)

    async def on_update_change(state: dict) -> None:
        await hub.broadcast({"type": "update", **state})

    updater.on_change = on_update_change
    hub.locked = lambda: updater.locked

    # Испорченные настройки (правили руками) — особые числа по умолчанию и без цели.
    try:
        hub.milestones = goals.clean_milestones(settings.get("milestones", goals.DEFAULT_MILESTONES))
        hub.goal = goals.clean_goal(settings.get("goal", 0))
    except (goals.GoalsError, TypeError):
        hub.milestones, hub.goal = list(goals.DEFAULT_MILESTONES), 0

    # --- Связь с OBS: автосброс при начале трансляции или записи и смена сцены по порогу ---
    loop_holder: dict[str, asyncio.AbstractEventLoop] = {}
    background: set[asyncio.Task] = set()

    def from_link_thread(coro) -> None:
        """Запуск корутины в цикле сервера из потока связи с OBS."""
        loop = loop_holder.get("loop")
        if loop is None:
            coro.close()
            return
        asyncio.run_coroutine_threadsafe(coro, loop)

    def on_obs_output(output: str) -> None:
        if obs_options(settings)[f"reset_{output}"]:
            log.info("OBS: начало %s, счёт сброшен", "трансляции" if output == "stream" else "записи")
            from_link_thread(hub.reset())

    def on_obs_status(state: dict) -> None:
        from_link_thread(hub.broadcast({"type": "obs", **state}))

    obs_link = obs_link or ObsLink(on_obs_output, on_obs_status)

    def configure_obs_link() -> None:
        needed = obs_link_needed(obs_options(settings))
        obs_link.configure(needed, autostart.obs_port(settings), autostart.obs_password(settings))

    async def switch_scene(name: str) -> None:
        try:
            await asyncio.to_thread(obs_link.request, "SetCurrentProgramScene", {"sceneName": name})
            log.info("OBS: сцена переключена на %r", name)
        except obs.ObsError as e:
            log.warning("Не удалось переключить сцену OBS: %s", e)

    def on_count(before: int, count: int) -> None:
        options = obs_options(settings)
        if options["scene"] and 0 < options["scene_at"] and before < options["scene_at"] <= count:
            task = asyncio.create_task(switch_scene(options["scene"]))
            background.add(task)
            task.add_done_callback(background.discard)

    hub.count_listeners.append(on_count)
    streaming = Streaming(hub, settings)  # чат Twitch и YouTube: команды, объявления, маркеры
    streaming.attach()
    if word_lists is not None:
        hub.extra.list_path = word_lists.path

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

    def hotkey_combos() -> dict[str, str]:
        saved = settings.get("hotkeys")
        return hotkeys.normalize(saved if isinstance(saved, dict) else {})

    def hotkeys_state() -> dict:
        return {
            "available": hotkey_listener is not None and hotkey_listener.available,
            "hotkeys": hotkey_combos(),
            "failed": hotkey_listener.failed if hotkey_listener is not None else [],
        }

    async def on_hotkey(action: str) -> None:
        log.info("Горячая клавиша: %s", action)
        if action == "increment":
            await hub.increment(1)
        elif action == "reset":
            await hub.reset()
        elif action == "pause":
            await hub.set_paused(not hub.paused)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await recognizer.start()
        updater.loop = asyncio.get_running_loop()
        loop_holder["loop"] = updater.loop
        configure_obs_link()
        obs_link.start()
        streaming.start(updater.loop)
        check_task = asyncio.create_task(updater.auto_check()) if check_updates else None
        if hotkey_listener is not None:
            loop = asyncio.get_running_loop()
            hotkey_listener.on_press = lambda action: asyncio.run_coroutine_threadsafe(on_hotkey(action), loop)
            await asyncio.to_thread(hotkey_listener.start, hotkey_combos())
        try:
            yield
        finally:
            if hotkey_listener is not None:
                await asyncio.to_thread(hotkey_listener.stop)
            if check_task is not None:
                check_task.cancel()
            await asyncio.to_thread(obs_link.stop)
            await asyncio.to_thread(streaming.stop)
            loop_holder.pop("loop", None)
            await updater.stop()
            await downloader.stop()
            await recognizer.stop()

    app = FastAPI(title="Счётчик матов", version=__version__, lifespan=lifespan)
    app.state.hub = hub  # трей читает отсюда, стоит ли пауза
    app.state.streaming = streaming
    app.include_router(streaming_router(streaming))

    @app.middleware("http")
    async def reject_foreign_origin(request: Request, call_next):
        if foreign_host(request.headers.get("host")):
            log.warning("Отклонён запрос %s: чужой адрес %s", request.url.path, request.headers.get("host"))
            return JSONResponse({"detail": "Откройте программу по адресу localhost"}, status_code=400)
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

    @app.get("/api/count")
    async def get_count():
        """Счёт простым текстом: для команды !маты в Streamer.bot (Fetch URL) и подобных."""
        return PlainTextResponse(str(hub.counter.value))

    @app.get("/api/pause")
    async def get_pause():
        return {"paused": hub.paused}

    @app.post("/api/pause")
    async def post_pause(choice: PauseChoice):
        return {"paused": await hub.set_paused(choice.paused)}

    @app.get("/api/timer")
    async def get_timer():
        state = hub.timer.message()
        del state["type"]
        return state

    @app.get("/api/goals")
    async def get_goals():
        message = hub.goals_message()
        del message["type"]
        return message

    @app.post("/api/goals")
    async def post_goals(choice: GoalsChoice):
        try:
            milestones = goals.clean_milestones(choice.milestones)
            goal = goals.clean_goal(choice.goal)
        except goals.GoalsError as e:
            raise HTTPException(400, str(e)) from None
        settings.set("milestones", milestones)
        settings.set("goal", goal)
        hub.milestones, hub.goal = milestones, goal
        await hub.broadcast(hub.goals_message())
        return await get_goals()

    @app.get("/api/hotkeys")
    async def get_hotkeys():
        return hotkeys_state()

    @app.post("/api/hotkeys")
    async def post_hotkey(choice: HotkeyChoice):
        if choice.action not in hotkeys.ACTIONS:
            raise HTTPException(400, "Неизвестное действие")
        try:
            hotkeys.parse(choice.combo)
        except hotkeys.HotkeyError as e:
            raise HTTPException(400, str(e)) from None
        combos = hotkey_combos()
        if choice.combo and any(combo == choice.combo for action, combo in combos.items() if action != choice.action):
            raise HTTPException(400, "Это сочетание уже назначено другому действию")
        combos[choice.action] = choice.combo
        settings.set("hotkeys", combos)
        if hotkey_listener is not None:
            await asyncio.to_thread(hotkey_listener.apply, combos)
        return hotkeys_state()

    @app.get("/api/ui-language")
    async def get_ui_language():
        return {"language": i18n.language(settings)}

    @app.post("/api/ui-language")
    async def post_ui_language(choice: LanguageChoice):
        if choice.language not in i18n.LANGUAGES:
            raise HTTPException(400, "Неизвестный язык")
        settings.set(i18n.SETTING, choice.language)
        # Оконный режим подписывается, чтобы перевести трей и заголовок окна (desktop.py).
        on_change = getattr(app.state, "on_ui_language", None)
        if on_change is not None:
            await asyncio.to_thread(on_change)
        return {"language": choice.language}

    @app.get("/api/version")
    async def get_version():
        return {"version": __version__, "support": SUPPORT_LINKS, "order_email": ORDER_EMAIL}

    @app.post("/api/order")
    async def post_order(order: PresetOrder):
        """Письмо автору: почтовая программа или сайт почты; сама программа ничего не отправляет."""
        if not ORDER_EMAIL:
            raise HTTPException(404, "Заказ оформления недоступен")
        email, description = order.email.strip(), order.description.strip()
        if len(email) > 254 or not ORDER_EMAIL_PATTERN.fullmatch(email):
            raise HTTPException(400, "Проверьте почту для связи")
        if not description:
            raise HTTPException(400, "Опишите, каким должно быть оформление")
        if len(description) > ORDER_DESCRIPTION_MAX:
            raise HTTPException(400, f"Описание длиннее {ORDER_DESCRIPTION_MAX} символов: сократите его")
        body = order_body(email, description)
        # Windows «открывает» mailto: и без почтовой программы, поэтому сначала проверяем её.
        mail_app = await asyncio.to_thread(mail.has_mail_app)
        opened = mail_app and await asyncio.to_thread(webbrowser.open, mail.mailto(ORDER_EMAIL, ORDER_SUBJECT, body))
        return {
            "email": ORDER_EMAIL,
            "subject": ORDER_SUBJECT,
            "body": body,
            "opened": bool(opened),
            "webmail": mail.webmail(email, ORDER_EMAIL, ORDER_SUBJECT, body),
        }

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

    @app.get("/api/autostart")
    async def get_autostart():
        return autostart.state(settings)

    @app.post("/api/autostart")
    async def post_autostart(choice: AutostartChoice):
        if choice.obs not in autostart.TRIGGER_MODES or choice.stream not in autostart.TRIGGER_MODES:
            raise HTTPException(400, "Неверный режим автозапуска")
        if not 0 < choice.obs_port < 65536:
            raise HTTPException(400, "Порт — число от 1 до 65535")
        old = {key: settings.get(key) for key in AUTOSTART_KEYS}
        settings.set("autostart_windows", choice.windows)
        settings.set("autostart_obs", choice.obs)
        settings.set("autostart_stream", choice.stream)
        settings.set("obs_ws_port", choice.obs_port)
        if choice.obs_password is not None:
            settings.set("obs_ws_password", choice.obs_password)
        try:
            await asyncio.to_thread(autostart.sync, settings)
        except OSError as e:
            for key, value in old.items():
                settings.set(key, value)
            raise HTTPException(500, f"Не удалось записать автозапуск в реестр: {e}") from None
        configure_obs_link()  # порт и пароль общие со связью с OBS
        return autostart.state(settings)

    @app.post("/api/autostart/obs-check")
    async def post_obs_check(check: ObsCheck):
        password = autostart.obs_password(settings) if check.obs_password is None else check.obs_password
        try:
            streaming = await asyncio.to_thread(obs.check, check.obs_port, password)
        except obs.ObsError as e:
            raise HTTPException(400, str(e)) from None
        return {"streaming": streaming}

    def obs_state() -> dict:
        return obs_options(settings) | {"status": obs_link.state()}

    @app.get("/api/obs")
    async def get_obs():
        return obs_state()

    @app.post("/api/obs")
    async def post_obs(options: ObsOptions):
        if not 0 <= options.scene_at <= goals.MAX_VALUE:
            raise HTTPException(400, f"Порог — целое число от 0 до {goals.MAX_VALUE}")
        if len(options.scene) > MAX_SCENE_NAME:
            raise HTTPException(400, "Слишком длинное имя сцены")
        settings.set("obs_link", options.model_dump())
        configure_obs_link()
        return obs_state()

    @app.get("/api/obs/scenes")
    async def get_obs_scenes():
        """Сцены OBS для выбора: через постоянную связь, а без неё — разовым подключением."""
        try:
            if obs_link.connected:
                return {"scenes": obs.scene_names(await asyncio.to_thread(obs_link.request, "GetSceneList"))}
            port, password = autostart.obs_port(settings), autostart.obs_password(settings)
            return {"scenes": await asyncio.to_thread(obs.scenes, port, password)}
        except obs.ObsError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/overlay/open")
    async def open_overlay(request: Request):
        """Открывает оверлей в браузере по умолчанию: окно программы само вкладки не открывает."""
        url = f"{request.base_url}overlay/"
        await asyncio.to_thread(webbrowser.open, url)
        return {"url": url}

    @app.post("/api/increment")
    async def post_increment():
        return {"count": await hub.increment(1)}

    @app.post("/api/reset")
    async def post_reset():
        return {"count": await hub.reset()}

    # --- Дополнительные счётчики: свой список слов, счёт и оформление оверлея ---

    def extra_or_404(counter_id: str) -> dict:
        try:
            return hub.extra.get(counter_id)
        except KeyError:
            raise HTTPException(404, "Такого счётчика нет") from None

    async def counters_changed() -> dict:
        message = hub.counters_message()
        await hub.broadcast(message)
        return {"counters": message["counters"]}

    @app.get("/api/counters")
    async def get_counters():
        return {"counters": hub.extra.items()}

    @app.post("/api/counters")
    async def post_counter(body: CounterCreate):
        try:
            hub.extra.add(body.name, body.list)
        except CounterError as e:
            raise HTTPException(400, str(e)) from None
        return await counters_changed()

    @app.post("/api/counters/{counter_id}")
    async def update_counter(counter_id: str, body: CounterUpdate):
        extra_or_404(counter_id)
        if body.preset is not None and not PRESET_ID.fullmatch(body.preset):
            raise HTTPException(400, "Неверный id пресета")
        label = None if body.label is None else " ".join(body.label.split())
        if label is not None and len(label) > LABEL_MAX_LENGTH:
            raise HTTPException(400, f"Подпись длиннее {LABEL_MAX_LENGTH} символов")
        try:
            hub.extra.update(counter_id, name=body.name, list=body.list, preset=body.preset, label=label)
        except CounterError as e:
            raise HTTPException(400, str(e)) from None
        return await counters_changed()

    @app.delete("/api/counters/{counter_id}")
    async def delete_counter(counter_id: str):
        extra_or_404(counter_id)
        hub.extra.remove(counter_id)
        return await counters_changed()

    @app.post("/api/counters/{counter_id}/increment")
    async def increment_counter(counter_id: str):
        extra_or_404(counter_id)
        return {"count": await hub.increment_extra(counter_id)}

    @app.post("/api/counters/{counter_id}/reset")
    async def reset_counter(counter_id: str):
        extra_or_404(counter_id)
        hub.extra.reset(counter_id)
        return await counters_changed()

    @app.get("/api/stats")
    async def get_stats():
        return hub.stats.state()

    @app.post("/api/stats/export")
    async def export_stats():
        """Сохраняет историю сессий таблицей CSV в «Загрузки» и показывает её в Проводнике."""
        path = downloads_dir() / "swearcounter-stats.csv"
        try:
            # utf-8-sig: с BOM Excel открывает кириллицу без кракозябр.
            await asyncio.to_thread(path.write_text, hub.stats.csv(), encoding="utf-8-sig", newline="")
        except OSError as e:
            raise HTTPException(500, f"Не удалось сохранить таблицу: {e}") from None
        log.info("Статистика сохранена в %s", path)
        try:
            reveal(path)
        except OSError:
            pass  # таблица сохранена, путь есть в ответе
        return {"path": str(path)}

    @app.delete("/api/stats")
    async def clear_stats():
        hub.stats.clear()
        return hub.stats.state()

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

    def catalog_model(model_id: str) -> ModelInfo:
        model = find_model(model_id)
        if model is None:
            raise HTTPException(404, f"Неизвестная модель {model_id}")
        return model

    @app.post("/api/speech/download/{model_id}")
    async def post_speech_download(model_id: str):
        """Только скачивает модель: включают её отдельно, кликом по ней."""
        model = catalog_model(model_id)
        if not model.installed:
            downloader.start(model)
        return await get_speech()

    @app.delete("/api/speech/download/{model_id}")
    async def delete_speech_download(model_id: str):
        if not downloader.cancel(model_id):
            raise HTTPException(404, "Эта модель не скачивается")
        if wanted["model"] == model_id:
            wanted["model"] = None
        return await get_speech()

    @app.delete("/api/speech/model/{model_id}")
    async def delete_speech_model(model_id: str):
        """Удаляет скачанную модель с диска; выбранную удалить нельзя."""
        model = catalog_model(model_id)
        async with switch_lock:  # чтобы модель не включили, пока она удаляется
            if model.path == recognizer.model_path:
                raise HTTPException(409, "Выбранную модель удалить нельзя: сначала выберите другую")
            if downloader.state(model.id):
                raise HTTPException(409, "Модель скачивается: сначала отмените скачивание")
            if not model.installed:
                raise HTTPException(404, "Модель не скачана")
            try:
                await asyncio.to_thread(remove_model, model)
            except OSError as e:
                raise HTTPException(500, f"Не удалось удалить модель: {e}") from None
            log.info("Модель %s удалена", model.id)
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

        @app.post("/api/presets/custom/url")
        async def post_custom_preset_url(link: PresetLink):
            """Скачивает архив по ссылке (Яндекс Диск, Google Диск, Dropbox, прямая) и ставит его."""
            try:
                data = await asyncio.to_thread(preset_links.download, link.url)
                preset = await asyncio.to_thread(custom_presets.install, data)
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
            await presets_changed()
            return preset

        @app.post("/api/presets/custom/{preset_id}/export")
        async def export_custom_preset(preset_id: str):
            """Сохраняет набор zip-архивом в «Загрузки» и показывает его в Проводнике."""
            try:
                data = await asyncio.to_thread(custom_presets.export, preset_id)
            except KeyError:
                raise HTTPException(404, "Такого оформления нет") from None
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
            path = downloads_dir() / f"{preset_id}.zip"
            try:
                await asyncio.to_thread(path.write_bytes, data)
            except OSError as e:
                raise HTTPException(500, f"Не удалось сохранить архив: {e}") from None
            log.info("Оформление %s сохранено в %s", preset_id, path)
            try:
                reveal(path)
            except OSError:
                pass  # архив сохранён, путь есть в ответе
            return {"path": str(path)}

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
            try:
                await asyncio.to_thread(open_path, path)
            except OSError as e:
                raise HTTPException(500, f"Не удалось открыть: {e}") from None
            return word_lists.state()

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        if foreign_host(ws.headers.get("host")) or foreign_ws_origin(ws.headers.get("origin")):
            log.warning("Отклонено подключение WebSocket: %s", ws.headers.get("origin") or ws.headers.get("host"))
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            await hub.connect(ws, [sound_message(), style_message(), hub.counters_message()])
            log.info("Клиент подключён, всего: %d", len(hub.clients))
            # Клиенты ничего не присылают; читаем только чтобы заметить отключение.
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(ws)
            log.info("Клиент отключён, всего: %d", len(hub.clients))

    @app.websocket("/ws/events")
    async def events_endpoint(ws: WebSocket):
        """Только события счёта и паузы — для Streamer.bot и других программ (docs/STREAMERBOT.md)."""
        if foreign_host(ws.headers.get("host")) or foreign_ws_origin(ws.headers.get("origin")):
            log.warning("Отклонено подключение WebSocket: %s", ws.headers.get("origin") or ws.headers.get("host"))
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            await hub.connect(ws, events_only=True)
            log.info("Подключена программа к /ws/events")
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(ws)

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
