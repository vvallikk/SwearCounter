"""Голосовые команды: «счётчик пауза», «счётчик плюс один», «счётчик сцена игра».

Команда — кодовое слово и фраза после него: без кодового слова обычная речь ничего
не включает. Срабатывают только окончательные фразы распознавания: промежуточный
текст переписывается на ходу. Одна и та же команда повторно не срабатывает
COOLDOWN секунд — движки иногда выдают фразу дважды.

На паузе команды тоже слушаются (иначе не сказать «продолжить»), считает мат
при этом только SwearTracker, а его пауза не касается этого модуля.

Настройки — в settings.json под ключом SETTING; по умолчанию выключено.
Выполняет команды сервер (app/server.py): ему нужны счётчик и связь с OBS.
"""

import logging
import re
import time
from collections.abc import Awaitable, Callable

from .profanity import normalize
from .settings import Settings

log = logging.getLogger(__name__)

SETTING = "voice_commands"
COOLDOWN = 2.0  # секунд между повторами одной команды
# Сколько посторонних слов можно сказать между кодовым словом и фразой («счётчик, давай пауза»).
MAX_GAP_WORDS = 3

# Действия с фиксированной фразой; сцен может быть несколько, у каждой свои фразы.
ACTIONS = ("pause", "resume", "increment", "reset")
SCENE = "scene"
DEFAULT_WAKE_WORDS = ["счётчик", "counter"]
# Фразы RU и EN вместе: модель распознавания может быть любого языка.
DEFAULT_PHRASES = {
    "pause": ["пауза", "pause"],
    "resume": ["продолжить", "продолжай", "resume", "continue"],
    "increment": ["плюс один", "плюс", "plus one"],
    "reset": ["сброс", "обнулить", "reset"],
}

MAX_PHRASES = 10  # фраз у одной команды
MAX_PHRASE = 64  # символов во фразе
MAX_SCENES = 20
MAX_SCENE_NAME = 256

_WORD_RE = re.compile(r"\w+")


class VoiceCommandsError(ValueError):
    pass


def words(text: str) -> tuple[str, ...]:
    return tuple(_WORD_RE.findall(normalize(text)))


def clean_phrases(value, default: list[str] | None = None) -> list[str]:
    """Фразы без пустых и повторов; не список — фразы по умолчанию."""
    if not isinstance(value, list):
        return list(default or [])
    phrases = []
    for phrase in value:
        if isinstance(phrase, str) and words(phrase):
            phrases.append(" ".join(phrase.split()))
    return list(dict.fromkeys(phrases))[:MAX_PHRASES]


def default_config() -> dict:
    return {
        "enabled": False,
        "wake_words": list(DEFAULT_WAKE_WORDS),
        "allow_reset": False,  # сброс голосом случайно стёр бы счёт
        "phrases": {action: list(phrases) for action, phrases in DEFAULT_PHRASES.items()},
        "scenes": [],
    }


def clean_config(saved) -> dict:
    """Настройки из settings.json; испорченные значения — по умолчанию."""
    config = default_config()
    if not isinstance(saved, dict):
        return config
    config["enabled"] = saved.get("enabled") is True
    config["allow_reset"] = saved.get("allow_reset") is True
    config["wake_words"] = clean_phrases(saved.get("wake_words"), DEFAULT_WAKE_WORDS) or list(DEFAULT_WAKE_WORDS)
    phrases = saved.get("phrases")
    phrases = phrases if isinstance(phrases, dict) else {}
    for action in ACTIONS:
        config["phrases"][action] = clean_phrases(phrases.get(action), DEFAULT_PHRASES[action])
    scenes = saved.get("scenes")
    for item in scenes[:MAX_SCENES] if isinstance(scenes, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("scene"), str) or not item["scene"].strip():
            continue
        config["scenes"].append({"phrases": clean_phrases(item.get("phrases")), "scene": item["scene"].strip()})
    return config


def validate(config: dict) -> dict:
    """Проверка того, что прислала страница управления; VoiceCommandsError с понятным текстом."""
    for phrase in config["wake_words"]:
        if len(phrase) > MAX_PHRASE:
            raise VoiceCommandsError("Слишком длинное кодовое слово")
    if not any(words(phrase) for phrase in config["wake_words"]):
        raise VoiceCommandsError("Задайте кодовое слово")
    for phrases in config["phrases"].values():
        if len(phrases) > MAX_PHRASES or any(len(p) > MAX_PHRASE for p in phrases):
            raise VoiceCommandsError(f"У команды до {MAX_PHRASES} фраз, каждая до {MAX_PHRASE} символов")
    if len(config["scenes"]) > MAX_SCENES:
        raise VoiceCommandsError(f"Не больше {MAX_SCENES} команд для сцен")
    for item in config["scenes"]:
        if not item["scene"].strip():
            raise VoiceCommandsError("Выберите сцену OBS для команды")
        if len(item["scene"]) > MAX_SCENE_NAME:
            raise VoiceCommandsError("Слишком длинное имя сцены")
        phrases = item["phrases"]
        if len(phrases) > MAX_PHRASES or any(len(p) > MAX_PHRASE for p in phrases):
            raise VoiceCommandsError(f"У команды до {MAX_PHRASES} фраз, каждая до {MAX_PHRASE} символов")
    return clean_config(config)


def _find(seq: tuple[str, ...], part: tuple[str, ...], start: int = 0, prefix: bool = False) -> int:
    """Позиция part в seq с start или -1. prefix: слово seq может продолжать слово part
    (кодовое слово в другом падеже: «счётчику»)."""
    n = len(part)
    for i in range(start, len(seq) - n + 1):
        if all(seq[i + k].startswith(w) if prefix else seq[i + k] == w for k, w in enumerate(part)):
            return i
    return -1


def match(text: str, config: dict) -> dict | None:
    """Команда в тексте: {"action", "phrase"[, "scene"]} или None.

    Ищется кодовое слово, затем через не больше MAX_GAP_WORDS слов — фраза команды.
    Из подходящих выигрывает та, что начинается раньше, а при равенстве — длиннее
    («плюс один» важнее «плюс»). Слова до кодового и после фразы не мешают.
    """
    said = words(text)
    candidates = [
        {"action": action, "phrase": phrase}
        for action in ACTIONS
        if action != "reset" or config["allow_reset"]
        for phrase in config["phrases"][action]
    ] + [
        {"action": SCENE, "phrase": phrase, "scene": item["scene"]}
        for item in config["scenes"]
        for phrase in item["phrases"]
    ]
    best = None  # (позиция, -длина, команда)
    for wake in config["wake_words"]:
        wake_words = words(wake)
        if not wake_words:
            continue
        at = _find(said, wake_words, prefix=True)
        while at >= 0:
            after = at + len(wake_words)
            for command in candidates:
                phrase_words = words(command["phrase"])
                pos = _find(said, phrase_words, after)
                if 0 <= pos <= after + MAX_GAP_WORDS:
                    key = (pos, -len(phrase_words))
                    if best is None or key < best[:2]:
                        best = (*key, command)
            at = _find(said, wake_words, at + 1, prefix=True)
    return best[2] if best is not None else None


class VoiceCommands:
    """Слушает распознанный текст и вызывает on_command(команда) для найденных команд."""

    def __init__(
        self,
        settings: Settings,
        on_command: Callable[[dict], Awaitable[object]] | None = None,
        cooldown: float = COOLDOWN,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.settings = settings
        self.on_command = on_command
        self.cooldown = cooldown
        self.clock = clock
        self._last_run: dict[tuple, float] = {}
        self.last: dict | None = None  # последняя сработавшая команда — для страницы управления

    def config(self) -> dict:
        return clean_config(self.settings.get(SETTING))

    def save(self, config: dict) -> dict:
        config = validate(config)
        self.settings.set(SETTING, config)
        return config

    def needs_obs(self) -> bool:
        config = self.config()
        return config["enabled"] and any(item["phrases"] for item in config["scenes"])

    async def feed(self, text: str, is_final: bool) -> dict | None:
        """Окончательная фраза → выполненная команда (или None)."""
        if not is_final or not text:
            return None
        config = self.config()
        if not config["enabled"]:
            return None
        command = match(text, config)
        if command is None:
            return None
        key = (command["action"], command.get("scene"))
        now = self.clock()
        last_run = self._last_run.get(key)
        if last_run is not None and now - last_run < self.cooldown:
            log.info("Голосовая команда %s повторилась, пропускаю", command["action"])
            return None
        self._last_run[key] = now
        log.info("Голосовая команда: %s", command["action"])
        if self.on_command is not None:
            await self.on_command(command)
        return command
