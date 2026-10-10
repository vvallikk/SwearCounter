"""VoskRecognizer без запуска процесса: прогресс загрузки, сообщения воркера, смена микрофона."""

import asyncio
import types

import pytest

from app.stt import vosk_recognizer
from app.stt.vosk_recognizer import VoskRecognizer

MODEL = "vosk-model-small-ru-0.22"


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def monotonic(self) -> float:
        return self.now


class FakeCommands:
    """Передающий конец канала команд воркеру."""

    def __init__(self, error: Exception | None = None):
        self.sent: list[tuple] = []
        self.error = error

    def send(self, message) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(message)


@pytest.fixture
def clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(vosk_recognizer, "time", types.SimpleNamespace(monotonic=clock.monotonic))
    return clock


@pytest.fixture
def texts():
    return []


@pytest.fixture
def recognizer(tmp_path, settings, texts):
    async def on_text(text, is_final):
        texts.append((text, is_final))

    model = tmp_path / "models" / MODEL
    model.mkdir(parents=True)
    return VoskRecognizer(on_text, model, settings)


# --- load_progress ---


def test_load_progress_is_zero_unless_loading(recognizer, clock):
    assert recognizer.load_progress == 0.0
    recognizer.status = "loading"  # загрузка ещё не началась
    assert recognizer.load_progress == 0.0
    recognizer._load_started = clock.now - 5
    recognizer.status = "listening"
    assert recognizer.load_progress == 0.0


def test_load_progress_grows_with_time(recognizer, clock):
    recognizer.status = "loading"
    recognizer._load_started = clock.now
    recognizer._load_expected = 10.0

    clock.now += 2.5
    assert recognizer.load_progress == pytest.approx(0.25)
    clock.now += 5
    assert recognizer.load_progress == pytest.approx(0.75)


def test_load_progress_never_reaches_one_while_loading(recognizer, clock):
    recognizer.status = "loading"
    recognizer._load_started = clock.now
    recognizer._load_expected = 10.0
    clock.now += 100  # загрузка идёт дольше ожидаемого
    assert recognizer.load_progress == 0.99


# --- _expected_load_seconds ---


def test_expected_load_seconds_uses_saved_time(recognizer, settings):
    settings.set("load_seconds", {MODEL: 42.5, "другая": 1.0})
    assert recognizer._expected_load_seconds() == 42.5


def test_expected_load_seconds_estimates_from_model_size(recognizer, monkeypatch):
    monkeypatch.setattr(vosk_recognizer, "LOAD_BYTES_PER_SECOND", 1000)
    (recognizer.model_path / "am").mkdir()
    (recognizer.model_path / "am" / "final.mdl").write_bytes(b"\0" * 3000)
    (recognizer.model_path / "conf.txt").write_bytes(b"\0" * 2000)
    assert recognizer._expected_load_seconds() == pytest.approx(5.0)


def test_expected_load_seconds_is_at_least_one_second(recognizer, settings):
    settings.set("load_seconds", {"другая-модель": 90})
    (recognizer.model_path / "conf.txt").write_bytes(b"\0" * 10)
    assert recognizer._expected_load_seconds() == 1.0


# --- _handle ---


def test_handle_text_calls_on_text(recognizer, texts):
    asyncio.run(recognizer._handle(("text", "привет", False)))
    asyncio.run(recognizer._handle(("text", "привет мир", True)))
    assert texts == [("привет", False), ("привет мир", True)]


def test_handle_loaded_remembers_load_time(recognizer, settings, clock):
    settings.set("load_seconds", {"другая": 3.0})
    recognizer._load_started = clock.now
    clock.now += 12.345

    asyncio.run(recognizer._handle(("loaded", 11.0)))

    # Время считается от запуска процесса, а не по числу из сообщения.
    assert settings.get("load_seconds") == {"другая": 3.0, MODEL: 12.3}
    recognizer._load_started = clock.now
    assert recognizer._expected_load_seconds() == 12.3


def test_handle_listening_updates_mic_state(recognizer):
    recognizer.status = "mic_error"
    recognizer.mic_error = "старая ошибка"
    recognizer.mic_pending = True

    asyncio.run(recognizer._handle(("listening", "Микрофон (Realtek(R) Audio)", 44100)))

    assert recognizer.status == "listening"
    assert recognizer.mic_name == "Микрофон (Realtek(R) Audio)"
    assert recognizer.mic_error is None
    assert recognizer.mic_pending is False


def test_handle_mic_error_updates_mic_state(recognizer):
    recognizer.status = "listening"
    recognizer.mic_name = "Микрофон (Realtek(R) Audio)"
    recognizer.mic_pending = True

    asyncio.run(recognizer._handle(("mic_error", "Микрофон «USB» не найден")))

    assert recognizer.status == "mic_error"
    assert recognizer.mic_name is None
    assert recognizer.mic_error == "Микрофон «USB» не найден"
    assert recognizer.mic_pending is False


def test_handle_error_raises_with_worker_traceback(recognizer):
    with pytest.raises(RuntimeError, match="Traceback из процесса"):
        asyncio.run(recognizer._handle(("error", "Traceback из процесса")))


# --- set_device ---


def test_set_device_before_start_only_remembers_device(recognizer):
    recognizer.set_device("Микрофон (Realtek(R) Audio)")
    assert recognizer.device == "Микрофон (Realtek(R) Audio)"
    assert recognizer.mic_pending is False


@pytest.mark.parametrize(
    ("status", "pending"),
    [("listening", True), ("mic_error", True), ("loading", False)],
)
def test_set_device_sends_command_to_worker(recognizer, status, pending):
    commands = FakeCommands()
    recognizer._commands = commands
    recognizer.status = status

    recognizer.set_device("Головная гарнитура")

    assert commands.sent == [("device", "Головная гарнитура")]
    assert recognizer.device == "Головная гарнитура"
    # Пока модель грузится, ответа о микрофоне ждать не нужно: он откроется после загрузки.
    assert recognizer.mic_pending is pending


def test_set_device_to_default(recognizer):
    commands = FakeCommands()
    recognizer._commands = commands
    recognizer.status = "listening"
    recognizer.set_device(None)
    assert commands.sent == [("device", None)]


def test_set_device_ignores_closed_pipe(recognizer):
    recognizer._commands = FakeCommands(error=BrokenPipeError())
    recognizer.status = "listening"
    recognizer.set_device("Головная гарнитура")  # не падает
    assert recognizer.device == "Головная гарнитура"


# --- set_model ---


def test_set_model_restarts_with_new_model(recognizer, monkeypatch, tmp_path):
    runs = []

    async def fake_run(self):
        runs.append(self.model_path.name)
        await asyncio.Event().wait()  # «грузится», пока задачу не отменят

    monkeypatch.setattr(VoskRecognizer, "run", fake_run)
    other = tmp_path / "models" / "vosk-model-ru-0.42"

    async def scenario():
        await recognizer.start()
        await asyncio.sleep(0)
        recognizer._load_started = 123.0
        await recognizer.set_model(other)
        await asyncio.sleep(0)
        state = (recognizer.status, recognizer.model_path, recognizer._load_started)
        await recognizer.stop()
        return state

    status, model_path, load_started = asyncio.run(scenario())

    assert runs == [MODEL, "vosk-model-ru-0.42"]
    assert status == "loading"
    assert model_path == other
    assert load_started is None  # прогресс новой загрузки не считается от старой
    assert recognizer.status == "stopped"


# --- уровень громкости, прослушивание, испорченные настройки ---


def test_handle_level_calls_on_level(recognizer):
    levels = []

    async def on_level(level):
        levels.append(level)

    recognizer.on_level = on_level
    asyncio.run(recognizer._handle(("level", 0.25)))
    assert levels == [0.25]


def test_handle_level_without_callback_is_ignored(recognizer):
    asyncio.run(recognizer._handle(("level", 0.25)))


def test_handle_monitor_updates_state(recognizer):
    asyncio.run(recognizer._handle(("monitor", True, None)))
    assert recognizer.monitor is True and recognizer.monitor_error is None
    asyncio.run(recognizer._handle(("monitor", False, "нет наушников")))
    assert recognizer.monitor is False and recognizer.monitor_error == "нет наушников"


def test_set_monitor_sends_command(recognizer):
    recognizer._commands = FakeCommands()
    recognizer.monitor_error = "старая ошибка"
    recognizer.set_monitor(True)
    assert recognizer._commands.sent == [("monitor", True)]
    assert recognizer.monitor_error is None


def test_set_monitor_without_worker_does_nothing(recognizer):
    recognizer.set_monitor(True)  # процесса нет — не падает


@pytest.mark.parametrize("broken", ["строка", 5, None, {MODEL: "много"}, {MODEL: -1}])
def test_corrupted_saved_load_time_falls_back_to_estimate(recognizer, settings, monkeypatch, broken):
    monkeypatch.setattr(vosk_recognizer, "LOAD_BYTES_PER_SECOND", 1)
    (recognizer.model_path / "data").write_bytes(b"x" * 5)
    settings.set("load_seconds", broken)
    assert recognizer._expected_load_seconds() == 5
    recognizer._remember_load_seconds(2.0)  # и запись не падает
    assert settings.get("load_seconds")[MODEL] == 2.0


def test_set_device_turns_monitor_off(recognizer):
    recognizer._commands = FakeCommands()
    recognizer.status = "listening"
    recognizer.monitor = True
    recognizer.monitor_error = "старая ошибка"
    recognizer.set_device(None)
    assert recognizer.monitor is False and recognizer.monitor_error is None
