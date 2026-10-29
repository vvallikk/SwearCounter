"""Живые субтитры для OBS: распознанная речь в оверлее /overlay/?show=subtitles.

По умолчанию выключены: пока выключатель на странице управления не включён, текст речи
никуда не уходит. Идут только обычным клиентам /ws (оверлей, страница управления),
в /ws/events не попадают. На паузе распознавания не отправляются. Маты по умолчанию
скрываются звёздочками по тому же списку корней, что и счёт (app/profanity.py).
"""

import re
from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from pydantic import BaseModel

from . import i18n
from .profanity import current_roots, normalize
from .settings import Settings

ENABLED_SETTING = "subtitles"
UNCENSORED_SETTING = "subtitles_uncensored"
MASK = "*"
# Пример для кнопки на странице управления: подогнать источник в OBS, не говоря в микрофон.
SAMPLE = "Так будут выглядеть субтитры: фраза держится несколько секунд и гаснет"

_WORD_RE = re.compile(r"\w+")


def censor(text: str, roots: tuple[str, ...] | None = None) -> str:
    """Слова, начинающиеся с корня из списка, заменяются звёздочками той же длины."""
    roots = current_roots() if roots is None else tuple(roots)
    if not roots:
        return text
    return _WORD_RE.sub(lambda m: MASK * len(m[0]) if normalize(m[0]).startswith(roots) else m[0], text)


class SubtitlesChoice(BaseModel):
    enabled: bool | None = None
    uncensored: bool | None = None


class Subtitles:
    def __init__(
        self,
        settings: Settings,
        broadcast: Callable[[dict], Awaitable[None]],
        paused: Callable[[], bool] = lambda: False,
        censor: Callable[[str], str] = censor,
    ):
        self.settings = settings
        self.broadcast = broadcast
        self.paused = paused
        self.censor = censor
        self._last: tuple[str, bool] | None = None  # последняя отправленная фраза

    @property
    def enabled(self) -> bool:
        return self.settings.get(ENABLED_SETTING) is True

    @property
    def uncensored(self) -> bool:
        return self.settings.get(UNCENSORED_SETTING) is True

    def message(self) -> dict:
        return {"type": "subtitles", "enabled": self.enabled, "uncensored": self.uncensored}

    async def feed(self, text: str, is_final: bool) -> None:
        if not self.enabled or self.paused():
            self._last = None
            return
        text = " ".join(text.split())
        # Пустой промежуточный текст (начало фразы) не стирает только что сказанную фразу.
        if not text:
            return
        shown = text if self.uncensored else self.censor(text)
        # Промежуточный текст приходит много раз в секунду и часто не меняется.
        if (shown, is_final) == self._last:
            return
        self._last = (shown, is_final)
        await self.broadcast({"type": "subtitle", "text": shown, "final": is_final})

    def sample(self) -> str:
        return i18n.tr(SAMPLE, i18n.language(self.settings))

    async def configure(self, choice: SubtitlesChoice) -> dict:
        if choice.enabled is not None:
            self.settings.set(ENABLED_SETTING, choice.enabled)
        if choice.uncensored is not None:
            self.settings.set(UNCENSORED_SETTING, choice.uncensored)
        self._last = None
        # Оверлей по этому сообщению гасит текст, если субтитры выключили.
        await self.broadcast(self.message())
        return self.message()

    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/api/subtitles")
        async def get_subtitles():
            return self.message()

        @router.post("/api/subtitles")
        async def post_subtitles(choice: SubtitlesChoice):
            return await self.configure(choice)

        @router.post("/api/subtitles/test")
        async def post_subtitles_test():
            """Пример фразы в оверлей; работает и при выключенных субтитрах — это не речь."""
            await self.broadcast({"type": "subtitle", "text": self.sample(), "final": True})
            return {"ok": True}

        return router
