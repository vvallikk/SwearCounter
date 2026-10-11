# Сборка exe: python scripts/build.py (он вызывает PyInstaller с этим файлом).
# -*- mode: python ; coding: utf-8 -*-

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

VERSION = re.search(r'__version__ = "(.+?)"', Path("app/__init__.py").read_text(encoding="utf-8"))[1]
_numbers = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:3])
_numbers += (0,) * (4 - len(_numbers))

# Ресурс версии: из FileDescription Windows берёт заголовок уведомлений в трее
# (без него там было бы «SwearCounter.exe»).
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_numbers, prodvers=_numbers),
    kids=[
        StringFileInfo([
            StringTable("041904B0", [
                StringStruct("FileDescription", "Счётчик матов"),
                StringStruct("ProductName", "Счётчик матов"),
                StringStruct("FileVersion", VERSION),
                StringStruct("ProductVersion", VERSION),
                StringStruct("InternalName", "SwearCounter"),
                StringStruct("OriginalFilename", "SwearCounter.exe"),
            ])
        ]),
        VarFileInfo([VarStruct("Translation", [0x0419, 1200])]),
    ],
)

a = Analysis(
    ["swearcounter.py"],
    pathex=[],
    # libvosk.dll, onnxruntime.dll и библиотеки sherpa-onnx лежат внутри пакетов;
    # PyInstaller сам их не находит.
    binaries=collect_dynamic_libs("vosk") + collect_dynamic_libs("sherpa_onnx"),
    # Ресурсы только для чтения; изменяемые файлы (wordlists, models, sounds, настройки)
    # лежат рядом с exe — см. app/paths.py.
    datas=[("overlay", "overlay"), ("control", "control"), ("assets", "assets"), ("wordlists", "wordlists")],
    # uvicorn выбирает реализации протоколов по строкам, их импорты не видны статически.
    hiddenimports=collect_submodules("uvicorn") + ["webview.platforms.winforms", "webview.platforms.edgechromium", "pystray._win32"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SwearCounter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Без консоли: интерфейс — окно и значок в трее (app/desktop.py), лог — в swearcounter.log.
    console=False,
    icon="assets/icon.ico",
    version=version_info,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="SwearCounter")
