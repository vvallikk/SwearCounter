"""Пути к файлам приложения.

Работают одинаково из исходников и из папки, собранной PyInstaller,
и не зависят от текущей рабочей директории.
"""

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # Собранный exe: ресурсы (overlay, control) PyInstaller кладёт в sys._MEIPASS,
    # а изменяемые файлы (counter.json, wordlists) храним рядом с exe.
    DATA_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", DATA_DIR))
else:
    # Запуск из исходников: всё лежит в корне проекта.
    DATA_DIR = RESOURCE_DIR = Path(__file__).resolve().parent.parent

OVERLAY_DIR = RESOURCE_DIR / "overlay"
CONTROL_DIR = RESOURCE_DIR / "control"
COUNTER_FILE = DATA_DIR / "counter.json"
# Списки слов: встроенные копируются рядом с exe, чтобы пользователь мог их править
# и добавлять свои (см. app/wordlists.py). Из исходников это одна и та же папка.
BUNDLED_WORDLISTS_DIR = RESOURCE_DIR / "wordlists"
WORDLISTS_DIR = DATA_DIR / "wordlists"
OLD_WORDS_FILE = DATA_DIR / "words.txt"  # единственный список версий до 0.3.0


SETTINGS_FILE = DATA_DIR / "settings.json"
SOUNDS_DIR = DATA_DIR / "sounds"  # свой звук оповещения, загруженный со страницы управления
PRESETS_DIR = DATA_DIR / "presets"  # личные оформления из zip-наборов (app/custom_presets.py)
MODELS_DIR = DATA_DIR / "models"
LOG_FILE = DATA_DIR / "swearcounter.log"
WEBVIEW_DIR = DATA_DIR / "webview"  # данные окна приложения (localStorage страницы управления)
ICON_FILE = RESOURCE_DIR / "assets" / "icon.png"
