"""FastAPI-приложение: API, WebSocket для оверлеев и статика."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .counter import Counter
from .paths import CONTROL_DIR, OVERLAY_DIR
from .stt import Recognizer

log = logging.getLogger(__name__)


class Hub:
    """Счётчик плюс список подключённых WebSocket-клиентов."""

    def __init__(self, counter: Counter):
        self.counter = counter
        self.clients: set[WebSocket] = set()
        # Общий замок: изменение счёта и рассылка идут строго по очереди,
        # чтобы клиенты получали события в правильном порядке.
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        async with self._lock:
            await ws.send_json({"type": "state", "count": self.counter.value})
            self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def increment(self, delta: int = 1) -> int:
        async with self._lock:
            count = await self.counter.add(delta)
            await self._broadcast({"type": "increment", "count": count, "delta": delta})
            return count

    async def reset(self) -> int:
        async with self._lock:
            count = await self.counter.reset()
            await self._broadcast({"type": "state", "count": count})
            return count

    async def _broadcast(self, message: dict) -> None:
        clients = list(self.clients)
        results = await asyncio.gather(
            *(ws.send_json(message) for ws in clients), return_exceptions=True
        )
        # Клиенты, которым не удалось отправить, считаются отключёнными.
        for ws, result in zip(clients, results):
            if isinstance(result, Exception):
                self.clients.discard(ws)


def create_app(hub: Hub, recognizer: Recognizer | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if recognizer is not None:
            await recognizer.start()
        try:
            yield
        finally:
            if recognizer is not None:
                await recognizer.stop()

    app = FastAPI(title="Счётчик матов", lifespan=lifespan)

    @app.get("/")
    async def root():
        return RedirectResponse("/control/")

    @app.get("/api/state")
    async def get_state():
        return {"count": hub.counter.value}

    @app.post("/api/increment")
    async def post_increment():
        return {"count": await hub.increment(1)}

    @app.post("/api/reset")
    async def post_reset():
        return {"count": await hub.reset()}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        try:
            await hub.connect(ws)
            log.info("Клиент подключён, всего: %d", len(hub.clients))
            # Клиенты ничего не присылают; читаем только чтобы заметить отключение.
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(ws)
            log.info("Клиент отключён, всего: %d", len(hub.clients))

    app.mount("/overlay", StaticFiles(directory=OVERLAY_DIR, html=True), name="overlay")
    app.mount("/control", StaticFiles(directory=CONTROL_DIR, html=True), name="control")
    return app
