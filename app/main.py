"""Точка входа: python -m app.main"""

import argparse
import logging
import multiprocessing
import socket
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

import sounddevice as sd
import uvicorn
from fastapi import FastAPI

from . import __version__
from .counter import Counter
from .paths import COUNTER_FILE, LOG_FILE, SETTINGS_FILE, SOUNDS_DIR, words_file
from .profanity import count_profanity, load_words
from .server import Hub, create_app
from .settings import Settings
from .sound import Sound
from .stt import CATALOG, VoskRecognizer, find_model, installed_models

HOST = "127.0.0.1"
PORT = 8765  # основной порт: его адрес прописывают в OBS
PORT_ATTEMPTS = 10  # если занят, пробуем следующие: 8766, 8767, ...
LOG_FORMAT = "%(asctime)s  %(message)s"
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUPS = 2

log = logging.getLogger("app")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Счётчик матов для OBS")
    parser.add_argument("--device", help="номер или часть названия микрофона (по умолчанию системный)")
    parser.add_argument("--list-devices", action="store_true", help="показать устройства и выйти")
    parser.add_argument("--console", action="store_true", help="без окна: адреса и лог в консоли (для разработки)")
    return parser.parse_args(argv)


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


def setup_logging(log_file: Path | None) -> None:
    """Лог в консоль (если она есть) и, для оконного режима, в файл рядом с exe."""
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    if log_file is not None:
        handlers.append(
            RotatingFileHandler(log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
        )
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%H:%M:%S", handlers=handlers, force=True)


@dataclass
class Prepared:
    app: FastAPI
    sock: socket.socket
    count: int
    model_missing: bool

    @property
    def port(self) -> int:
        return self.sock.getsockname()[1]

    @property
    def port_notice(self) -> str | None:
        """Предупреждение, если основной порт занят и адрес оверлея в OBS устарел."""
        if self.port == PORT:
            return None
        return (
            f"Порт {PORT} занят, сервер запущен на {self.port}. Если в OBS прописан старый "
            "адрес оверлея, обновите его или освободите порт."
        )


def prepare(args: argparse.Namespace) -> Prepared:
    """Собирает приложение и занимает порт; сервер ещё не запущен."""
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
    return Prepared(app, sock, hub.counter.value, model_missing=model is None)


def run_console(prepared: Prepared) -> None:
    port = prepared.port
    print(f"Счётчик матов {__version__}")
    print(f"Счётчик: {prepared.count}")
    print(f"Оверлей для OBS:     http://localhost:{port}/overlay/")
    print(f"Страница управления: http://localhost:{port}/control/")
    if prepared.port_notice:
        print(f"ВНИМАНИЕ: {prepared.port_notice}")
    if prepared.model_missing:
        print("Модель распознавания ещё не скачана: выберите её на странице управления.")
    print("Для остановки нажмите Ctrl+C")

    server = uvicorn.Server(uvicorn.Config(prepared.app, log_level="warning"))
    server.run(sockets=[prepared.sock])


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.list_devices:
        print(sd.query_devices())
        return

    # Без консоли (exe из проводника) --console бессмысленен: печатать некуда.
    if args.console and sys.stdout is not None:
        setup_logging(None)
        run_console(prepare(args))
        return

    from . import desktop

    setup_logging(LOG_FILE)
    with desktop.single_instance() as first:
        if not first:
            desktop.message_box("Счётчик матов уже запущен: его значок — в области уведомлений.")
            return
        prepared = prepare(args)
        log.info("Счётчик матов %s, порт %d", __version__, prepared.port)
        desktop.run(prepared.app, prepared.sock, notice=prepared.port_notice)


if __name__ == "__main__":
    # Нужно для процессов распознавания в будущем exe (PyInstaller); из исходников ничего не делает.
    multiprocessing.freeze_support()
    main()
