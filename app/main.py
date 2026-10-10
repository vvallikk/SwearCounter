"""Точка входа: python -m app.main"""

import argparse
import logging
import multiprocessing
import socket
import sys

import sounddevice as sd
import uvicorn

from .counter import Counter
from .paths import COUNTER_FILE, MODELS_DIR, SETTINGS_FILE, words_file
from .profanity import count_profanity, load_words
from .server import Hub, create_app
from .settings import Settings
from .stt import CATALOG, VoskRecognizer, find_model, installed_models

HOST = "127.0.0.1"
PORT = 8765  # основной порт: его адрес прописывают в OBS
PORT_ATTEMPTS = 10  # если занят, пробуем следующие: 8766, 8767, ...

log = logging.getLogger("app")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Счётчик матов для OBS")
    parser.add_argument("--device", help="номер или часть названия микрофона (по умолчанию системный)")
    parser.add_argument("--list-devices", action="store_true", help="показать устройства и выйти")
    return parser.parse_args()


def bind_socket(host: str, first_port: int, attempts: int) -> socket.socket:
    """Занимает первый свободный порт, начиная с first_port."""
    for port in range(first_port, first_port + attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, port))
        except OSError:
            sock.close()
            log.warning("Порт %d занят, пробую следующий", port)
            continue
        return sock
    sys.exit(f"Порты {first_port}–{first_port + attempts - 1} заняты, запустить сервер не удалось.")


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

    models = installed_models()
    if not models:
        sys.exit(
            f"Не найдено ни одной модели распознавания в {MODELS_DIR}\n"
            "Скачайте и распакуйте туда одну из моделей:\n"
            + "\n".join(f"  {m.title}: {m.url}" for m in CATALOG)
        )
    device = int(args.device) if args.device and args.device.isdigit() else args.device
    # Модель, выбранная на странице управления, иначе первая установленная из каталога.
    saved = settings.get("model")
    model = find_model(saved) if saved else None
    if model is None or not model.installed:
        model = models[0]
    recognizer = VoskRecognizer(on_text, model.path, settings, device=device)

    app = create_app(hub, recognizer, settings)

    # Сокет занимаем сами, а не через uvicorn: так можно перебрать порты.
    sock = bind_socket(HOST, PORT, PORT_ATTEMPTS)
    port = sock.getsockname()[1]

    print(f"Счётчик: {hub.counter.value}")
    print(f"Оверлей для OBS:     http://localhost:{port}/overlay/")
    print(f"Страница управления: http://localhost:{port}/control/")
    if port != PORT:
        print(f"ВНИМАНИЕ: порт {PORT} занят, сервер запущен на {port}.")
        print("Если в OBS прописан старый адрес оверлея, обновите его или освободите порт.")
    print("Для остановки нажмите Ctrl+C")

    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    server.run(sockets=[sock])


if __name__ == "__main__":
    # Нужно для процессов распознавания в будущем exe (PyInstaller); из исходников ничего не делает.
    multiprocessing.freeze_support()
    main()
