"""Уровень громкости и очередь прослушивания в процессе распознавания."""

import array

import pytest

from app.stt.vosk_worker import _Monitor, peak_level


def pcm(*samples: int) -> bytes:
    return array.array("h", samples).tobytes()


@pytest.mark.parametrize(
    "data, expected",
    [
        (b"", 0.0),
        (pcm(0, 0, 0), 0.0),
        (pcm(16384, -100), 0.5),
        (pcm(10, -16384), 0.5),  # отрицательный пик считается так же
        (pcm(-32768), 1.0),
        (pcm(32767), 32767 / 32768),
    ],
)
def test_peak_level(data, expected):
    assert peak_level(data) == pytest.approx(expected)


class _FakeStream:
    def __init__(self):
        self.aborted = self.closed = False

    def abort(self):
        self.aborted = True

    def close(self):
        self.closed = True


def test_monitor_ignores_audio_when_not_running():
    monitor = _Monitor()
    monitor.feed(pcm(1, 2, 3))
    assert not monitor.running
    assert len(monitor._pending) == 0


def test_monitor_drops_oldest_audio_to_keep_latency_low():
    monitor = _Monitor()
    monitor.stream = _FakeStream()
    monitor._max_bytes = 8
    monitor.feed(pcm(1, 2, 3))
    monitor.feed(pcm(4, 5, 6))
    assert bytes(monitor._pending) == pcm(3, 4, 5, 6)


def test_monitor_stop_closes_stream_and_clears_queue():
    monitor = _Monitor()
    stream = monitor.stream = _FakeStream()
    monitor._max_bytes = 100
    monitor.feed(pcm(1, 2))
    monitor.stop()
    assert stream.aborted and stream.closed
    assert not monitor.running
    assert len(monitor._pending) == 0
