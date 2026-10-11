"""Общие фикстуры: файлы во временной папке и поддельный sounddevice.

Тесты не трогают настоящие микрофоны, модели Vosk и файлы в корне проекта.
"""

import sys

import pytest

from app import autostart
from app.counter import Counter
from app.settings import Settings
from app.stt import audio_devices

# Типичная таблица устройств Windows: одно и то же устройство видно
# в нескольких интерфейсах. MME обрезает имена до 31 символа, в DirectSound
# и WASAPI имена полные, в WDM-KS — служебные («... Wave»).
HOSTAPIS = [
    {"name": "MME"},
    {"name": "Windows DirectSound"},
    {"name": "Windows WASAPI"},
    {"name": "Windows WDM-KS"},
]

REALTEK = "Микрофон (Realtek(R) Audio)"
HYPERX = "Головная гарнитура (HyperX Cloud Flight Wireless)"
STEAM = "Микрофон (Steam Streaming Microphone)"
MME_NAME_LIMIT = 31


def _device(name: str, hostapi: int, inputs: int, outputs: int = 0, rate: float = 44100.0):
    return {
        "name": name,
        "hostapi": hostapi,
        "max_input_channels": inputs,
        "max_output_channels": outputs,
        "default_samplerate": rate,
    }


def mme(name: str) -> str:
    """Имя устройства, как его показывает MME."""
    return name[:MME_NAME_LIMIT]


def windows_devices() -> list[dict]:
    return [
        # MME: первым идёт «переназначение» (системный микрофон по умолчанию).
        _device("Переназначение звуковых устр. - Input", 0, 2),
        _device(mme(REALTEK), 0, 2),
        _device(mme(HYPERX), 0, 1, rate=16000.0),
        _device(mme(STEAM), 0, 2, rate=48000.0),
        _device("Переназначение звуковых устр. - Output", 0, 0, 2),
        _device("Динамики (Realtek(R) Audio)", 0, 0, 2),
        # DirectSound: полные имена.
        _device("Основной драйвер записи звука", 1, 2),
        _device(REALTEK, 1, 2),
        _device(HYPERX, 1, 1),
        _device("Первичный звуковой драйвер", 1, 0, 2),
        # WASAPI: полные имена (Steam-микрофон есть только здесь).
        _device(REALTEK, 2, 2),
        _device(HYPERX, 2, 1),
        _device(STEAM, 2, 2),
        # WDM-KS: имя начинается как MME-имя гарнитуры и длиннее настоящего,
        # поэтому выиграло бы, если бы его не отбрасывали.
        _device(HYPERX[:MME_NAME_LIMIT] + " Cloud Flight Wireless Wave)", 3, 1),
    ]


class FakeStream:
    """Поток микрофона: звук «приходит», когда тест вызывает feed()."""

    def __init__(self, device, samplerate, blocksize, dtype, channels, callback):
        self.device = device
        self.samplerate = samplerate
        self.callback = callback
        self.active = False
        self.closed = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def abort(self):
        self.active = False

    def close(self):
        self.closed = True

    def feed(self, data: bytes) -> None:
        self.callback(data, len(data) // 2, None, None)


class FakeSoundDevice:
    """Подмена модуля sounddevice с таблицей устройств windows_devices()."""

    def __init__(self):
        self.devices = windows_devices()
        self.hostapis = HOSTAPIS
        self.default = type("Default", (), {})()
        self.default.hostapi = 0
        self.default.device = [1, 5]  # микрофон Realtek, динамики Realtek
        self.streams: list[FakeStream] = []
        self.refreshes = 0
        # Исключение, которое бросит следующий refresh(): так тесты останавливают процесс-воркер.
        self.fail_on_refresh: BaseException | None = None

    def _terminate(self):
        if self.fail_on_refresh is not None:
            raise self.fail_on_refresh
        self.refreshes += 1

    def _initialize(self):
        pass

    def query_hostapis(self, index=None):
        return self.hostapis if index is None else self.hostapis[index]

    def query_devices(self, device=None, kind=None):
        if device is None and kind is None:
            return [dict(d, index=i) for i, d in enumerate(self.devices)]
        if device is None:
            device = self.default.device[0 if kind == "input" else 1]
        info = self.devices[device]
        if kind == "input" and info["max_input_channels"] == 0:
            raise ValueError(f"Устройство {device} не является микрофоном")
        return dict(info, index=device)

    def RawInputStream(self, **kwargs):
        stream = FakeStream(**kwargs)
        self.streams.append(stream)
        return stream


@pytest.fixture
def fake_sd(monkeypatch):
    """Поддельный sounddevice и в audio_devices, и для `import sounddevice`."""
    sd = FakeSoundDevice()
    monkeypatch.setattr(audio_devices, "sd", sd)
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    return sd


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "settings.json"


@pytest.fixture
def settings(settings_path):
    return Settings(settings_path)


@pytest.fixture
def counter_path(tmp_path):
    return tmp_path / "counter.json"


@pytest.fixture
def counter(counter_path):
    return Counter(counter_path)


@pytest.fixture
def models_dir(tmp_path, monkeypatch):
    """Папка models/ во временной папке; модели в ней изначально не установлены."""
    from app.stt import catalog

    path = tmp_path / "models"
    path.mkdir()
    monkeypatch.setattr(catalog, "MODELS_DIR", path)
    return path


class FakeRunKey:
    """Значение автозапуска в «реестре» без настоящего реестра."""

    def __init__(self):
        self.value: str | None = None
        self.fail: OSError | None = None

    def read(self):
        return self.value

    def write(self, command):
        if self.fail is not None:
            raise self.fail
        self.value = command

    def delete(self):
        self.value = None


@pytest.fixture(autouse=True)
def run_key(monkeypatch):
    """Ни один тест не пишет в настоящий автозапуск Windows."""
    key = FakeRunKey()
    monkeypatch.setattr(autostart, "default_run_key", lambda: key)
    return key


# Сообщения, которыми сервер встречает нового клиента WebSocket, по порядку.
GREETING = ("state", "pause", "timer", "goals", "sound", "style", "counters")


def skip_greeting(ws) -> list[dict]:
    """Читает приветствие сервера, чтобы тест дальше видел только новые сообщения."""
    messages = [ws.receive_json() for _ in GREETING]
    assert tuple(m["type"] for m in messages) == GREETING
    return messages
