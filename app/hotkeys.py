"""Глобальные горячие клавиши: «+1», «Сбросить» и пауза, даже когда окно свёрнуто.

Сочетания регистрируются через RegisterHotKey: Windows сообщает только о нажатии
выбранных сочетаний, программа не перехватывает остальную клавиатуру.
Сочетание хранится строкой вида "Ctrl+Shift+F9"; пустая строка — клавиша не задана.
"""

import ctypes
import logging
import os
import threading
from collections.abc import Callable
from ctypes import wintypes

log = logging.getLogger(__name__)

ACTIONS = ("increment", "pause", "reset")
# Сброс по умолчанию без клавиши: случайное нажатие стёрло бы счёт.
DEFAULTS = {"increment": "Ctrl+Shift+F9", "pause": "Ctrl+Shift+F10", "reset": ""}

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
MODIFIERS = {"Ctrl": MOD_CONTROL, "Alt": MOD_ALT, "Shift": MOD_SHIFT, "Win": MOD_WIN}

KEYS: dict[str, int] = {
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    **{f"F{n}": 0x6F + n for n in range(1, 25)},
    **{f"Num{d}": 0x60 + d for d in range(10)},
    "NumMultiply": 0x6A, "NumAdd": 0x6B, "NumSubtract": 0x6D, "NumDecimal": 0x6E, "NumDivide": 0x6F,
    "Space": 0x20, "PageUp": 0x21, "PageDown": 0x22, "End": 0x23, "Home": 0x24,
    "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28, "Insert": 0x2D, "Delete": 0x2E,
    "Pause": 0x13, "Minus": 0xBD, "Equal": 0xBB, "Backquote": 0xC0,
}
# Эти клавиши можно назначить без Ctrl/Alt/Shift/Win: при наборе текста их не жмут.
SOLO_KEYS = {name for name in KEYS if name.startswith(("F", "Num"))} | {"Pause"}


class HotkeyError(ValueError):
    pass


def parse(combo: str) -> tuple[int, int] | None:
    """"Ctrl+Shift+F9" → (модификаторы, код клавиши); пустая строка → None."""
    if not combo:
        return None
    *mods, key = combo.split("+")
    if key not in KEYS:
        raise HotkeyError(f"Неизвестная клавиша: {key or combo}")
    flags = 0
    for mod in mods:
        if mod not in MODIFIERS or flags & MODIFIERS[mod]:
            raise HotkeyError(f"Неверное сочетание: {combo}")
        flags |= MODIFIERS[mod]
    if not flags and key not in SOLO_KEYS:
        raise HotkeyError("Добавьте Ctrl, Alt, Shift или Win: без них клавиша мешала бы печатать")
    return flags, KEYS[key]


def normalize(combos: dict) -> dict[str, str]:
    """Сочетания для всех действий: неизвестные действия отбрасываются, недостающие — по умолчанию."""
    return {action: str(combos.get(action, DEFAULTS[action]) or "") for action in ACTIONS}


class Hotkeys:
    """Поток с очередью сообщений Windows: регистрирует сочетания и ждёт нажатий.

    on_press(action) вызывается из этого потока.
    """

    WM_HOTKEY, WM_QUIT, WM_APP = 0x0312, 0x0012, 0x8000
    APPLY_TIMEOUT = 5.0

    def __init__(self, on_press: Callable[[str], None]):
        self.on_press = on_press
        self.available = os.name == "nt"
        self.failed: list[str] = []  # действия, чьё сочетание занято другой программой
        self._wanted: dict[str, str] = {}
        self._applied = threading.Event()
        self._ready = threading.Event()
        self._thread_id = 0
        self._thread: threading.Thread | None = None

    def start(self, combos: dict[str, str]) -> None:
        if not self.available:
            return
        self._wanted = dict(combos)
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(self.APPLY_TIMEOUT)

    def apply(self, combos: dict[str, str]) -> list[str]:
        """Перерегистрирует сочетания; возвращает действия, которые не удалось зарегистрировать."""
        if self._thread is None or not self._thread.is_alive():
            return []
        self._wanted = dict(combos)
        self._applied.clear()
        ctypes.windll.user32.PostThreadMessageW(self._thread_id, self.WM_APP, 0, 0)
        self._applied.wait(self.APPLY_TIMEOUT)
        return self.failed

    def stop(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)
            self._thread.join(self.APPLY_TIMEOUT)

    def _register(self, user32) -> None:
        for index in range(len(ACTIONS)):
            user32.UnregisterHotKey(None, index + 1)
        failed = []
        for index, action in enumerate(ACTIONS):
            try:
                parsed = parse(self._wanted.get(action, ""))
            except HotkeyError:
                parsed = None
            if parsed is None:
                continue
            mods, vk = parsed
            if not user32.RegisterHotKey(None, index + 1, mods | MOD_NOREPEAT, vk):
                log.warning("Сочетание %s для %s занято другой программой", self._wanted[action], action)
                failed.append(action)
        self.failed = failed
        self._applied.set()

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        # PeekMessage создаёт очередь сообщений потока: до этого PostThreadMessage не дойдёт.
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self._register(user32)
        self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_APP:
                    self._register(user32)
                elif msg.message == self.WM_HOTKEY and 1 <= msg.wParam <= len(ACTIONS):
                    action = ACTIONS[msg.wParam - 1]
                    try:
                        self.on_press(action)
                    except Exception:
                        log.exception("Ошибка горячей клавиши %s", action)
        finally:
            for index in range(len(ACTIONS)):
                user32.UnregisterHotKey(None, index + 1)
