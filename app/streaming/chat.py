"""Сообщения чата и их разбор: общая часть для Twitch и YouTube, без сети и потоков."""

import re
from dataclasses import dataclass

TWITCH = "twitch"
YOUTUBE = "youtube"

MAX_ADD = 100  # столько можно прибавить одной командой модератора или одним сообщением с битами


@dataclass(frozen=True)
class ChatMessage:
    platform: str
    author: str
    text: str
    privileged: bool = False  # модератор или владелец канала
    bits: int = 0  # Twitch: сколько битов приложено к сообщению (Cheer)
    paid: int = 0  # YouTube: 1 — Super Chat или Super Sticker


@dataclass(frozen=True)
class Action:
    kind: str  # "show" | "add" | "reset"
    delta: int = 0


def parse_command(text: str, command: str, privileged: bool, mod_commands: bool) -> Action | None:
    """Команда зрителя («!маты») показывает счёт; модератор может дописать «+3» или «сброс».

    Всё остальное в чате — не команда. Регистр не важен, команда должна быть первым словом.
    """
    words = text.split()
    if not words or words[0].casefold() != command.casefold():
        return None
    args = words[1:]
    if not (privileged and mod_commands and args):
        return Action("show")
    arg = args[0].casefold()
    if arg in ("сброс", "reset"):
        return Action("reset")
    match = re.fullmatch(r"\+(\d{1,3})", arg)
    if match and 1 <= int(match.group(1)) <= MAX_ADD:
        return Action("add", int(match.group(1)))
    return Action("show")


def render(template: str, **values: object) -> str:
    """Подставляет {имя}; незнакомые {слова} остаются как есть, а не роняют отправку."""
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template)


# --- Twitch IRC ---

_TAG_ESCAPES = {"s": " ", ":": ";", "r": "\r", "n": "\n", "\\": "\\"}
_IRC_LINE = re.compile(r"^(?:@(?P<tags>\S+) )?(?::(?P<prefix>\S+) )?(?P<command>\S+)(?: (?P<params>.*))?$")
_ACTION = "\x01ACTION "


@dataclass(frozen=True)
class IrcLine:
    command: str
    params: str = ""
    tags: dict | None = None
    nick: str = ""

    @property
    def trailing(self) -> str:
        """Текст после « :» — сообщение чата или текст уведомления."""
        _, sep, rest = (" " + self.params).partition(" :")
        return rest if sep else ""


def _unescape_tag(value: str) -> str:
    return re.sub(r"\\(.)", lambda m: _TAG_ESCAPES.get(m.group(1), m.group(1)), value)


def parse_irc(line: str) -> IrcLine | None:
    match = _IRC_LINE.match(line.strip())
    if match is None:
        return None
    tags = {}
    for pair in (match["tags"] or "").split(";"):
        if pair:
            key, _, value = pair.partition("=")
            tags[key] = _unescape_tag(value)
    prefix = match["prefix"] or ""
    return IrcLine(match["command"], match["params"] or "", tags, prefix.partition("!")[0])


def twitch_message(line: IrcLine) -> ChatMessage | None:
    """PRIVMSG из чата в ChatMessage; всё остальное (JOIN, USERSTATE…) — None."""
    if line.command != "PRIVMSG":
        return None
    tags = line.tags or {}
    badges = tags.get("badges", "").split(",")
    privileged = tags.get("mod") == "1" or any(b.startswith(("broadcaster/", "moderator/")) for b in badges)
    text = line.trailing
    if text.startswith(_ACTION) and text.endswith("\x01"):  # «/me ...»
        text = text[len(_ACTION):-1]
    bits = tags.get("bits", "")
    return ChatMessage(
        TWITCH,
        tags.get("display-name") or line.nick,
        text,
        privileged,
        bits=int(bits) if bits.isdigit() else 0,
    )
