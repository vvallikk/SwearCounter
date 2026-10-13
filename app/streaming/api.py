"""Маршруты /api/streaming: настройки интеграций и проверка связи."""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import options as opts
from .chat import TWITCH, YOUTUBE
from .manager import Streaming

MAX_SECRET = 512


class TwitchBody(BaseModel):
    enabled: bool = False
    channel: str = ""
    token: str | None = None  # None — оставить сохранённый
    command: str = opts.DEFAULT_COMMAND
    reply: str = opts.DEFAULT_REPLY
    cooldown: int = 10
    mod_commands: bool = True
    announce_milestones: bool = True
    announce_text: str = opts.DEFAULT_ANNOUNCE
    announce_every: int = 0
    bits_per_swear: int = 0
    markers: bool = False


class YouTubeBody(BaseModel):
    enabled: bool = False
    video: str = ""
    api_key: str | None = None  # None — оставить сохранённый
    command: str = opts.DEFAULT_COMMAND
    mod_commands: bool = True
    superchat_swears: int = 0


class StreamingBody(BaseModel):
    twitch: TwitchBody | None = None  # None — платформу не менять
    youtube: YouTubeBody | None = None


def make_router(streaming: Streaming) -> APIRouter:
    router = APIRouter()
    settings = streaming.settings

    def changed_secret(platform: str, value: str | None) -> str | None:
        if value is None:
            return None
        value = opts.clean_token(value)
        if len(value) > MAX_SECRET:
            raise HTTPException(400, "Слишком длинный токен или ключ")
        return value

    @router.get("/api/streaming")
    async def get_streaming():
        return streaming.state()

    @router.post("/api/streaming")
    async def post_streaming(body: StreamingBody):
        saved = streaming.options()
        secrets: dict[str, str] = {}
        parts = {TWITCH: body.twitch, YOUTUBE: body.youtube}
        try:
            for platform, part in parts.items():
                if part is None:
                    continue
                raw = part.model_dump(exclude={"token", "api_key"})
                saved[platform] = opts.CLEANERS[platform](raw)
                secret = changed_secret(platform, part.token if platform == TWITCH else part.api_key)
                if secret is not None:
                    secrets[platform] = secret
        except opts.OptionsError as e:
            raise HTTPException(400, str(e)) from None
        for platform, label in ((TWITCH, "токен Twitch"), (YOUTUBE, "ключ YouTube API")):
            if saved[platform]["enabled"] and not (secrets.get(platform) or streaming.token(platform)):
                raise HTTPException(400, f"Вставьте {label}")
        for platform, secret in secrets.items():
            settings.set(opts.TOKEN_SETTINGS[platform], secret)
        settings.set(opts.SETTING, saved)
        streaming.apply()
        return streaming.state()

    @router.post("/api/streaming/twitch/test")
    async def post_twitch_test():
        """Показывает в чате текущий ответ на команду: так видно, что связь и права в порядке."""
        if not streaming.twitch.connected:
            raise HTTPException(400, "Нет связи с чатом Twitch: включите интеграцию и дождитесь статуса «на связи»")
        if not await asyncio.to_thread(streaming.twitch.say, streaming.test_text()):
            raise HTTPException(400, "Сообщение не отправлено: подождите пару секунд и повторите")
        return {"sent": True}

    return router
