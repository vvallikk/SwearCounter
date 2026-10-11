"""Движки распознавания: Vosk и модели sherpa-onnx за одним интерфейсом.

load_engine(папка модели) загружает модель в память. engine.session(частота)
начинает распознавание одного микрофона; session.accept(звук int16) возвращает
список результатов (текст, is_final): промежуточные — пока фраза звучит,
окончательный — когда она закончилась.

Работает в процессе распознавания (worker.py), поэтому тяжёлые библиотеки
импортируются только здесь и только когда нужны.
"""

import array
import json
from pathlib import Path

from .catalog import SHERPA_NEMO_CTC, SHERPA_T_ONE, SHERPA_TRANSDUCER, find_model

NUM_THREADS = 2  # потоков процессора на распознавание: остальное остаётся игре и трансляции
VAD_SAMPLE_RATE = 16000  # детектор речи и GigaAM работают только на этой частоте
PARTIAL_SECONDS = 0.6  # как часто GigaAM распознаёт ещё не законченную фразу
MAX_PHRASE_SECONDS = 15  # длиннее фразу детектор речи режет: распознавать её дольше

Result = tuple[str, bool]


def load_engine(model_path: str):
    model = find_model(Path(model_path).name)
    if model is None or model.engine not in _SHERPA:
        return VoskEngine(model_path)  # модели Vosk, положенные вручную, тоже работают
    files = {role: str(Path(model_path) / name) for role, name in model.model_files.items()}
    return _SHERPA[model.engine](files)


def to_floats(data: bytes) -> list[float]:
    """Звук int16 в числа от -1 до 1, как ждёт sherpa-onnx."""
    return [v / 32768 for v in array.array("h", data[: len(data) // 2 * 2])]


class VoskEngine:
    def __init__(self, model_path: str):
        import vosk

        vosk.SetLogLevel(-1)  # иначе Kaldi засыпает консоль служебными сообщениями
        self.model = vosk.Model(model_path)

    def session(self, samplerate: int) -> "_VoskSession":
        import vosk

        return _VoskSession(vosk.KaldiRecognizer(self.model, samplerate))


class _VoskSession:
    def __init__(self, rec):
        self.rec = rec
        self.last_partial = ""

    def accept(self, data: bytes) -> list[Result]:
        if self.rec.AcceptWaveform(data):
            self.last_partial = ""
            text = json.loads(self.rec.Result())["text"]
            return [(text, True)] if text else []
        partial = json.loads(self.rec.PartialResult())["partial"]
        if partial and partial != self.last_partial:
            self.last_partial = partial
            return [(partial, False)]
        return []


class _OnlineEngine:
    """Потоковые модели: текст растёт по мере речи, конец фразы определяет сама модель."""

    def __init__(self, rec):
        self.rec = rec

    @classmethod
    def transducer(cls, files: dict[str, str]) -> "_OnlineEngine":
        import sherpa_onnx

        return cls(
            sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=files["tokens"],
                encoder=files["encoder"],
                decoder=files["decoder"],
                joiner=files["joiner"],
                num_threads=NUM_THREADS,
                sample_rate=16000,
                enable_endpoint_detection=True,
            )
        )

    @classmethod
    def t_one(cls, files: dict[str, str]) -> "_OnlineEngine":
        import sherpa_onnx

        return cls(
            sherpa_onnx.OnlineRecognizer.from_t_one_ctc(
                tokens=files["tokens"],
                model=files["model"],
                num_threads=NUM_THREADS,
                sample_rate=8000,
                enable_endpoint_detection=True,
            )
        )

    def session(self, samplerate: int) -> "_OnlineSession":
        return _OnlineSession(self.rec, samplerate)


class _OnlineSession:
    def __init__(self, rec, samplerate: int):
        self.rec = rec
        self.samplerate = samplerate  # частоту микрофона sherpa-onnx приводит к нужной сама
        self.stream = rec.create_stream()
        self.last_partial = ""

    def accept(self, data: bytes) -> list[Result]:
        self.stream.accept_waveform(self.samplerate, to_floats(data))
        while self.rec.is_ready(self.stream):
            self.rec.decode_stream(self.stream)
        text = self.rec.get_result(self.stream).strip()
        if self.rec.is_endpoint(self.stream):
            self.rec.reset(self.stream)
            self.last_partial = ""
            return [(text, True)] if text else []
        if text and text != self.last_partial:
            self.last_partial = text
            return [(text, False)]
        return []


class _VadEngine:
    """GigaAM распознаёт фразу целиком; фразы в звуке выделяет детектор речи Silero VAD."""

    def __init__(self, files: dict[str, str]):
        import sherpa_onnx

        self.rec = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
            model=files["model"], tokens=files["tokens"], num_threads=NUM_THREADS
        )
        self.vad_model = files["vad"]

    def session(self, samplerate: int) -> "_VadSession":
        import sherpa_onnx

        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = self.vad_model
        config.silero_vad.max_speech_duration = MAX_PHRASE_SECONDS
        config.sample_rate = VAD_SAMPLE_RATE
        vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=MAX_PHRASE_SECONDS * 2)
        return _VadSession(self.rec, vad, samplerate)


class _VadSession:
    def __init__(self, rec, vad, samplerate: int):
        self.rec = rec
        self.vad = vad
        self.resampler = Resampler(samplerate, VAD_SAMPLE_RATE)
        self.since_partial = 0  # отсчётов с последнего промежуточного распознавания
        self.last_partial = ""

    def accept(self, data: bytes) -> list[Result]:
        samples = self.resampler(to_floats(data))
        self.vad.accept_waveform(samples)
        results = []
        while not self.vad.empty():  # фраза закончилась
            text = self._decode(self.vad.front.samples)
            self.vad.pop()
            self.since_partial = 0
            self.last_partial = ""
            if text:
                results.append((text, True))
        if not self.vad.is_speech_detected():
            self.since_partial = 0
            return results
        # Фраза ещё звучит: время от времени распознаём то, что уже сказано,
        # чтобы слово засчитывалось сразу, а не после паузы.
        self.since_partial += len(samples)
        if self.since_partial >= PARTIAL_SECONDS * VAD_SAMPLE_RATE:
            self.since_partial = 0
            text = self._decode(self.vad.current_segment.samples)
            if text and text != self.last_partial:
                self.last_partial = text
                results.append((text, False))
        return results

    def _decode(self, samples) -> str:
        stream = self.rec.create_stream()
        stream.accept_waveform(VAD_SAMPLE_RATE, samples)
        self.rec.decode_stream(stream)
        return stream.result.text.strip()


class Resampler:
    """Приводит звук к другой частоте кусками, помня хвост предыдущего куска.

    Перед прореживанием звук сглаживается скользящим средним: иначе высокие
    частоты превратились бы в шум, который мешает распознаванию.
    """

    def __init__(self, source: int, target: int):
        self.step = source / target
        self.window = max(1, round(self.step))  # сглаживание только при понижении частоты
        self.history = [0.0] * (self.window - 1)  # последние отсчёты для скользящего среднего
        self.tail: list[float] = []  # сглаженные отсчёты, ещё нужные для интерполяции
        self.pos = 0.0  # где в tail + новых отсчётах стоит следующий выходной отсчёт

    def __call__(self, samples: list[float]) -> list[float]:
        if self.step == 1:
            return samples
        raw = self.history + samples
        smoothed = []
        total = sum(raw[: self.window - 1])
        for i in range(self.window - 1, len(raw)):
            total += raw[i]
            smoothed.append(total / self.window)
            total -= raw[i - self.window + 1]
        self.history = raw[len(raw) - (self.window - 1) :]

        buf = self.tail + smoothed
        out = []
        pos = self.pos
        while pos + 1 < len(buf):
            i = int(pos)
            frac = pos - i
            out.append(buf[i] + (buf[i + 1] - buf[i]) * frac)
            pos += self.step
        used = min(int(pos), len(buf))
        self.tail = buf[used:]
        self.pos = pos - used
        return out


_SHERPA = {
    SHERPA_TRANSDUCER: _OnlineEngine.transducer,
    SHERPA_T_ONE: _OnlineEngine.t_one,
    SHERPA_NEMO_CTC: _VadEngine,
}
