"""Заглушка распознавателя: подаёт тестовые фразы без микрофона."""

import asyncio
import itertools

from .base import OnText, Recognizer

# Часть фраз содержит тестовые корни из words.txt, часть — нет.
PHRASES = [
    "привет всем, начинаем стрим",
    "ой, тестслово вырвалось",
    "сегодня играем во что-нибудь новое",
    "Проверка связи, проверка",
    "ТЕСТСЛОВО, тестслова и ещё тестсловечко",
    "ну всё, идём дальше",
]


class FakeRecognizer(Recognizer):
    def __init__(self, on_text: OnText, interval: float = 5.0):
        super().__init__(on_text)
        self.interval = interval

    async def run(self) -> None:
        for phrase in itertools.cycle(PHRASES):
            await asyncio.sleep(self.interval)
            # Как у настоящего распознавателя: сначала промежуточный результат, затем итоговый.
            half = phrase[: len(phrase) // 2]
            await self.on_text(half, False)
            await self.on_text(phrase, True)
