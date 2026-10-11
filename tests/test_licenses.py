"""Файл лицензий для сборки: все зависимости из requirements.txt и сторонние компоненты."""

from scripts.licenses import build_notices, runtime_distributions


def test_runtime_distributions_include_dependencies():
    names = {d.metadata["Name"].lower() for d in runtime_distributions()}
    # Прямые зависимости и транзитивные (starlette — через fastapi).
    assert {"fastapi", "pystray", "vosk", "pywebview", "starlette"} <= names
    # Инструменты разработки и сборки в exe не попадают.
    assert not {"pytest", "pyinstaller"} & names


def test_notices_contain_license_texts():
    text = build_notices()
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text  # pystray
    assert "Apache License" in text  # Vosk
    assert "PortAudio" in text
