"""Облачное распознавание: запросы к сервисам и разбор ответов без сети."""

import io
import json
import urllib.error
import wave
from types import SimpleNamespace

import pytest

from app.stt import cloud, engines
from app.stt.catalog import CATALOG, CLOUD, EN, RU, find_model
from app.stt.cloud import PROVIDERS, CloudError, CloudRecognizer, build_request, clean_key, parse_response


def headers_of(request):
    return {k.lower(): v for k, v in request.header_items()}


def samples(seconds: float, value: float = 0.1):
    return [value] * int(cloud.SAMPLE_RATE * seconds)


# --- ключ ---


@pytest.mark.parametrize("raw, expected", [("  abc123 ", "abc123"), ("a" * 512, "a" * 512)])
def test_clean_key(raw, expected):
    assert clean_key(raw) == expected


@pytest.mark.parametrize("raw", [None, 5, "", "  ", "a b", "a\nb", "ключ", "a" * 513, "k\x00"])
def test_clean_key_rejects(raw):
    assert clean_key(raw) is None


# --- звук и тело запроса ---


def test_to_wav_is_16khz_mono_16bit():
    data = cloud.to_wav([0.0, 1.0, -1.0, 0.5, 5.0])  # 5.0 обрезается до 1.0
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
        frames = wav.readframes(wav.getnframes())
    values = [int.from_bytes(frames[i : i + 2], "little", signed=True) for i in range(0, len(frames), 2)]
    assert values == [0, 32767, -32767, 16383, 32767]


def test_multipart_has_fields_and_file():
    body, content_type = cloud.multipart({"model": "m", "language": "ru"}, "p.wav", b"RIFFDATA", "audio/wav")
    boundary = content_type.split("boundary=")[1]
    assert content_type.startswith("multipart/form-data")
    text = body.decode("latin-1")
    assert f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nm\r\n' in text
    assert 'name="language"\r\n\r\nru' in text
    assert 'name="file"; filename="p.wav"\r\nContent-Type: audio/wav\r\n\r\nRIFFDATA\r\n' in text
    assert text.endswith(f"--{boundary}--\r\n")


# --- запросы по сервисам ---


def test_openai_request():
    request = build_request(PROVIDERS["openai"], "whisper-1", "ru", "KEY", b"wav")
    assert request.full_url == "https://api.openai.com/v1/audio/transcriptions"
    assert headers_of(request)["authorization"] == "Bearer KEY"
    assert headers_of(request)["content-type"].startswith("multipart/form-data")
    assert b'name="model"\r\n\r\nwhisper-1' in request.data
    assert b'name="language"\r\n\r\nru' in request.data
    assert request.get_method() == "POST"


def test_groq_uses_openai_api_on_its_own_host():
    request = build_request(PROVIDERS["groq"], "whisper-large-v3-turbo", "en", "K", b"wav")
    assert request.full_url == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert headers_of(request)["authorization"] == "Bearer K"
    assert b"whisper-large-v3-turbo" in request.data


def test_deepgram_request_sends_raw_wav():
    request = build_request(PROVIDERS["deepgram"], "nova-2", "ru", "KEY", b"WAVBYTES")
    assert request.full_url.startswith("https://api.deepgram.com/v1/listen?")
    assert "model=nova-2" in request.full_url and "language=ru" in request.full_url
    assert headers_of(request)["authorization"] == "Token KEY"
    assert headers_of(request)["content-type"] == "audio/wav"
    assert request.data == b"WAVBYTES"


def test_elevenlabs_request():
    request = build_request(PROVIDERS["elevenlabs"], "scribe_v2", "en", "KEY", b"wav")
    assert request.full_url == "https://api.elevenlabs.io/v1/speech-to-text"
    assert headers_of(request)["xi-api-key"] == "KEY"
    assert b'name="model_id"\r\n\r\nscribe_v2' in request.data
    assert b'name="language_code"\r\n\r\nen' in request.data


def test_key_is_never_in_the_url():
    for provider in PROVIDERS.values():
        assert "SECRETKEY" not in build_request(provider, "m", "ru", "SECRETKEY", b"w").full_url


# --- ответы ---


def test_parse_openai_like_and_elevenlabs():
    assert parse_response(PROVIDERS["openai"], {"text": " привет мир "}) == "привет мир"
    assert parse_response(PROVIDERS["elevenlabs"], {"text": "hi"}) == "hi"
    assert parse_response(PROVIDERS["groq"], {}) == ""
    assert parse_response(PROVIDERS["openai"], {"text": None}) == ""


def test_parse_deepgram():
    payload = {"results": {"channels": [{"alternatives": [{"transcript": " hello "}]}]}}
    assert parse_response(PROVIDERS["deepgram"], payload) == "hello"
    assert parse_response(PROVIDERS["deepgram"], {"results": {"channels": []}}) == ""
    assert parse_response(PROVIDERS["deepgram"], {}) == ""


# --- сеть ---


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def network(monkeypatch):
    state = SimpleNamespace(calls=[], outcome=FakeResponse({"text": "мат"}))

    def urlopen(request, timeout=None):
        state.calls.append((request, timeout))
        if isinstance(state.outcome, Exception):
            raise state.outcome
        return state.outcome

    monkeypatch.setattr(cloud.urllib.request, "urlopen", urlopen)
    return state


def http_error(code, body=b"nope"):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))


def test_transcribe_returns_text(network):
    text = cloud.transcribe(PROVIDERS["openai"], "whisper-1", "ru", "K", samples(1))
    assert text == "мат"
    assert network.calls[0][1] == cloud.REQUEST_TIMEOUT


@pytest.mark.parametrize("code", [401, 402, 403])
def test_auth_and_billing_errors_are_fatal(network, code):
    network.outcome = http_error(code, b'{"error":"bad key"}')
    with pytest.raises(CloudError) as e:
        cloud.transcribe(PROVIDERS["deepgram"], "nova-2", "ru", "K", samples(1))
    assert e.value.fatal
    assert str(code) in str(e.value)


@pytest.mark.parametrize("code", [429, 500, 503])
def test_other_http_errors_are_not_fatal(network, code):
    network.outcome = http_error(code)
    with pytest.raises(CloudError) as e:
        cloud.transcribe(PROVIDERS["openai"], "m", "ru", "K", samples(1))
    assert not e.value.fatal


def test_network_down_and_garbage_are_not_fatal(network):
    network.outcome = urllib.error.URLError("нет сети")
    with pytest.raises(CloudError) as e:
        cloud.transcribe(PROVIDERS["openai"], "m", "ru", "K", samples(1))
    assert not e.value.fatal
    network.outcome = FakeResponse(b"<html>")
    with pytest.raises(CloudError):
        cloud.transcribe(PROVIDERS["openai"], "m", "ru", "K", samples(1))


def test_error_message_does_not_contain_key(network):
    network.outcome = http_error(401)
    with pytest.raises(CloudError) as e:
        cloud.transcribe(PROVIDERS["openai"], "m", "ru", "SECRETKEY", samples(1))
    assert "SECRETKEY" not in str(e.value)


# --- CloudRecognizer: интерфейс OfflineRecognizer для _VadSession ---


def decode(rec, seconds):
    stream = rec.create_stream()
    stream.accept_waveform(16000, samples(seconds))
    rec.decode_stream(stream)
    return stream.result.text


def test_recognizer_decodes_phrase(network):
    rec = CloudRecognizer(PROVIDERS["openai"], "whisper-1", "ru", "K")
    assert decode(rec, 1.0) == "мат"


def test_too_short_phrase_is_not_sent(network):
    rec = CloudRecognizer(PROVIDERS["openai"], "whisper-1", "ru", "K")
    assert decode(rec, 0.1) == ""
    assert network.calls == []


def test_transient_error_skips_phrase(network):
    network.outcome = http_error(500)
    rec = CloudRecognizer(PROVIDERS["openai"], "whisper-1", "ru", "K")
    assert decode(rec, 1.0) == ""
    assert rec.skipped == 1


def test_fatal_error_propagates(network):
    network.outcome = http_error(401)
    rec = CloudRecognizer(PROVIDERS["openai"], "whisper-1", "ru", "K")
    with pytest.raises(CloudError):
        decode(rec, 1.0)


# --- каталог и движок ---


def cloud_models():
    return [m for m in CATALOG if m.engine == CLOUD]


def test_every_provider_and_language_has_models():
    for provider in PROVIDERS:
        for language in (RU, EN):
            assert any(m.provider == provider and m.language == language for m in cloud_models())


def test_cloud_models_are_consistent():
    for model in cloud_models():
        assert model.cloud
        assert model.provider in PROVIDERS
        assert model.api_model
        assert model.id.startswith("cloud-") and model.id.endswith(f"-{model.language}")
        assert model.model_files == {"vad": "silero_vad.onnx"}
        assert model.to_dict()["cloud"] is True


def test_cloud_model_needs_a_key(models_dir):
    model = find_model("cloud-deepgram-nova-2-ru")
    with pytest.raises(ValueError):
        engines.load_engine(str(model.path))
    with pytest.raises(ValueError):
        engines.load_engine(str(model.path), api_key="")
