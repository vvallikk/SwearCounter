"""Смена сцены OBS по порогам счёта: до MAX_RULES правил «при N словах → сцена X»
и необязательный возврат прежней сцены через M секунд.

Правило срабатывает, когда счёт переходит через его порог; после сброса счёта (новая сессия)
каждое снова может сработать один раз. Настройки хранятся в settings.json → obs_link:
scene_rules — список {"at", "scene"}, scene_return — секунды до возврата (0 — не возвращать).
Старые scene/scene_at (одно правило) читаются как список из одного правила, а при сохранении
записываются рядом зеркалом первого правила, чтобы прежняя версия программы тоже их поняла.
"""

import asyncio
import logging
from collections.abc import Callable

from . import goals
from .obs import ObsError

log = logging.getLogger(__name__)

MAX_RULES = 5
MAX_SCENE_NAME = 256
MAX_RETURN = 3600  # час: дольше вернуть сцену проще руками


class ScenesError(ValueError):
    pass


def check_rule(at: int, scene: str) -> None:
    """Порог 0 или пустая сцена — допустимое «не заполнено»: правило хранится, но не срабатывает."""
    if not 0 <= at <= goals.MAX_VALUE:
        raise ScenesError(f"Порог — целое число от 0 до {goals.MAX_VALUE}")
    if len(scene) > MAX_SCENE_NAME:
        raise ScenesError("Слишком длинное имя сцены")


def check_options(rules: list[tuple[int, str]], return_after: int) -> None:
    if len(rules) > MAX_RULES:
        raise ScenesError(f"Правил смены сцены не больше {MAX_RULES}")
    for at, scene in rules:
        check_rule(at, scene)
    if not 0 <= return_after <= MAX_RETURN:
        raise ScenesError(f"Возврат сцены — от 0 до {MAX_RETURN} секунд")


def _clean_rule(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    at, scene = raw.get("at"), raw.get("scene")
    if not isinstance(at, int) or isinstance(at, bool) or not isinstance(scene, str):
        return None
    try:
        check_rule(at, scene)
    except ScenesError:
        return None
    return {"at": at, "scene": scene}


def saved_options(saved: dict) -> dict:
    """Правила и возврат из сохранённого obs_link; испорченное отбрасывается, старый формат — одно правило."""
    if "scene_rules" in saved:
        raw = saved["scene_rules"] if isinstance(saved["scene_rules"], list) else []
    else:
        raw = [{"at": saved.get("scene_at"), "scene": saved.get("scene")}]
    rules = [rule for rule in map(_clean_rule, raw) if rule is not None][:MAX_RULES]
    if "scene_rules" not in saved and not any(rule["at"] or rule["scene"] for rule in rules):
        rules = []  # старое «сцену не переключать»
    back = saved.get("scene_return")
    back = back if isinstance(back, int) and not isinstance(back, bool) and 0 <= back <= MAX_RETURN else 0
    return {"scene_rules": rules, "scene_return": back, **legacy_fields(rules)}


def legacy_fields(rules: list[dict]) -> dict:
    """Прежние поля scene/scene_at: первое правило — для старых скриптов и старой версии программы."""
    first = rules[0] if rules else {"at": 0, "scene": ""}
    return {"scene": first["scene"], "scene_at": first["at"]}


def active(rules: list[dict]) -> list[dict]:
    return [rule for rule in rules if rule["at"] > 0 and rule["scene"]]


def crossed_scene(rules: list[dict], before: int, count: int) -> str | None:
    """Сцена правила, чей порог счёт только что перешёл; перешёл сразу несколько — самого старшего."""
    hit = [rule for rule in active(rules) if before < rule["at"] <= count]
    return max(hit, key=lambda rule: rule["at"])["scene"] if hit else None


def current_scene(data: dict) -> str | None:
    """Имя текущей сцены из ответа GetCurrentProgramScene (поле переименовано в obs-websocket 5.3)."""
    name = data.get("sceneName") or data.get("currentProgramSceneName")
    return name if isinstance(name, str) and name else None


class SceneSwitcher:
    """Переключает сцены через request(тип, данные) — синхронный запрос к OBS (ObsLink.request).

    Перед первым переключением запоминает текущую сцену и через return_after секунд
    возвращает её. Если до возврата сработало следующее правило, возврат откладывается
    и ведёт всё равно к сцене, что была до первого переключения. Если за это время
    сцену сменили руками, возврата нет. second — длина секунды (в тестах короче).
    """

    def __init__(self, request: Callable[[str, dict | None], dict], second: float = 1.0):
        self._request = request
        self.second = second
        self._lock = asyncio.Lock()
        self._return_task: asyncio.Task | None = None
        self._previous: str | None = None  # куда вернуться

    async def _call(self, request_type: str, data: dict | None = None) -> dict:
        return await asyncio.to_thread(self._request, request_type, data)

    async def switch(self, name: str, return_after: int) -> None:
        async with self._lock:
            pending = self._cancel_return()
            if return_after > 0 and not pending:
                try:
                    self._previous = current_scene(await self._call("GetCurrentProgramScene"))
                except ObsError as e:  # переключить всё равно можно, просто без возврата
                    log.warning("Не удалось узнать текущую сцену OBS: %s", e)
                    self._previous = None
            try:
                await self._call("SetCurrentProgramScene", {"sceneName": name})
                log.info("OBS: сцена переключена на %r", name)
            except ObsError as e:
                log.warning("Не удалось переключить сцену OBS: %s", e)
                return
            if return_after > 0 and self._previous and self._previous != name:
                self._return_task = asyncio.create_task(self._return_later(name, return_after * self.second))

    def _cancel_return(self) -> bool:
        """Отменяет ожидающий возврат; True — он был (прежняя сцена уже запомнена)."""
        task, self._return_task = self._return_task, None
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def _return_later(self, switched_to: str, delay: float) -> None:
        await asyncio.sleep(delay)
        async with self._lock:
            self._return_task = None
            try:
                if current_scene(await self._call("GetCurrentProgramScene")) != switched_to:
                    log.info("OBS: сцену сменили вручную, возврат на %r отменён", self._previous)
                    return
                await self._call("SetCurrentProgramScene", {"sceneName": self._previous})
                log.info("OBS: сцена возвращена на %r", self._previous)
            except ObsError as e:
                log.warning("Не удалось вернуть сцену OBS: %s", e)

    def close(self) -> None:
        self._cancel_return()
