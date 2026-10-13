"""YouTube: чтение чата трансляции через YouTube Data API (ключ API, без входа в аккаунт).

С одним ключом API чат можно только читать: команды модераторов и Super Chat. Отвечать
в чат от имени пользователя API разрешает лишь после входа через OAuth, поэтому ответов
в чате YouTube нет: счёт зрители видят на экране в оверлее.
"""

import logging
from collections.abc import Callable
from urllib.parse import quote

from . import http
from .chat import YOUTUBE, ChatMessage
from .link import CONNECTED, Link, LinkError

log = logging.getLogger(__name__)

API = "https://www.googleapis.com/youtube/v3"
# Один запрос списка сообщений стоит 5 единиц из 10 000 суточной квоты: пауза не короче 10 секунд,
# иначе квоты хватит меньше чем на 3 часа трансляции.
MIN_POLL = 10.0
NO_CHAT_RETRY = 30.0
QUOTA_RETRY = 900.0
KEY_RETRY = 60.0
QUOTA_REASONS = ("quotaExceeded", "rateLimitExceeded", "dailyLimitExceeded")


def youtube_message(item: dict) -> ChatMessage | None:
    """Элемент liveChat/messages в ChatMessage; вступления, членство и т. п. — None."""
    snippet = item.get("snippet")
    author = item.get("authorDetails")
    if not isinstance(snippet, dict) or not isinstance(author, dict):
        return None
    kind = snippet.get("type")
    privileged = author.get("isChatOwner") is True or author.get("isChatModerator") is True
    name = str(author.get("displayName", ""))
    if kind == "textMessageEvent":
        details = snippet.get("textMessageDetails")
        text = details.get("messageText") if isinstance(details, dict) else None
        return ChatMessage(YOUTUBE, name, text if isinstance(text, str) else str(snippet.get("displayMessage", "")), privileged)
    if kind in ("superChatEvent", "superStickerEvent"):
        return ChatMessage(YOUTUBE, name, "", privileged, paid=1)
    return None


class YouTubeLink(Link):
    name = "youtube"

    def __init__(
        self,
        on_message: Callable[[ChatMessage], None],
        on_status: Callable[[str, dict], None] = lambda name, state: None,
        get: Callable = http.request_json,
        retry: float | None = None,
        min_poll: float = MIN_POLL,
    ):
        super().__init__(on_status, **({} if retry is None else {"retry": retry}))
        self._on_message = on_message
        self._get = get
        self._min_poll = min_poll
        self.title = ""  # название трансляции для страницы управления

    def configure_chat(self, video: str, api_key: str) -> None:
        self.configure((video, api_key) if video and api_key else None)

    def state(self) -> dict:
        return super().state() | {"title": self.title if self.connected else ""}

    def _api(self, path: str, **params: str) -> dict:
        query = "&".join(f"{key}={quote(value, safe='')}" for key, value in params.items())
        try:
            return self._get(f"{API}/{path}?{query}")
        except http.HttpError as e:
            if e.reason in QUOTA_REASONS:
                raise LinkError("Суточная квота YouTube API исчерпана, чат снова заработает завтра", QUOTA_RETRY) from None
            if e.reason in ("keyInvalid", "badRequest") or e.status == 400:
                raise LinkError("YouTube не принял ключ API: проверьте его", KEY_RETRY) from None
            if e.reason in ("liveChatEnded", "liveChatNotFound") or e.status == 404:
                raise LinkError("Чат трансляции недоступен или уже закончился", NO_CHAT_RETRY) from None
            if e.status == 403:
                raise LinkError(f"YouTube отказал в доступе: {e}", KEY_RETRY) from None
            raise LinkError(f"YouTube ответил ошибкой {e.status}") from None

    def _live_chat_id(self, video: str, key: str) -> str:
        data = self._api("videos", part="snippet,liveStreamingDetails", id=video, key=key)
        items = data.get("items")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise LinkError("Видео не найдено: проверьте ссылку", KEY_RETRY)
        item = items[0]
        details = item.get("liveStreamingDetails")
        chat_id = details.get("activeLiveChatId") if isinstance(details, dict) else None
        if not isinstance(chat_id, str) or not chat_id:
            raise LinkError("У видео нет активного чата: трансляция ещё не началась или уже закончилась", NO_CHAT_RETRY)
        snippet = item.get("snippet")
        self.title = str(snippet.get("title", ""))[:100] if isinstance(snippet, dict) else ""
        return chat_id

    def _session(self, config) -> None:
        video, key = config
        chat_id = self._live_chat_id(video, key)
        page_token = ""
        first = True
        while not self._should_stop():
            params = {"liveChatId": chat_id, "part": "snippet,authorDetails", "maxResults": "200", "key": key}
            if page_token:
                params["pageToken"] = page_token
            data = self._api("liveChat/messages", **params)
            self._set_status(CONNECTED, "")
            items = data.get("items")
            if not first and isinstance(items, list):  # на первой странице — прошлые сообщения, их не считаем
                for item in items:
                    message = youtube_message(item) if isinstance(item, dict) else None
                    if message is not None:
                        self._on_message(message)
            first = False
            page_token = str(data.get("nextPageToken") or page_token)
            interval = data.get("pollingIntervalMillis")
            wait = max(self._min_poll, interval / 1000 if isinstance(interval, int | float) else 0.0)
            self._changed.wait(wait)  # просыпается сразу, если изменили настройки или останавливаем
