"""Сборка релиза: папка dist/SwearCounter с exe и zip-архив для GitHub Release.

Запуск из корня проекта:  .venv\\Scripts\\python.exe scripts/build.py
Нужен PyInstaller:         .venv\\Scripts\\python.exe -m pip install -r requirements-build.txt
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import __version__  # noqa: E402
from scripts.licenses import build_notices  # noqa: E402

DIST = ROOT / "dist"
APP_DIR = DIST / "SwearCounter"
ARCHIVE = DIST / f"SwearCounter-v{__version__}-windows"

MODELS_README = """Здесь хранятся модели распознавания речи.

Обычно ничего делать не нужно: нажмите на модель на странице управления,
и программа сама скачает её сюда. Можно скачать несколько моделей
и переключаться между ними там же.

Модели из одного архива можно поставить и вручную: распакуйте архив так,
чтобы получилось, например, models/vosk-model-small-ru-0.22/am, conf, graph, ...

Маленькая, Vosk (45 МБ, ~0.3 ГБ памяти):
  https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
Компактная, Vosk Streaming small (24 МБ, ~0.15 ГБ памяти):
  https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-small-ru-vosk-int8-2025-08-16.tar.bz2
Разговорная, T-one (128 МБ, ~0.5 ГБ памяти):
  https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-t-one-russian-2025-09-08.tar.bz2
Большая, Vosk (1.8 ГБ, ~5.5 ГБ памяти):
  https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip

Средняя (Vosk Streaming) и Точная (GigaAM) состоят из нескольких файлов:
их проще скачать кнопкой на странице управления.
"""


def main() -> None:
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "SwearCounter.spec"],
        cwd=ROOT,
        check=True,
    )
    # Файлы, которые пользователь меняет сам, кладём рядом с exe (см. app/paths.py).
    # Списки слов программа и сама разложит при первом запуске, но так их видно сразу.
    shutil.copytree(ROOT / "wordlists", APP_DIR / "wordlists", dirs_exist_ok=True)
    shutil.copy2(ROOT / "README.md", APP_DIR / "README.md")
    # Лицензия программы и лицензии всего стороннего, что вошло в сборку.
    shutil.copy2(ROOT / "LICENSE", APP_DIR / "LICENSE.txt")
    (APP_DIR / "THIRD_PARTY_LICENSES.txt").write_text(build_notices(), encoding="utf-8")
    models = APP_DIR / "models"
    models.mkdir(exist_ok=True)
    (models / "README.txt").write_text(MODELS_README, encoding="utf-8")

    archive = shutil.make_archive(str(ARCHIVE), "zip", root_dir=DIST, base_dir=APP_DIR.name)
    size_mb = Path(archive).stat().st_size / 1024 / 1024
    print(f"Готово: {APP_DIR}\nАрхив:  {archive} ({size_mb:.1f} МБ)")


if __name__ == "__main__":
    main()
