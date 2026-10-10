"""Точка входа: python -m app.main"""

import argparse
import logging
import multiprocessing
import socket
import sys

import sounddevice as sd
import uvicorn

from . import __version__
from .counter import Counter
from .paths import COUNTER_FILE, SETTINGS_FILE, SOUNDS_DIR, words_file
from .profanity import count_profanity, load_words
from .server import Hub, create_app
from .settings import Settings
from .sound import Sound
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


def _busy_on_any_interface(port: int) -> bool:
    """Занят ли порт хоть на каком-то адресе.

    Windows разрешает занять 127.0.0.1:порт, даже если другая программа слушает
    этот порт на всех адресах (0.0.0.0) — и запросы ушли бы не туда. Поэтому
    сначала пробуем исключительно занять порт на всех адресах и сразу отпускаем.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("0.0.0.0", port))
        except OSError:
            return True
    return False


def bind_socket(host: str, first_port: int, attempts: int) -> socket.socket:
    """Занимает первый свободный порт, начиная с first_port."""
    for port in range(first_port, first_port + attempts):
        if _busy_on_any_interface(port):
            log.warning("Порт %d занят, пробую следующий", port)
            continue
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
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

    # Микрофон: ключ --device, иначе выбранный на странице управления, иначе системный.
    if args.device:
        device = int(args.device) if args.device.isdigit() else args.device
    else:
        device = settings.get("device")
    # Модель, выбранная на странице управления, иначе первая установленная из каталога.
    # Если не скачано ни одной, сервер всё равно запускается: модель скачается
    # по клику на странице управления.
    saved = settings.get("model")
    model = find_model(saved) if saved else None
    if model is None or not model.installed:
        models = installed_models()
        model = models[0] if models else None
    async def on_level(level: float) -> None:
        # Для индикатора громкости на странице управления; оверлей это сообщение пропускает.
        await hub.broadcast({"type": "mic_level", "level": round(level, 3)})

    recognizer = VoskRecognizer(
        on_text, (model or CATALOG[0]).path, settings, device=device, on_level=on_level
    )

    app = create_app(hub, recognizer, settings, Sound(settings, SOUNDS_DIR))

    # Сокет занимаем сами, а не через uvicorn: так можно перебрать порты.
    sock = bind_socket(HOST, PORT, PORT_ATTEMPTS)
    port = sock.getsockname()[1]

    print(f"Счётчик матов {__version__}")
    print(f"Счётчик: {hub.counter.value}")
    print(f"Оверлей для OBS:     http://localhost:{port}/overlay/")
    print(f"Страница управления: http://localhost:{port}/control/")
    if port != PORT:
        print(f"ВНИМАНИЕ: порт {PORT} занят, сервер запущен на {port}.")
        print("Если в OBS прописан старый адрес оверлея, обновите его или освободите порт.")
    if model is None:
        print("Модель распознавания ещё не скачана: выберите её на странице управления.")
    print("Для остановки нажмите Ctrl+C")

    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    server.run(sockets=[sock])


if __name__ == "__main__":
    # Нужно для процессов распознавания в будущем exe (PyInstaller); из исходников ничего не делает.
    multiprocessing.freeze_support()
    main()
