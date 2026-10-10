# Сборка exe: python scripts/build.py (он вызывает PyInstaller с этим файлом).
# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

a = Analysis(
    ["swearcounter.py"],
    pathex=[],
    # libvosk.dll и её зависимости лежат в пакете vosk; PyInstaller сам их не находит.
    binaries=collect_dynamic_libs("vosk"),
    # Ресурсы только для чтения; изменяемые файлы (words.txt, models, sounds, настройки)
    # лежат рядом с exe — см. app/paths.py.
    datas=[("overlay", "overlay"), ("control", "control"), ("words.txt", ".")],
    # uvicorn выбирает реализации протоколов по строкам, их импорты не видны статически.
    hiddenimports=collect_submodules("uvicorn"),
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
    # Окно консоли нужно: в нём адреса оверлея и страницы управления, лог и Ctrl+C.
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="SwearCounter")
