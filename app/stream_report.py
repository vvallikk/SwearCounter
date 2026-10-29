"""Отчёт после стрима: итоги сессии текстом в Discord (вебхук) и/или Telegram (бот).

Отправляется кнопкой со страницы управления, а если включено — сам, когда в OBS
закончилась трансляция (событие приходит через app/obs_link.py). По умолчанию автоотправка
выключена и ничего никуда не уходит, пока пользователь сам не ввёл адрес вебхука или бота.

Адрес вебхука и токен бота — секреты, как API-ключи облачного распознавания: хранятся
в settings.json на этом компьютере, а наружу (в API и в лог) уходит только их хвост.
Запросы — urllib, как в app/updater.py, без сторонних библиотек.
"""

import asyncio
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import __version__, i18n
from .settings import Settings

log = logging.getLogger(__name__)

SETTING = "stream_report"
LAST_SETTING = "stream_report_last"
REQUEST_TIMEOUT = 10
TOP_WORDS = 5
MAX_TEXT = 2000  # больше Discord не примет в одном сообщении (у Telegram 4096)
MAX_SECRET = 512

DISCORD_WEBHOOK = re.compile(
    r"https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+"
)
TELEGRAM_TOKEN = re.compile(r"\d+:[A-Za-z0-9_-]{20,}")
TELEGRAM_CHAT = re.compile(r"-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{3,31}")
TELEGRAM_API = "https://api.telegram.org/bot{}/sendMessage"


class ReportError(Exception):
    """Отправка не удалась; текст — для страницы управления, без секретов."""


def post_json(url: str, payload: dict) -> bytes:
    """POST с JSON; ответ сервиса или urllib.error.* — тесты подменяют эту функцию."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        # Без своего User-Agent Cloudflare перед Discord отвечает 403 на «Python-urllib».
        headers={"Content-Type": "application/json", "User-Agent": f"SwearCounter/{__version__}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.read()


def mask(secret: str) -> str:
    """Хвост секрета, по которому его узнают: «…a1b2»."""
    return f"…{secret[-4:]}" if secret else ""


def censor(word: str) -> str:
    """Слово звёздочками, кроме первой буквы: «х**»."""
    return word[:1] + "*" * (len(word) - 1) if len(word) > 1 else "*"


def options(settings: Settings) -> dict:
    """Сохранённые настройки отчёта; испорченное значение — как не заданное."""
    saved = settings.get(SETTING)
    saved = saved if isinstance(saved, dict) else {}

    def text(key: str, pattern: re.Pattern) -> str:
        value = saved.get(key)
        return value if isinstance(value, str) and pattern.fullmatch(value) else ""

    return {
        "discord_webhook": text("discord_webhook", DISCORD_WEBHOOK),
        "telegram_token": text("telegram_token", TELEGRAM_TOKEN),
        "telegram_chat": text("telegram_chat", TELEGRAM_CHAT),
        "auto": saved.get("auto") is True,
        "censor": saved.get("censor") is not False,  # по умолчанию звёздочками
    }


def targets(opts: dict) -> list[str]:
    """Куда отправлять: discord и/или telegram (у Telegram нужны и токен, и чат)."""
    result = []
    if opts["discord_webhook"]:
        result.append("discord")
    if opts["telegram_token"] and opts["telegram_chat"]:
        result.append("telegram")
    return result


def duration_text(seconds: float, lang: str) -> str:
    seconds = max(0, round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return i18n.tr("{} ч {} мин", lang).format(hours, f"{minutes:02d}")
    if minutes:
        return i18n.tr("{} мин {} с", lang).format(minutes, f"{secs:02d}")
    return i18n.tr("{} с", lang).format(secs)


class StreamReport:
    """Итоги текущей сессии счётчика и их отправка.

    hub — app.server.Hub (счёт, статистика, таймер, цель, доп. счётчики).
    """

    def __init__(self, hub, settings: Settings, clock: Callable[[], float] = time.time):
        self._hub = hub
        self._settings = settings
        self._clock = clock
        self.session_start = clock()  # запуск программы или сброс счёта
        self.stream_start: float | None = None  # начало трансляции в OBS за этот запуск
        self._send_lock = threading.Lock()  # кнопка и конец трансляции не шлют одно дважды

    def on_reset(self) -> None:
        self.session_start = self._clock()

    def on_stream_started(self) -> None:
        self.stream_start = self._clock()

    def text(self, lang: str | None = None) -> str:
        lang = lang or i18n.language(self._settings)

        def tr(text: str) -> str:
            return i18n.tr(text, lang)

        hub = self._hub
        opts = options(self._settings)
        start = max(self.session_start, self.stream_start or 0)
        count = hub.counter.value
        lines = [
            tr("Счётчик матов: итоги стрима"),
            tr("Длительность: {}").format(duration_text(self._clock() - start, lang)),
            tr("Счёт: {}").format(count),
        ]
        session = hub.stats.current()
        words = sorted((session or {}).get("words", {}).items(), key=lambda item: (-item[1], item[0]))[:TOP_WORDS]
        if words:
            shown = ", ".join(f"{censor(w) if opts['censor'] else w} — {n}" for w, n in words)
            lines.append(tr("Чаще всего: {}").format(shown))
        streak = max(hub.timer.record, hub.timer.elapsed())
        lines.append(tr("Самая долгая серия без мата: {}").format(duration_text(streak, lang)))
        if hub.goal:
            if count >= hub.goal:
                lines.append(tr("Цель {}: достигнута").format(hub.goal))
            else:
                lines.append(tr("Цель {}: не достигнута ({} из {})").format(hub.goal, count, hub.goal))
        extra = [f"{c['name']} — {c['count']}" for c in hub.extra.items()]
        if extra:
            lines.append(tr("Другие счётчики: {}").format(", ".join(extra)))
        return "\n".join(lines)[:MAX_TEXT]

    def state(self) -> dict:
        """Для страницы управления: секреты — только хвостом."""
        opts = options(self._settings)
        last = self._settings.get(LAST_SETTING)
        return {
            "discord": {"set": bool(opts["discord_webhook"]), "hint": mask(opts["discord_webhook"])},
            "telegram": {"set": bool(opts["telegram_token"]), "hint": mask(opts["telegram_token"]),
                         "chat": opts["telegram_chat"]},
            "auto": opts["auto"],
            "censor": opts["censor"],
            "last": last if isinstance(last, dict) else None,
        }

    def auto_enabled(self) -> bool:
        opts = options(self._settings)
        return opts["auto"] and bool(targets(opts))

    def save(self, changes: dict) -> None:
        """changes: значение None — оставить как было, "" — удалить; ReportError, если не похоже."""
        saved = self._settings.get(SETTING)
        saved = dict(saved) if isinstance(saved, dict) else {}
        checks = {
            "discord_webhook": (DISCORD_WEBHOOK, "Адрес вебхука Discord должен начинаться с "
                                "https://discord.com/api/webhooks/ — скопируйте его целиком"),
            "telegram_token": (TELEGRAM_TOKEN, "Токен бота Telegram выглядит как 123456789:AAE…: "
                               "скопируйте его из @BotFather целиком"),
            "telegram_chat": (TELEGRAM_CHAT, "Чат Telegram — число (например, -1001234567890) "
                              "или @имя_канала"),
        }
        for key, (pattern, error) in checks.items():
            value = changes.get(key)
            if value is None:
                continue
            value = value.strip()
            if value and (len(value) > MAX_SECRET or not pattern.fullmatch(value)):
                raise ReportError(error)
            saved[key] = value
        for key in ("auto", "censor"):
            if changes.get(key) is not None:
                saved[key] = bool(changes[key])
        self._settings.set(SETTING, saved)

    def send(self, auto: bool = False) -> dict:
        """Отправляет отчёт всюду, куда настроено; блокирует, вызывать в отдельном потоке."""
        opts = options(self._settings)
        where = targets(opts)
        if not where:
            raise ReportError("Не задано, куда отправлять: укажите вебхук Discord или бота Telegram")
        with self._send_lock:
            text = self.text()
            results = {}
            for target in where:
                try:
                    if target == "discord":
                        _send_discord(opts["discord_webhook"], text)
                    else:
                        _send_telegram(opts["telegram_token"], opts["telegram_chat"], text)
                    results[target] = {"ok": True}
                    log.info("Отчёт о стриме отправлен: %s", target)
                except ReportError as e:
                    results[target] = {"ok": False, "error": str(e)}
                    log.warning("Не удалось отправить отчёт о стриме (%s): %s", target, e)
            last = {"time": round(self._clock()), "auto": auto, "results": results}
            self._settings.set(LAST_SETTING, last)
            return last

    def on_stream_stopped(self) -> None:
        """Конец трансляции в OBS (поток связи): отчёт уходит в фоне, если включено."""
        if not self.auto_enabled():
            self.stream_start = None
            return

        def run() -> None:
            try:
                self.send(auto=True)
            except ReportError as e:
                log.warning("Отчёт о стриме не отправлен: %s", e)
            finally:
                self.stream_start = None

        log.info("OBS: трансляция закончилась, отправляю отчёт")
        threading.Thread(target=run, name="stream-report", daemon=True).start()


def _send_discord(webhook: str, text: str) -> None:
    # allowed_mentions: слово из чата вроде @everyone в отчёте никого не позовёт.
    _post("Discord", webhook, {"content": text, "allowed_mentions": {"parse": []}})


def _send_telegram(token: str, chat: str, text: str) -> None:
    _post("Telegram", TELEGRAM_API.format(token), {"chat_id": chat, "text": text, "disable_web_page_preview": True})


def _post(service: str, url: str, payload: dict) -> None:
    """Ошибки — ReportError без адреса: в адресе Telegram лежит токен бота."""
    try:
        post_json(url, payload)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("description") or ""  # так отвечает Telegram
        except (OSError, ValueError, AttributeError):
            pass
        message = f"{service} ответил ошибкой {e.code}"
        raise ReportError(f"{message}: {detail[:200]}" if detail else message) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise ReportError(f"нет связи с {service} ({reason})") from None


class ReportChoice(BaseModel):
    discord_webhook: str | None = None  # None — оставить сохранённое, "" — удалить
    telegram_token: str | None = None
    telegram_chat: str | None = None
    auto: bool | None = None
    censor: bool | None = None


def router(report: StreamReport, on_change: Callable[[], None] = lambda: None) -> APIRouter:
    """/api/stream-report: настройки, предпросмотр и отправка. on_change — включить связь с OBS."""
    api = APIRouter()

    @api.get("/api/stream-report")
    async def get_report():
        return report.state()

    @api.post("/api/stream-report")
    async def post_report(choice: ReportChoice):
        try:
            report.save(choice.model_dump())
        except ReportError as e:
            raise HTTPException(400, str(e)) from None
        on_change()
        return report.state()

    @api.get("/api/stream-report/preview")
    async def get_preview():
        return {"text": report.text()}

    @api.post("/api/stream-report/send")
    async def post_send():
        try:
            await asyncio.to_thread(report.send)
        except ReportError as e:
            raise HTTPException(400, str(e)) from None
        return report.state()

    return api
