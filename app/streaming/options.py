"""Настройки интеграций со стримами: проверка и значения по умолчанию.

Ключи и токены лежат в settings.json отдельно (twitch_token, youtube_api_key) и странице
не отдаются: только «задан ли».
"""

import re
from urllib.parse import parse_qs, urlsplit

from .. import goals

SETTING = "streaming"
TOKEN_SETTINGS = {"twitch": "twitch_token", "youtube": "youtube_api_key"}

DEFAULT_COMMAND = "!маты"
DEFAULT_REPLY = "Маты: {count}"
DEFAULT_ANNOUNCE = "🎉 Счёт достиг {milestone}! Сейчас: {count}"
MAX_TEXT = 200  # сообщение чата Twitch — до 500 символов, шаблону хватит и этого
MAX_COOLDOWN = 600
MAX_BITS = 100_000

DEFAULTS = {
    "twitch": {
        "enabled": False,
        "channel": "",
        "command": DEFAULT_COMMAND,
        "reply": DEFAULT_REPLY,
        "cooldown": 10,  # секунд между ответами на «!маты» от зрителей
        "mod_commands": True,
        "announce_milestones": True,
        "announce_text": DEFAULT_ANNOUNCE,
        "announce_every": 0,  # 0 — не сообщать каждые N слов
        "bits_per_swear": 0,  # 0 — биты на счёт не влияют
        "markers": False,  # маркер на таймлайне трансляции на каждое слово
    },
    "youtube": {
        "enabled": False,
        "video": "",
        "command": DEFAULT_COMMAND,
        "mod_commands": True,
        "superchat_swears": 0,  # сколько слов прибавляет один Super Chat; 0 — не влияет
    },
}


class OptionsError(ValueError):
    pass


CHANNEL = re.compile(r"[a-z0-9_]{3,25}")
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def clean_channel(value: str) -> str:
    """Имя канала из имени, @имени или ссылки twitch.tv/имя; пусто — не задан."""
    value = value.strip().lower()
    if not value:
        return ""
    if "/" in value:
        parts = urlsplit(value if "//" in value else f"//{value}")
        if not (parts.hostname or "").endswith("twitch.tv"):
            raise OptionsError("Укажите имя канала Twitch или ссылку twitch.tv/имя")
        value = parts.path.strip("/").split("/")[0]
    value = value.lstrip("@#")
    if not CHANNEL.fullmatch(value):
        raise OptionsError("Имя канала Twitch — латинские буквы, цифры и «_», от 3 до 25 символов")
    return value


def clean_video(value: str) -> str:
    """Идентификатор видео из ссылки (watch?v=, youtu.be/, /live/) или самого идентификатора."""
    value = value.strip()
    if not value:
        return ""
    if VIDEO_ID.fullmatch(value):
        return value
    parts = urlsplit(value if "//" in value else f"//{value}")
    host = (parts.hostname or "").removeprefix("www.").removeprefix("m.")
    candidate = ""
    if host == "youtu.be":
        candidate = parts.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com"):
        segments = parts.path.strip("/").split("/")
        if segments[0] in ("live", "embed", "shorts") and len(segments) > 1:
            candidate = segments[1]
        else:
            candidate = parse_qs(parts.query).get("v", [""])[0]
    if not VIDEO_ID.fullmatch(candidate):
        raise OptionsError("Не удалось найти видео: вставьте ссылку на трансляцию YouTube")
    return candidate


def clean_command(value: str) -> str:
    value = value.strip()
    if value and not value.startswith("!"):
        value = "!" + value
    if not re.fullmatch(r"![^\s!]{1,24}", value):
        raise OptionsError("Команда — одно слово без пробелов, например !маты")
    return value


def clean_text(value: str, what: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise OptionsError(f"{what}: текст не может быть пустым")
    if len(value) > MAX_TEXT:
        raise OptionsError(f"{what}: не длиннее {MAX_TEXT} символов")
    return value


def _number(value, low: int, high: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise OptionsError(f"{what}: целое число от {low} до {high}")
    return value


def clean_twitch(raw: dict) -> dict:
    options = DEFAULTS["twitch"] | {k: v for k, v in raw.items() if k in DEFAULTS["twitch"]}
    options["channel"] = clean_channel(str(options["channel"]))
    options["command"] = clean_command(str(options["command"]))
    options["reply"] = clean_text(str(options["reply"]), "Ответ на команду")
    options["announce_text"] = clean_text(str(options["announce_text"]), "Сообщение о цели")
    options["cooldown"] = _number(options["cooldown"], 0, MAX_COOLDOWN, "Пауза между ответами")
    options["announce_every"] = _number(options["announce_every"], 0, goals.MAX_VALUE, "Сообщать каждые N слов")
    options["bits_per_swear"] = _number(options["bits_per_swear"], 0, MAX_BITS, "Битов на одно слово")
    for key in ("enabled", "mod_commands", "announce_milestones", "markers"):
        options[key] = options[key] is True
    if options["enabled"] and not options["channel"]:
        raise OptionsError("Укажите канал Twitch")
    return options


def clean_youtube(raw: dict) -> dict:
    options = DEFAULTS["youtube"] | {k: v for k, v in raw.items() if k in DEFAULTS["youtube"]}
    options["video"] = clean_video(str(options["video"]))
    options["command"] = clean_command(str(options["command"]))
    options["superchat_swears"] = _number(options["superchat_swears"], 0, 100, "Слов за Super Chat")
    for key in ("enabled", "mod_commands"):
        options[key] = options[key] is True
    if options["enabled"] and not options["video"]:
        raise OptionsError("Вставьте ссылку на трансляцию YouTube")
    return options


CLEANERS = {"twitch": clean_twitch, "youtube": clean_youtube}


def load(saved) -> dict:
    """Сохранённые настройки; испорченное (правили руками) — по умолчанию, платформа выключена."""
    saved = saved if isinstance(saved, dict) else {}
    result = {}
    for platform, clean in CLEANERS.items():
        raw = saved.get(platform)
        try:
            result[platform] = clean(raw if isinstance(raw, dict) else {})
        except OptionsError:
            result[platform] = dict(DEFAULTS[platform])
    return result


def clean_token(value: str) -> str:
    """Токен без пробелов и префикса «oauth:», с которым его выдаёт генератор токенов."""
    value = value.strip()
    return value[len("oauth:"):] if value.lower().startswith("oauth:") else value
