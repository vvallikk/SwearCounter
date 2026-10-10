"""Точка входа: python -m app.main"""

import logging

import uvicorn

from .counter import Counter
from .paths import COUNTER_FILE, words_file
from .profanity import count_profanity, load_words
from .server import Hub, create_app
from .stt import FakeRecognizer

HOST = "127.0.0.1"
PORT = 8765
FAKE_INTERVAL = 5.0  # секунд между фразами заглушки

log = logging.getLogger("app")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

    load_words(words_file())
    hub = Hub(Counter(COUNTER_FILE))

    async def on_text(text: str, is_final: bool) -> None:
        if not is_final:
            return
        found = count_profanity(text)
        log.info("Распознано: %r, найдено: %d", text, found)
        if found > 0:
            count = await hub.increment(found)
            log.info("Счётчик: %d", count)

    app = create_app(hub, FakeRecognizer(on_text, interval=FAKE_INTERVAL))

    print(f"Счётчик: {hub.counter.value}")
    print(f"Оверлей для OBS:     http://localhost:{PORT}/overlay/")
    print(f"Страница управления: http://localhost:{PORT}/control/")
    print("Для остановки нажмите Ctrl+C")

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
