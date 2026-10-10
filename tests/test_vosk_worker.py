"""Протокол процесса распознавания (_Worker и run_worker).

Воркер запускается в потоке текущего процесса, а не в отдельном процессе:
vosk и sounddevice подменены, звук тест подаёт сам через FakeStream.feed().
Каналы — настоящие multiprocessing.Pipe, как в приложении.
"""

import json
import multiprocessing
import sys
import threading
import types

import pytest

from app.stt import vosk_worker
from conftest import HYPERX, REALTEK

TIMEOUT = 2.0  # сколько ждать сообщения от воркера


class _StopWorker(BaseException):
    """Останавливает цикл воркера в конце теста.

    Наследуется от BaseException, чтобы его не перехватил `except Exception`
    вокруг открытия микрофона.
    """


def partial(text: str) -> bytes:
    """Кусок звука, после которого распознаватель вернёт промежуточный результат."""
    return f"partial:{text}".encode()


def final(text: str) -> bytes:
    """Кусок звука, завершающий фразу text."""
    return f"final:{text}".encode()


def make_fake_vosk() -> types.ModuleType:
    """Подмена vosk: кусок звука partial(текст) или final(текст) — готовый результат."""
    vosk = types.ModuleType("vosk")
    vosk.models_loaded = 0
    vosk.broken_model = None  # текст исключения при загрузке модели

    class Model:
        def __init__(self, path):
            if vosk.broken_model:
                raise RuntimeError(vosk.broken_model)
            vosk.models_loaded += 1
            self.path = path

    class KaldiRecognizer:
        def __init__(self, model, samplerate):
            self.samplerate = samplerate
            self._text = ""

        def AcceptWaveform(self, data: bytes) -> bool:
            kind, _, self._text = data.decode("utf-8").partition(":")
            return kind == "final"

        def Result(self) -> str:
            return json.dumps({"text": self._text})

        def PartialResult(self) -> str:
            return json.dumps({"partial": self._text})

    vosk.SetLogLevel = lambda level: None
    vosk.Model = Model
    vosk.KaldiRecognizer = KaldiRecognizer
    return vosk


class _ReaderExit(BaseException):
    """Замена os._exit в потоке чтения команд: завершает только этот поток, а не pytest."""


def _exit_thread(code=0):
    raise _ReaderExit(code)


class WorkerHarness:
    def __init__(self, fake_sd, fake_vosk):
        self.fake_sd = fake_sd
        self.vosk = fake_vosk
        self.error: BaseException | None = None
        self.thread: threading.Thread | None = None
        self.levels: list[float] = []  # уровни громкости, пропущенные recv()

    def start(self, device=None, *, via_run_worker=False) -> None:
        self.results, results_send = multiprocessing.Pipe(duplex=False)
        cmd_recv, self.commands = multiprocessing.Pipe(duplex=False)
        self._threads_before = set(threading.enumerate())
        if via_run_worker:
            target = lambda: vosk_worker.run_worker(results_send, cmd_recv, "models/fake", device)  # noqa: E731
        else:
            worker = vosk_worker._Worker(results_send, cmd_recv, device)
            target = lambda: worker.run("models/fake")  # noqa: E731
        self.thread = threading.Thread(target=self._guard, args=(target,), daemon=True)
        self.thread.start()

    def _guard(self, target) -> None:
        try:
            target()
        except _StopWorker:
            pass
        except BaseException as e:  # покажем в тесте, а не потеряем в потоке
            self.error = e

    def recv(self) -> tuple:
        """Следующее сообщение, кроме уровня громкости (он идёт на каждый кусок звука)."""
        while True:
            assert self.results.poll(TIMEOUT), "воркер ничего не прислал"
            message = self.results.recv()
            if message[0] != "level":
                return message
            self.levels.append(message[1])

    def expect(self, kind: str) -> tuple:
        message = self.recv()
        assert message[0] == kind, message
        return message

    def assert_silent(self, seconds: float = 0.1) -> None:
        while self.results.poll(seconds):
            message = self.results.recv()
            assert message[0] == "level", message

    def device(self, device) -> None:
        self.commands.send(("device", device))

    @property
    def stream(self):
        return self.fake_sd.streams[-1]

    def close(self) -> None:
        if self.thread is None:
            return
        # Команда будит воркер, а следующее открытие микрофона его останавливает.
        self.fake_sd.fail_on_refresh = _StopWorker()
        if self.thread.is_alive():
            self.device(None)
        self.thread.join(TIMEOUT)
        # Закрытый канал команд завершает поток чтения команд.
        self.commands.close()
        for thread in set(threading.enumerate()) - self._threads_before:
            thread.join(TIMEOUT)
            assert not thread.is_alive(), f"поток {thread.name} не завершился"
        self.results.close()
        if self.error is not None:
            raise self.error


@pytest.fixture
def fake_vosk(monkeypatch):
    vosk = make_fake_vosk()
    monkeypatch.setitem(sys.modules, "vosk", vosk)
    return vosk


@pytest.fixture
def worker(fake_sd, fake_vosk, monkeypatch):
    monkeypatch.setattr(vosk_worker, "os", types.SimpleNamespace(_exit=_exit_thread))
    previous_hook = threading.excepthook

    def excepthook(args):
        # Ожидаемое завершение потока чтения команд — не ошибка теста.
        if args.exc_type is not _ReaderExit:
            previous_hook(args)

    monkeypatch.setattr(threading, "excepthook", excepthook)
    harness = WorkerHarness(fake_sd, fake_vosk)
    yield harness
    harness.close()


def start_listening(worker, device=None) -> tuple:
    worker.start(device)
    loaded = worker.expect("loaded")
    assert loaded[1] >= 0
    return worker.expect("listening")


def test_loads_model_and_opens_default_microphone(worker, fake_vosk):
    assert start_listening(worker) == ("listening", REALTEK, 44100)
    assert fake_vosk.models_loaded == 1
    assert worker.stream.active
    assert worker.stream.device is None  # системный микрофон по умолчанию


def test_text_flows_from_microphone(worker):
    start_listening(worker)
    for chunk in (partial("при"), partial("при"), partial("привет"), final("привет мир"), final("")):
        worker.stream.feed(chunk)

    assert worker.recv() == ("text", "при", False)
    # Повтор того же промежуточного результата не отправляется.
    assert worker.recv() == ("text", "привет", False)
    assert worker.recv() == ("text", "привет мир", True)
    # Пустой окончательный результат (тишина) тоже не отправляется.
    worker.assert_silent()


def test_opens_microphone_from_settings_by_full_name(worker, fake_sd):
    assert start_listening(worker, HYPERX) == ("listening", HYPERX, 16000)
    assert worker.stream.device == 2
    assert worker.stream.samplerate == 16000


def test_device_command_switches_microphone_without_reloading_model(worker, fake_vosk):
    start_listening(worker)
    first = worker.stream

    worker.device(HYPERX)

    assert worker.expect("listening") == ("listening", HYPERX, 16000)
    assert fake_vosk.models_loaded == 1
    assert first.closed and not first.active
    assert worker.stream is not first
    worker.stream.feed(final("новый микрофон"))
    assert worker.recv() == ("text", "новый микрофон", True)


def test_unknown_device_reports_mic_error_and_recovers(worker, fake_sd, fake_vosk):
    worker.start("USB микрофон")
    worker.expect("loaded")
    message = worker.expect("mic_error")
    assert "USB микрофон" in message[1]
    assert fake_sd.streams == []

    # Модель остаётся в памяти и ждёт другой микрофон.
    worker.assert_silent()
    worker.device(REALTEK)
    assert worker.expect("listening") == ("listening", REALTEK, 44100)
    assert fake_vosk.models_loaded == 1


def test_inactive_stream_reports_lost_microphone(worker, monkeypatch):
    monkeypatch.setattr(vosk_worker, "SILENCE_TIMEOUT", 0.05)
    start_listening(worker)
    lost = worker.stream

    lost.active = False  # например, гарнитуру выдернули из USB

    message = worker.expect("mic_error")
    assert REALTEK in message[1] and "перестал отвечать" in message[1]

    worker.device(None)
    assert worker.expect("listening") == ("listening", REALTEK, 44100)
    assert lost.closed
    assert worker.stream is not lost


def test_silence_on_active_stream_is_not_an_error(worker, monkeypatch):
    monkeypatch.setattr(vosk_worker, "SILENCE_TIMEOUT", 0.05)
    start_listening(worker)

    worker.assert_silent(0.3)  # несколько таймаутов тишины подряд

    worker.stream.feed(final("я тут"))
    assert worker.recv() == ("text", "я тут", True)


def test_run_worker_reports_model_error(worker, fake_vosk):
    fake_vosk.broken_model = "битая модель"
    worker.start(via_run_worker=True)

    kind, description = worker.recv()
    assert kind == "error"
    assert "битая модель" in description  # traceback целиком
    worker.thread.join(TIMEOUT)
    assert not worker.thread.is_alive()


def test_run_worker_runs_worker(worker):
    worker.start(via_run_worker=True)
    worker.expect("loaded")
    assert worker.expect("listening") == ("listening", REALTEK, 44100)


# --- уровень громкости и прослушивание ---


def pcm(*samples: int) -> bytes:
    return b"".join(s.to_bytes(2, "little", signed=True) for s in samples)


class FakeOutputStream:
    """Поток в динамики: тест сам «просит» звук через pull()."""

    instances: list["FakeOutputStream"] = []

    def __init__(self, samplerate, channels, dtype, callback):
        self.samplerate = samplerate
        self.callback = callback
        self.active = self.closed = False
        FakeOutputStream.instances.append(self)

    def start(self):
        self.active = True

    def abort(self):
        self.active = False

    def close(self):
        self.closed = True

    def pull(self, nbytes: int) -> bytes:
        out = bytearray(nbytes)
        self.callback(out, nbytes // 2, None, None)
        return bytes(out)


@pytest.fixture
def speakers(fake_sd):
    FakeOutputStream.instances = []
    fake_sd.RawOutputStream = FakeOutputStream
    return FakeOutputStream.instances


def test_level_reported_for_each_chunk(worker):
    start_listening(worker)
    # Заглушка vosk читает куски как текст, поэтому байты отсчётов — допустимый UTF-8.
    worker.stream.feed(pcm(16384, 100))
    worker.stream.feed(final("ок"))
    assert worker.recv() == ("text", "ок", True)
    assert worker.levels[0] == pytest.approx(0.5)
    assert len(worker.levels) == 2


def test_monitor_plays_microphone_and_stops(worker, speakers):
    start_listening(worker)
    worker.commands.send(("monitor", True))
    assert worker.expect("monitor") == ("monitor", True, None)
    out = speakers[-1]
    assert out.active and out.samplerate == 44100

    worker.stream.feed(pcm(1, 2))
    worker.stream.feed(final("стоп"))  # дожидаемся, пока воркер обработает кусок звука
    worker.expect("text")
    assert out.pull(4) == pcm(1, 2)
    assert out.pull(len(final("стоп"))) == final("стоп")  # в наушники идёт весь звук
    assert out.pull(4) == pcm(0, 0)  # звука больше нет — тишина, а не мусор

    worker.commands.send(("monitor", False))
    assert worker.expect("monitor") == ("monitor", False, None)
    assert out.closed


def test_monitor_failure_is_reported(worker, fake_sd):
    def broken(**kwargs):
        raise RuntimeError("нет устройства вывода")

    fake_sd.RawOutputStream = broken
    start_listening(worker)
    worker.commands.send(("monitor", True))
    kind, enabled, error = worker.expect("monitor")
    assert not enabled
    assert "нет устройства вывода" in error


def test_microphone_switch_turns_monitor_off(worker, speakers):
    start_listening(worker)
    worker.commands.send(("monitor", True))
    worker.expect("monitor")
    worker.device(HYPERX)
    assert worker.expect("listening")[1] == HYPERX
    worker.assert_silent()  # прослушивание само не включилось
    assert speakers[0].closed
    assert len(speakers) == 1


def test_lost_microphone_is_closed_right_away(worker, monkeypatch):
    monkeypatch.setattr(vosk_worker, "SILENCE_TIMEOUT", 0.05)
    start_listening(worker)
    lost = worker.stream
    lost.active = False
    worker.expect("mic_error")
    # Закрыт сразу, а не только после выбора другого микрофона.
    assert lost.closed
