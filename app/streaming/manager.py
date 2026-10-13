"""Интеграции со стримами: чат Twitch и YouTube отдаёт команды и подарки зрителей счётчику,
а счётчик сообщает в чат и ставит маркеры.

Что умеет:
- команда «!маты» в чате показывает счёт (ответ — только в Twitch);
- модератор пишет «!маты +3» или «!маты сброс»;
- биты Twitch и Super Chat YouTube прибавляют слова («штраф от зрителей»);
- Twitch: объявление в чат на особых числах и каждые N слов, маркер на таймлайне трансляции.
"""

import asyncio
import logging
import time

from .. import goals
from ..settings import Settings
from . import options as opts
from .chat import TWITCH, YOUTUBE, Action, ChatMessage, parse_command, render
from .link import Link
from .twitch import TwitchLink
from .youtube import YouTubeLink

log = logging.getLogger(__name__)

MARKER_INTERVAL = 5.0  # не чаще: серия слов подряд — один маркер, а не десять


class Streaming:
    def __init__(self, hub, settings: Settings, twitch: TwitchLink | None = None, youtube: YouTubeLink | None = None):
        self.hub = hub
        self.settings = settings
        self.twitch = twitch or TwitchLink(self._from_thread_message, self._on_status)
        self.youtube = youtube or YouTubeLink(self._from_thread_message, self._on_status)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._background: set[asyncio.Task] = set()
        self._last_reply = {TWITCH: float("-inf"), YOUTUBE: float("-inf")}
        self._last_marker = float("-inf")

    # --- настройки ---

    def options(self) -> dict:
        return opts.load(self.settings.get(opts.SETTING))

    def token(self, platform: str) -> str:
        value = self.settings.get(opts.TOKEN_SETTINGS[platform], "")
        return value if isinstance(value, str) else ""

    def links(self) -> dict[str, Link]:
        return {TWITCH: self.twitch, YOUTUBE: self.youtube}

    def state(self) -> dict:
        options = self.options()
        return {
            platform: options[platform] | {"has_token": bool(self.token(platform))} | link.state()
            for platform, link in self.links().items()
        }

    def apply(self) -> None:
        """Подключает или отключает платформы по сохранённым настройкам."""
        options = self.options()
        twitch, youtube = options[TWITCH], options[YOUTUBE]
        enabled = twitch["enabled"]
        self.twitch.configure_chat(twitch["channel"] if enabled else "", self.token(TWITCH))
        enabled = youtube["enabled"]
        self.youtube.configure_chat(youtube["video"] if enabled else "", self.token(YOUTUBE))

    # --- жизненный цикл ---

    def attach(self) -> None:
        self.hub.count_listeners.append(self.on_count)

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self.apply()
        self.twitch.start()
        self.youtube.start()

    def stop(self) -> None:
        self._loop = None
        self.twitch.stop()
        self.youtube.stop()

    # --- вызовы из потоков связи ---

    def _from_thread_message(self, message: ChatMessage) -> None:
        self._submit(self.handle_message(message))

    def _on_status(self, name: str, state: dict) -> None:
        self._submit(self.hub.broadcast({"type": "streaming", "platform": name, **state}))

    def _submit(self, coro) -> None:
        loop = self._loop
        if loop is None:
            coro.close()
            return
        asyncio.run_coroutine_threadsafe(coro, loop)

    # --- логика ---

    async def handle_message(self, message: ChatMessage) -> None:
        options = self.options()[message.platform]
        if not options["enabled"]:
            return
        if message.platform == TWITCH:
            await self._handle_gifts(options["bits_per_swear"] and message.bits // options["bits_per_swear"])
        elif message.paid and options["superchat_swears"]:
            await self._handle_gifts(options["superchat_swears"])
        action = parse_command(message.text, options["command"], message.privileged, options["mod_commands"])
        if action is not None:
            await self._run_action(message, action, options)

    async def _handle_gifts(self, swears: int) -> None:
        if swears > 0:
            await self.hub.increment(min(swears, 100))

    async def _run_action(self, message: ChatMessage, action: Action, options: dict) -> None:
        if action.kind == "add":
            await self.hub.increment(action.delta)
            log.info("%s: модератор прибавил %d", message.platform, action.delta)
        elif action.kind == "reset":
            await self.hub.reset()
            log.info("%s: модератор сбросил счёт", message.platform)
        elif message.platform == TWITCH:
            # Ответ на команду зрителя не чаще раза в cooldown секунд; модератору отвечаем всегда.
            now = time.monotonic()
            if not message.privileged and now - self._last_reply[TWITCH] < options["cooldown"]:
                return
            self._last_reply[TWITCH] = now
        if message.platform == TWITCH:
            self.twitch.say(render(options["reply"], count=self.hub.counter.value, user=message.author))

    def on_count(self, before: int, count: int) -> None:
        """Слушатель счётчика (Hub.count_listeners): объявления и маркеры."""
        if count <= before or self._loop is None:
            return
        options = self.options()[TWITCH]
        if not options["enabled"] or not self.twitch.connected:
            return
        text = self._announcement(options, before, count)
        if text:
            self.twitch.say(text)
        if options["markers"]:
            now = time.monotonic()
            if now - self._last_marker >= MARKER_INTERVAL and self.twitch.state()["can_mark"]:
                self._last_marker = now
                self._spawn(self._put_marker(f"Мат №{count}"))

    def _announcement(self, options: dict, before: int, count: int) -> str:
        milestone = goals.reached(self.hub.milestones, self.hub.goal, before, count) if options["announce_milestones"] else None
        every = options["announce_every"]
        if milestone is None and every and before // every < count // every:
            milestone = count // every * every
        if milestone is None:
            return ""
        return render(options["announce_text"], count=count, milestone=milestone)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _put_marker(self, description: str) -> None:
        try:
            await asyncio.to_thread(self.twitch.marker, description)
        except Exception as e:  # noqa: BLE001 маркер — мелочь, счёту он не мешает
            log.info("Twitch: %s", e)

    def test_text(self) -> str:
        """Текст пробного сообщения в чат Twitch (кнопка на странице управления)."""
        return render(self.options()[TWITCH]["reply"], count=self.hub.counter.value, user="")

