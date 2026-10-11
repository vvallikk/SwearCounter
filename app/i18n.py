"""Язык интерфейса: русский или английский.

Страницу управления переводит control/i18n.js, а здесь — то, что показывает сама
программа: меню трея, уведомления и окна сообщений. Язык выбирается на странице
управления и хранится в settings.json; пока не выбран, берётся язык системы.
"""

import ctypes
import os
import sys

from .settings import Settings

RU = "ru"
EN = "en"
LANGUAGES = (RU, EN)
SETTING = "ui_language"

# Языки Windows, для которых интерфейс по умолчанию русский: русский, украинский,
# белорусский, казахский (основной идентификатор языка, младшие 10 бит LANGID).
RUSSIAN_SPEAKING_LANGIDS = {0x19, 0x22, 0x23, 0x3F}
# Те же языки в macOS и Linux: начало переменной LANG вида «ru_RU.UTF-8».
RUSSIAN_SPEAKING_LOCALES = {"ru", "uk", "be", "kk"}

TITLES = {RU: "Счётчик матов", EN: "Swear Counter"}

# Русский текст (шаблон для str.format) → английский.
_EN = {
    "Открыть": "Open",
    "Пауза распознавания": "Pause recognition",
    "Скопировать адрес оверлея": "Copy overlay address",
    "Открыть в браузере": "Open in browser",
    "Проверить обновления": "Check for updates",
    "Поддержать автора": "Support the author",
    "Выход": "Quit",
    "Скрыть": "Hide",
    "Запустить счётчик матов": "Start Swear Counter",
    "Адрес оверлея скопирован: {}": "Overlay address copied: {}",
    "У вас последняя версия: v{}": "You have the latest version: v{}",
    "Не удалось проверить обновления": "Couldn't check for updates",
    "Нужно обязательное обновление до v{}: без него программа не работает.":
        "A required update to v{} is available: the program doesn't work without it.",
    "Доступна версия v{}. Установить — на странице управления.":
        "Version v{} is available. Install it on the control page.",
    "Счётчик матов запущен и работает в трее. Нажмите на значок, чтобы открыть окно.":
        "Swear Counter is running in the tray. Click the icon to open the window.",
    "Счётчик матов уже запущен: его значок — в области уведомлений.":
        "Swear Counter is already running: its icon is in the notification area.",
    "Порт {} занят, сервер запущен на {}. Если в OBS прописан старый адрес оверлея, "
    "обновите его или освободите порт.":
        "Port {} is busy, the server is running on {}. If OBS has the old overlay address, "
        "update it or free the port.",
    "OBS запущен. Нажмите, чтобы запустить счётчик матов.": "OBS is running. Click to start Swear Counter.",
    "Трансляция началась, а счётчик матов не запущен. Нажмите, чтобы запустить.":
        "The stream has started, but Swear Counter isn't running. Click to start it.",
}


def system_language() -> str:
    if sys.platform != "win32":
        locale = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
        # Без переменных (например, программа запущена не из терминала) — русский, как раньше.
        if not locale or locale in ("C", "POSIX") or locale.startswith("C."):
            return RU
        return RU if locale.split("_")[0].split(".")[0].lower() in RUSSIAN_SPEAKING_LOCALES else EN
    try:
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return RU
    return RU if langid & 0x3FF in RUSSIAN_SPEAKING_LANGIDS else EN


def language(settings: Settings) -> str:
    """Выбранный на странице управления язык, а пока не выбран — язык системы."""
    chosen = settings.get(SETTING)
    return chosen if chosen in LANGUAGES else system_language()


def tr(text: str, lang: str) -> str:
    """Перевод русского текста; без перевода в словаре остаётся русский."""
    return _EN.get(text, text) if lang == EN else text


def title(lang: str) -> str:
    return TITLES.get(lang, TITLES[RU])
