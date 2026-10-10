"""Точка входа: python -m app.main"""

import argparse
import logging
import multiprocessing
import sys

import sounddevice as sd
import uvicorn

from .counter import Counter
from .paths import COUNTER_FILE, MODELS_DIR, SETTINGS_FILE, words_file
from .profanity import count_profanity, load_words
from .server import Hub, create_app
from .settings import Settings
from .stt import VoskRecognizer

HOST = "127.0.0.1"
PORT = 8765

log = logging.getLogger("app")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Счётчик матов для OBS")
    parser.add_argument("--device", help="номер или часть названия микрофона (по умолчанию системный)")
    parser.add_argument("--list-devices", action="store_true", help="показать устройства и выйти")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.list_devices:
        print(sd.query_devices())
        return

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

    load_words(words_file())
    hub = Hub(Counter(COUNTER_FILE))
    settings = Settings(SETTINGS_FILE)

    async def on_text(text: str, is_final: bool) -> None:
        if not is_final:
            return
        found = count_profanity(text)
        log.info("Распознано: %r, найдено: %d", text, found)
        if found > 0:
            count = await hub.increment(found)
            log.info("Счётчик: %d", count)

    # Распакованные модели Vosk, маленькие первыми.
    models = sorted(
        (p for p in MODELS_DIR.glob("vosk-model-*") if p.is_dir()),
        key=lambda p: ("small" not in p.name, p.name),
    )
    if not models:
        sys.exit(
            f"Не найдена модель Vosk в {MODELS_DIR}\n"
            "Скачайте русскую модель с https://alphacephei.com/vosk/models и распакуйте\n"
            "в эту папку, например models/vosk-model-small-ru-0.22."
        )
    device = int(args.device) if args.device and args.device.isdigit() else args.device
    recognizer = VoskRecognizer(on_text, models[0], settings, device=device)

    app = create_app(hub, recognizer)

    print(f"Счётчик: {hub.counter.value}")
    print(f"Оверлей для OBS:     http://localhost:{PORT}/overlay/")
    print(f"Страница управления: http://localhost:{PORT}/control/")
    print("Для остановки нажмите Ctrl+C")

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    # Нужно для процессов распознавания в будущем exe (PyInstaller); из исходников ничего не делает.
    multiprocessing.freeze_support()
    main()
