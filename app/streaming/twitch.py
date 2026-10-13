"""Twitch: чат по IRC (чтение команд и биты, ответы и объявления) и маркеры трансляции.

Нужен токен пользователя с правами chat:read и chat:edit (для маркеров ещё
channel:manage:broadcast). Токен получает сам пользователь, например в генераторе
токенов Twitch; программа хранит его только в settings.json и никуда, кроме Twitch, не шлёт.
"""

import logging
import queue
import socket
import ssl
import time
from collections.abc import Callable

from . import http
from .chat import ChatMessage, parse_irc, twitch_message
from .link import CONNECTED, Link, LinkError

log = logging.getLogger(__name__)

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6697
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
MARKERS_URL = "https://api.twitch.tv/helix/streams/markers"

READ_TIMEOUT = 0.5  # так часто поток проверяет, не изменились ли настройки
SEND_INTERVAL = 1.5  # пауза между сообщениями: лимит Twitch — 20 за 30 секунд для обычного бота
OUTBOX_SIZE = 5
MAX_MESSAGE = 450
AUTH_RETRY = 60.0  # с неверным токеном чаще пробовать бессмысленно
REQUIRED_SCOPES = ("chat:read", "chat:edit")
MARKER_SCOPE = "channel:manage:broadcast"
MARKER_DESCRIPTION_MAX = 140


class IrcConnection:
    """TLS-соединение с чатом Twitch: строки туда и обратно."""

    def __init__(self, sock: socket.socket):
        self._sock = sock
        self._buffer = b""

    @classmethod
    def open(cls) -> "IrcConnection":
        raw = socket.create_connection((IRC_HOST, IRC_PORT), timeout=10)
        try:
            sock = ssl.create_default_context().wrap_socket(raw, server_hostname=IRC_HOST)
        except OSError:
            raw.close()
            raise
        return cls(sock)

    def send(self, line: str) -> None:
        self._sock.sendall(line.replace("\r", " ").replace("\n", " ").encode("utf-8") + b"\r\n")

    def read(self, timeout: float) -> list[str]:
        """Новые строки; пусто, если за timeout ничего не пришло. ConnectionError — Twitch закрыл связь."""
        self._sock.settimeout(timeout)
        try:
            chunk = self._sock.recv(4096)
        except (TimeoutError, ssl.SSLWantReadError):
            return []
        if not chunk:
            raise ConnectionError("Twitch закрыл соединение")
        self._buffer += chunk
        *lines, self._buffer = self._buffer.split(b"\r\n")
        return [line.decode("utf-8", "replace") for line in lines if line]

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


def validate_token(token: str, get: Callable = http.request_json) -> dict:
    """Кому принадлежит токен и какие у него права; LinkError, если Twitch его не принял."""
    try:
        data = get(VALIDATE_URL, headers={"Authorization": f"OAuth {token}"})
    except http.HttpError as e:
        if e.status == 401:
            raise LinkError("Twitch не принял токен: он неверный или истёк, получите новый", AUTH_RETRY) from None
        raise LinkError(f"Twitch не ответил на проверку токена ({e.status})") from None
    login, scopes = data.get("login"), data.get("scopes")
    if not isinstance(login, str) or not login:
        raise LinkError("Twitch вернул непонятный ответ на проверку токена")
    scopes = [s for s in scopes if isinstance(s, str)] if isinstance(scopes, list) else []
    missing = [scope for scope in REQUIRED_SCOPES if scope not in scopes]
    if missing:
        raise LinkError(f"Токену не хватает прав: {', '.join(missing)}", AUTH_RETRY)
    return {
        "login": login.lower(),
        "user_id": str(data.get("user_id", "")),
        "client_id": str(data.get("client_id", "")),
        "scopes": scopes,
    }


class TwitchLink(Link):
    name = "twitch"

    def __init__(
        self,
        on_message: Callable[[ChatMessage], None],
        on_status: Callable[[str, dict], None] = lambda name, state: None,
        connect: Callable[[], IrcConnection] = IrcConnection.open,
        validate: Callable[[str], dict] = validate_token,
        post: Callable = http.request_json,
        retry: float | None = None,
    ):
        super().__init__(on_status, **({} if retry is None else {"retry": retry}))
        self._on_message = on_message
        self._connect = connect
        self._validate = validate
        self._post = post
        self._outbox: queue.Queue[str] = queue.Queue(OUTBOX_SIZE)
        self._identity: dict | None = None
        self._token = ""
        self._channel = ""

    def configure_chat(self, channel: str, token: str) -> None:
        """Пустой канал или токен выключает связь."""
        self.configure((channel, token) if channel and token else None)

    def state(self) -> dict:
        identity = self._identity if self.connected else None
        return super().state() | {
            "login": identity["login"] if identity else "",
            # Маркер ставится на канале владельца токена и только с правом channel:manage:broadcast.
            "can_mark": bool(identity and MARKER_SCOPE in identity["scopes"] and identity["login"] == self._channel),
        }

    def say(self, text: str) -> bool:
        """Поставить сообщение в очередь отправки; False, если связи нет или очередь забита."""
        if not self.connected:
            return False
        text = " ".join(text.split())[:MAX_MESSAGE]
        if not text:
            return False
        try:
            self._outbox.put_nowait(text)
        except queue.Full:
            return False
        return True

    def marker(self, description: str) -> None:
        """Маркер на таймлайне идущей трансляции (блокирующий запрос — вызывать не из цикла событий)."""
        identity = self._identity
        if identity is None or not self.state()["can_mark"]:
            raise LinkError("Для маркеров нужен токен владельца канала с правом channel:manage:broadcast")
        try:
            self._post(
                MARKERS_URL,
                headers={"Authorization": f"Bearer {self._token}", "Client-Id": identity["client_id"]},
                body={"user_id": identity["user_id"], "description": description[:MARKER_DESCRIPTION_MAX]},
            )
        except http.HttpError as e:
            if e.status == 404:  # трансляция не идёт
                raise LinkError("Маркер не поставлен: трансляция не идёт") from None
            raise LinkError(f"Twitch не принял маркер ({e.status}): {e}") from None

    def _session(self, config) -> None:
        self._channel, self._token = config
        identity = self._validate(self._token)
        conn = self._connect()
        self._identity = identity
        try:
            conn.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
            conn.send(f"PASS oauth:{self._token}")
            conn.send(f"NICK {identity['login']}")
            conn.send(f"JOIN #{self._channel}")
            last_sent = float("-inf")
            while not self._should_stop():
                try:
                    lines = conn.read(READ_TIMEOUT)
                except ConnectionError as e:
                    raise LinkError(str(e), retry=2.0) from None
                for raw in lines:
                    self._handle(conn, raw)
                if self.connected and time.monotonic() - last_sent >= SEND_INTERVAL:
                    try:
                        text = self._outbox.get_nowait()
                    except queue.Empty:
                        continue
                    conn.send(f"PRIVMSG #{self._channel} :{text}")
                    last_sent = time.monotonic()
        finally:
            conn.close()
            self._identity = None
            while not self._outbox.empty():  # старые сообщения на новом подключении уже не нужны
                try:
                    self._outbox.get_nowait()
                except queue.Empty:
                    break

    def _handle(self, conn: IrcConnection, raw: str) -> None:
        line = parse_irc(raw)
        if line is None:
            return
        if line.command == "PING":
            conn.send(f"PONG :{line.trailing or 'tmi.twitch.tv'}")
        elif line.command == "RECONNECT":
            raise LinkError("Twitch попросил переподключиться", retry=1.0)
        elif line.command == "NOTICE" and "authentication failed" in line.trailing.lower():
            raise LinkError("Twitch не принял токен: он неверный или истёк, получите новый", AUTH_RETRY)
        elif line.command == "ROOMSTATE":
            self._set_status(CONNECTED, "")
        elif line.command == "PRIVMSG":
            message = twitch_message(line)
            if message is not None:
                self._on_message(message)
