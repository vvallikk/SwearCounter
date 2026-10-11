"""Движки распознавания на поддельных vosk и sherpa_onnx: без моделей и звука."""

import array
import json
import math
import sys
import types

import pytest

from app.stt import engines
from app.stt.catalog import CATALOG, SHERPA_NEMO_CTC, SHERPA_T_ONE, SHERPA_TRANSDUCER, VOSK
from app.stt.engines import Resampler, load_engine, to_floats


def model_of(engine):
    return next(m for m in CATALOG if m.engine == engine)


def pcm(*values):
    return array.array("h", values).tobytes()


# --- подделки ---


class FakeOnlineRecognizer:
    """Текст — это сумма принятых отсчётов; конец фразы — после отсчёта 1.0."""

    created = []

    def __init__(self, kind, **kwargs):
        self.kind, self.kwargs = kind, kwargs
        FakeOnlineRecognizer.created.append(self)

    @classmethod
    def from_transducer(cls, **kwargs):
        return cls("transducer", **kwargs)

    @classmethod
    def from_t_one_ctc(cls, **kwargs):
        return cls("t_one", **kwargs)

    def create_stream(self):
        return types.SimpleNamespace(words=[], pending=0, rates=[], accept_waveform=None)

    def is_ready(self, stream):
        return stream.pending > 0

    def decode_stream(self, stream):
        stream.pending -= 1

    def get_result(self, stream):
        return " ".join(stream.words) + " "

    def is_endpoint(self, stream):
        return stream.endpoint

    def reset(self, stream):
        stream.words.clear()


def online_stream(rec):
    """Поток, который понимает отсчёты: 0.5 — слово «мат», 1.0 — конец фразы."""
    stream = rec.create_stream()
    stream.endpoint = False

    def accept_waveform(rate, samples):
        stream.rates.append(rate)
        stream.pending += 1
        for v in samples:
            if v == 0.5:
                stream.words.append("мат")
            if v == 1.0 - 1 / 32768:
                stream.endpoint = True

    stream.accept_waveform = accept_waveform
    return stream


class FakeVad:
    """Речь — отсчёты не равные нулю; конец фразы — первый ноль после речи."""

    def __init__(self):
        self.segments = []
        self.current = []

    def accept_waveform(self, samples):
        for v in samples:
            if v:
                self.current.append(v)
            elif self.current:
                self.segments.append(self.current)
                self.current = []

    def empty(self):
        return not self.segments

    @property
    def front(self):
        return types.SimpleNamespace(samples=self.segments[0])

    def pop(self):
        self.segments.pop(0)

    def is_speech_detected(self):
        return bool(self.current)

    @property
    def current_segment(self):
        return types.SimpleNamespace(samples=list(self.current))


class FakeOfflineRecognizer:
    """Распознаёт фразу как «слово» по одному на каждые 100 отсчётов."""

    def __init__(self):
        self.decoded = []

    def create_stream(self):
        stream = types.SimpleNamespace(result=types.SimpleNamespace(text=""))

        def accept_waveform(rate, samples):
            assert rate == engines.VAD_SAMPLE_RATE
            stream.samples = list(samples)

        stream.accept_waveform = accept_waveform
        return stream

    def decode_stream(self, stream):
        self.decoded.append(len(stream.samples))
        stream.result.text = " ".join(["слово"] * (len(stream.samples) // 100)) + " "


@pytest.fixture
def fake_sherpa(monkeypatch):
    FakeOnlineRecognizer.created = []
    module = types.ModuleType("sherpa_onnx")
    module.OnlineRecognizer = FakeOnlineRecognizer
    module.OfflineRecognizer = types.SimpleNamespace(
        from_nemo_ctc=lambda **kwargs: types.SimpleNamespace(kind="nemo_ctc", kwargs=kwargs)
    )
    vad_configs = []

    def vad_model_config():
        config = types.SimpleNamespace(silero_vad=types.SimpleNamespace(), sample_rate=0)
        vad_configs.append(config)
        return config

    module.VadModelConfig = vad_model_config
    module.VoiceActivityDetector = lambda config, buffer_size_in_seconds: FakeVad()
    module.vad_configs = vad_configs
    monkeypatch.setitem(sys.modules, "sherpa_onnx", module)
    return module


@pytest.fixture
def fake_vosk(monkeypatch):
    module = types.ModuleType("vosk")
    module.log_level = None
    module.SetLogLevel = lambda level: setattr(module, "log_level", level)
    module.Model = lambda path: types.SimpleNamespace(path=path)
    module.KaldiRecognizer = lambda model, rate: types.SimpleNamespace(model=model, rate=rate)
    monkeypatch.setitem(sys.modules, "vosk", module)
    return module


# --- выбор движка ---


def test_vosk_models_use_vosk(fake_vosk, models_dir):
    model = model_of(VOSK)
    engine = load_engine(str(model.path))
    assert isinstance(engine, engines.VoskEngine)
    assert engine.model.path == str(model.path)
    assert fake_vosk.log_level == -1


def test_unknown_folder_is_treated_as_vosk(fake_vosk, models_dir):
    """Модель Vosk, положенную в models/ вручную, по-прежнему можно выбрать."""
    engine = load_engine(str(models_dir / "vosk-model-ru-0.10"))
    assert isinstance(engine, engines.VoskEngine)


def test_transducer_model(fake_sherpa, models_dir):
    model = model_of(SHERPA_TRANSDUCER)
    engine = load_engine(str(model.path))
    rec = engine.rec
    assert rec.kind == "transducer"
    assert rec.kwargs["encoder"] == str(model.path / model.model_files["encoder"])
    assert rec.kwargs["tokens"] == str(model.path / model.model_files["tokens"])
    assert rec.kwargs["enable_endpoint_detection"] is True
    assert rec.kwargs["num_threads"] == engines.NUM_THREADS


def test_t_one_model(fake_sherpa, models_dir):
    model = model_of(SHERPA_T_ONE)
    rec = load_engine(str(model.path)).rec
    assert rec.kind == "t_one"
    assert rec.kwargs["model"] == str(model.path / model.model_files["model"])
    assert rec.kwargs["sample_rate"] == 8000


def test_nemo_ctc_model_with_vad(fake_sherpa, models_dir):
    model = model_of(SHERPA_NEMO_CTC)
    engine = load_engine(str(model.path))
    assert engine.rec.kwargs["model"] == str(model.path / model.model_files["model"])
    engine.session(48000)
    config = fake_sherpa.vad_configs[-1]
    assert config.silero_vad.model == str(model.path / model.model_files["vad"])
    assert config.sample_rate == engines.VAD_SAMPLE_RATE
    assert config.silero_vad.max_speech_duration == engines.MAX_PHRASE_SECONDS


# --- Vosk ---


class FakeKaldi:
    def __init__(self, script):
        self.script = list(script)  # (финал?, текст) на каждый кусок
        self.current = None

    def AcceptWaveform(self, data):
        self.current = self.script.pop(0)
        return self.current[0]

    def Result(self):
        return json.dumps({"text": self.current[1]})

    def PartialResult(self):
        return json.dumps({"partial": self.current[1]})


def test_vosk_session_partials_and_finals():
    session = engines._VoskSession(
        FakeKaldi([(False, ""), (False, "ну"), (False, "ну"), (False, "ну мат"), (True, "ну мат"), (True, "")])
    )
    results = [session.accept(b"\0\0") for _ in range(6)]
    assert results == [[], [("ну", False)], [], [("ну мат", False)], [("ну мат", True)], []]


def test_vosk_repeats_partial_after_final():
    session = engines._VoskSession(FakeKaldi([(False, "мат"), (True, "мат"), (False, "мат")]))
    assert [session.accept(b"") for _ in range(3)] == [[("мат", False)], [("мат", True)], [("мат", False)]]


# --- потоковые модели sherpa-onnx ---


def test_online_session():
    rec = FakeOnlineRecognizer("transducer")
    session = engines._OnlineSession(rec, 44100)
    session.stream = online_stream(rec)

    assert session.accept(pcm(0, 0)) == []
    assert session.accept(pcm(16384)) == [("мат", False)]
    assert session.accept(pcm(0)) == []  # текст не изменился
    assert session.accept(pcm(16384)) == [("мат мат", False)]
    assert session.accept(pcm(32767)) == [("мат мат", True)]
    assert session.stream.words == []  # после конца фразы поток начат заново
    assert session.stream.pending == 0  # всё распознано
    assert set(session.stream.rates) == {44100}  # частоту микрофона передаём как есть


def test_online_session_empty_phrase_end():
    rec = FakeOnlineRecognizer("transducer")
    session = engines._OnlineSession(rec, 16000)
    session.stream = online_stream(rec)
    assert session.accept(pcm(32767)) == []


# --- GigaAM: детектор речи и распознавание фраз ---


def vad_session(samplerate=16000):
    return engines._VadSession(FakeOfflineRecognizer(), FakeVad(), samplerate)


def test_vad_session_final_after_pause():
    session = vad_session()
    assert session.accept(pcm(*[100] * 250)) == []  # речь короче PARTIAL_SECONDS
    assert session.accept(pcm(*[0] * 10)) == [("слово слово", True)]
    assert session.accept(pcm(*[0] * 10)) == []


def test_vad_session_partials_while_speaking(monkeypatch):
    monkeypatch.setattr(engines, "PARTIAL_SECONDS", 200 / engines.VAD_SAMPLE_RATE)
    session = vad_session()
    assert session.accept(pcm(*[100] * 150)) == []
    assert session.accept(pcm(*[100] * 100)) == [("слово слово", False)]  # 250 отсчётов речи
    assert session.accept(pcm(*[100] * 100)) == []  # ещё не прошло 200 отсчётов
    assert session.accept(pcm(*[100] * 100)) == [("слово слово слово слово", False)]
    assert session.accept(pcm(*[0] * 10)) == [("слово слово слово слово", True)]  # 450 отсчётов
    # Новая фраза: таймер промежуточных результатов начат заново.
    assert session.accept(pcm(*[100] * 150)) == []


def test_vad_session_does_not_repeat_same_partial(monkeypatch):
    monkeypatch.setattr(engines, "PARTIAL_SECONDS", 10 / engines.VAD_SAMPLE_RATE)
    session = vad_session()
    assert session.accept(pcm(*[100] * 120)) == [("слово", False)]
    assert session.accept(pcm(*[100] * 20)) == []  # «слово» снова: не повторяем


def test_vad_session_resamples_to_16k():
    session = vad_session(48000)
    session.accept(pcm(*[3000] * 4800))
    session.accept(pcm(*[0] * 30))
    # 0,1 с звука на 48 кГц — это 1600 отсчётов на 16 кГц (±1 на стыке).
    assert abs(session.rec.decoded[-1] - 1600) <= 1


# --- преобразование звука ---


def test_to_floats():
    assert to_floats(pcm(0, 16384, -32768) + b"\x01") == [0.0, 0.5, -1.0]


def test_resampler_same_rate_passes_through():
    samples = [0.1, 0.2, 0.3]
    assert Resampler(16000, 16000)(samples) is samples


@pytest.mark.parametrize("source", [8000, 22050, 44100, 48000])
def test_resampler_keeps_length_across_chunks(source):
    resampler = Resampler(source, 16000)
    total = sum(len(resampler([0.0] * (source // 10))) for _ in range(50))  # 5 секунд кусками по 0,1 с
    assert abs(total - 16000 * 5) <= 2


@pytest.mark.parametrize("source", [44100, 48000])
def test_resampler_keeps_speech_frequencies(source):
    """Тон 440 Гц после прореживания остаётся тем же тоном, кусками или целиком."""
    tone = [math.sin(2 * math.pi * 440 * i / source) for i in range(source)]
    resampler = Resampler(source, 16000)
    chunk = source // 10
    out = []
    for i in range(0, len(tone), chunk):
        out += resampler(tone[i : i + chunk])
    # Сглаживание чуть сдвигает фазу и ослабляет тон, но форма сохраняется.
    shift = (round(source / 16000) - 1) / 2 / source * 16000
    expected = [math.sin(2 * math.pi * 440 * (i - shift) / 16000) for i in range(len(out))]
    error = max(abs(a - b) for a, b in zip(out[100:], expected[100:]))
    assert error < 0.05


def test_resampler_suppresses_high_frequencies():
    """Писк 15 кГц выше половины 16 кГц: после прореживания его почти не слышно."""
    source = 48000
    squeal = [math.sin(2 * math.pi * 15000 * i / source) for i in range(source // 10)]
    out = Resampler(source, 16000)(squeal)
    assert max(abs(v) for v in out[10:]) < 0.35
