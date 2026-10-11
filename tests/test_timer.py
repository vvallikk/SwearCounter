"""Таймер «без мата»: выдержка, рекорд, пауза и рассылка клиентам."""

import asyncio

from app.server import Hub
from app.timer import NoSwearTimer


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_timer():
    clock = Clock()
    return clock, NoSwearTimer(clock)


def test_counts_from_start():
    clock, timer = make_timer()
    clock.now += 42
    assert timer.elapsed() == 42
    assert timer.running
    assert timer.record == 0


def test_hit_restarts_and_keeps_best_streak():
    clock, timer = make_timer()
    clock.now += 60
    timer.hit()
    assert timer.elapsed() == 0
    assert timer.record == 60
    clock.now += 10
    timer.hit()
    assert timer.record == 60  # короткая серия рекорд не портит
    clock.now += 90
    timer.hit()
    assert timer.record == 90


def test_reset_starts_new_session():
    clock, timer = make_timer()
    clock.now += 60
    timer.hit()
    clock.now += 5
    timer.reset()
    assert timer.record == 0
    assert timer.elapsed() == 0


def test_pause_freezes_time():
    clock, timer = make_timer()
    clock.now += 30
    timer.pause()
    clock.now += 600  # перерыв не засчитывается
    assert timer.elapsed() == 30
    assert not timer.running
    timer.resume()
    clock.now += 5
    assert timer.elapsed() == 35


def test_pause_and_resume_are_idempotent():
    clock, timer = make_timer()
    clock.now += 10
    timer.pause()
    timer.pause()
    clock.now += 10
    timer.resume()
    timer.resume()
    clock.now += 10
    assert timer.elapsed() == 20


def test_hit_while_paused_stays_paused():
    clock, timer = make_timer()
    clock.now += 20
    timer.pause()
    timer.hit()  # «+1» кнопкой на паузе
    clock.now += 100
    assert timer.elapsed() == 0
    assert timer.record == 20
    assert not timer.running


def test_message_rounds_seconds():
    clock, timer = make_timer()
    clock.now += 12.345
    assert timer.message() == {"type": "timer", "elapsed": 12.3, "record": 0.0, "running": True}


# --- в связке с сервером ---


def test_hub_updates_timer(counter):
    clock = Clock()
    hub = Hub(counter)
    hub.timer = NoSwearTimer(clock)
    clock.now += 50
    asyncio.run(hub.increment(1))
    assert hub.timer.record == 50
    assert hub.timer.elapsed() == 0
    asyncio.run(hub.set_paused(True))
    assert not hub.timer.running
    asyncio.run(hub.reset())
    assert hub.timer.record == 0


def test_locked_increment_does_not_touch_timer(counter):
    clock = Clock()
    hub = Hub(counter)
    hub.timer = NoSwearTimer(clock)
    hub.locked = lambda: True
    clock.now += 50
    asyncio.run(hub.increment(1))
    assert hub.timer.elapsed() == 50


def test_speech_on_pause_does_not_touch_timer(counter):
    clock = Clock()
    hub = Hub(counter)
    hub.timer = NoSwearTimer(clock)
    clock.now += 50
    asyncio.run(hub.set_paused(True))
    asyncio.run(hub.increment(1, speech=True))
    assert hub.timer.elapsed() == 50

