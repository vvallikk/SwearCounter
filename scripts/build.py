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

DIST = ROOT / "dist"
APP_DIR = DIST / "SwearCounter"
ARCHIVE = DIST / f"SwearCounter-v{__version__}-windows"

MODELS_README = """Здесь хранятся модели распознавания речи Vosk.

Обычно ничего делать не нужно: нажмите на модель на странице управления,
и программа сама скачает её сюда.

Вручную: распакуйте архив так, чтобы получилось
  models/vosk-model-small-ru-0.22/am, conf, graph, ...

Маленькая модель (45 МБ, быстрая):
  https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
Большая модель (1.8 ГБ, точнее, нужно ~5.5 ГБ памяти):
  https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip

Можно положить обе и переключаться между ними на странице управления.
"""


def main() -> None:
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "SwearCounter.spec"],
        cwd=ROOT,
        check=True,
    )
    # Файлы, которые стример меняет сам, кладём рядом с exe (см. app/paths.py).
    shutil.copy2(ROOT / "words.txt", APP_DIR / "words.txt")
    shutil.copy2(ROOT / "README.md", APP_DIR / "README.md")
    models = APP_DIR / "models"
    models.mkdir(exist_ok=True)
    (models / "README.txt").write_text(MODELS_README, encoding="utf-8")

    archive = shutil.make_archive(str(ARCHIVE), "zip", root_dir=DIST, base_dir=APP_DIR.name)
    size_mb = Path(archive).stat().st_size / 1024 / 1024
    print(f"Готово: {APP_DIR}\nАрхив:  {archive} ({size_mb:.1f} МБ)")


if __name__ == "__main__":
    main()
