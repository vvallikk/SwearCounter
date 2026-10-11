"""Пути к файлам приложения.

Работают одинаково из исходников и из папки, собранной PyInstaller,
и не зависят от текущей рабочей директории.
"""

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # Собранный exe: ресурсы (overlay, control) PyInstaller кладёт в sys._MEIPASS,
    # а изменяемые файлы (counter.json, words.txt) храним рядом с exe.
    DATA_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", DATA_DIR))
else:
    # Запуск из исходников: всё лежит в корне проекта.
    DATA_DIR = RESOURCE_DIR = Path(__file__).resolve().parent.parent

OVERLAY_DIR = RESOURCE_DIR / "overlay"
CONTROL_DIR = RESOURCE_DIR / "control"
COUNTER_FILE = DATA_DIR / "counter.json"


def words_file() -> Path:
    """words.txt рядом с exe (чтобы пользователь мог его править), иначе встроенный."""
    path = DATA_DIR / "words.txt"
    return path if path.exists() else RESOURCE_DIR / "words.txt"


SETTINGS_FILE = DATA_DIR / "settings.json"
SOUNDS_DIR = DATA_DIR / "sounds"  # свой звук оповещения, загруженный со страницы управления
MODELS_DIR = DATA_DIR / "models"
LOG_FILE = DATA_DIR / "swearcounter.log"
WEBVIEW_DIR = DATA_DIR / "webview"  # данные окна приложения (localStorage страницы управления)
ICON_FILE = RESOURCE_DIR / "assets" / "icon.png"
