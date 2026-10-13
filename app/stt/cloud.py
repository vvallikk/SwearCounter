"""Облачное распознавание: фраза уходит на сервис по API, текст возвращается.

В отличие от остальных движков, здесь звук покидает компьютер, поэтому облачные
модели включаются только после того, как пользователь сам ввёл API-ключ сервиса.

Фразы выделяет тот же локальный детектор речи (Silero VAD), что у Whisper и GigaAM:
в облако уходят только законченные фразы, а тишина не оплачивается. Каждая фраза —
один запрос; промежуточных результатов нет (за них пришлось бы платить многократно).

Сервисы (запросы только по HTTPS, без сторонних библиотек):
    openai      /v1/audio/transcriptions, multipart, Bearer-ключ
    groq        то же API, что у OpenAI (Whisper на серверах Groq)
    deepgram    /v1/listen, WAV в теле запроса, заголовок «Token»
    elevenlabs  /v1/speech-to-text, multipart, заголовок xi-api-key
"""

import array
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from dataclasses import dataclass
from io import BytesIO

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
REQUEST_TIMEOUT = 20  # секунд на один запрос: зависшая сеть не должна блокировать счётчик
MIN_PHRASE_SECONDS = 0.25  # короче — щелчок или вдох: платить за такое незачем
MAX_KEY_LENGTH = 512

# Ответы, после которых повторять нечего: ключ не подходит или закончились деньги.
# Остальные ошибки (сеть, перегрузка, лимит запросов) пропускают только одну фразу.
FATAL_STATUSES = (401, 402, 403)


@dataclass(frozen=True)
class Provider:
    id: str
    title: str
    api: str  # способ обращения: openai, deepgram, elevenlabs
    url: str
    keys_page: str  # где пользователь берёт ключ


PROVIDERS = {
    p.id: p
    for p in (
        Provider("openai", "OpenAI", "openai", "https://api.openai.com/v1/audio/transcriptions",
                 "https://platform.openai.com/api-keys"),
        Provider("groq", "Groq", "openai", "https://api.groq.com/openai/v1/audio/transcriptions",
                 "https://console.groq.com/keys"),
        Provider("deepgram", "Deepgram", "deepgram", "https://api.deepgram.com/v1/listen",
                 "https://console.deepgram.com/"),
        Provider("elevenlabs", "ElevenLabs", "elevenlabs", "https://api.elevenlabs.io/v1/speech-to-text",
                 "https://elevenlabs.io/app/settings/api-keys"),
    )
}


class CloudError(Exception):
    """Запрос в облако не удался; fatal — повторять бесполезно (ключ, оплата)."""

    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


def clean_key(key: object) -> str | None:
    """Ключ без пробелов по краям, если он похож на ключ; иначе None.

    Ключ идёт в заголовок запроса, поэтому пробелы внутри, переводы строк и не-ASCII
    не пропускаем: так в заголовок не попадёт лишнее.
    """
    if not isinstance(key, str):
        return None
    key = key.strip()
    if not key or len(key) > MAX_KEY_LENGTH:
        return None
    if not (key.isascii() and key.isprintable()) or any(c.isspace() for c in key):
        return None
    return key


def to_wav(samples) -> bytes:
    """Звук (числа от -1 до 1, 16 кГц) в WAV 16 бит, моно."""
    pcm = array.array("h", (int(max(-1.0, min(1.0, v)) * 32767) for v in samples))
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue()


def multipart(fields: dict[str, str], filename: str, content: bytes, content_type: str) -> tuple[bytes, str]:
    """Тело multipart/form-data: текстовые поля и один файл `file`."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def build_request(provider: Provider, model: str, language: str, key: str, wav: bytes) -> urllib.request.Request:
    if provider.api == "deepgram":
        query = urllib.parse.urlencode({"model": model, "language": language, "smart_format": "false"})
        return urllib.request.Request(
            f"{provider.url}?{query}",
            data=wav,
            method="POST",
            headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"},
        )
    if provider.api == "elevenlabs":
        fields = {"model_id": model, "language_code": language}
        headers = {"xi-api-key": key}
    else:  # openai, groq
        fields = {"model": model, "language": language, "response_format": "json"}
        headers = {"Authorization": f"Bearer {key}"}
    body, content_type = multipart(fields, "phrase.wav", wav, "audio/wav")
    return urllib.request.Request(
        provider.url, data=body, method="POST", headers=headers | {"Content-Type": content_type}
    )


def parse_response(provider: Provider, payload: dict) -> str:
    """Текст фразы из ответа сервиса; пустая строка, если речи не нашлось."""
    if provider.api == "deepgram":
        try:
            return payload["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
        except (KeyError, IndexError, TypeError, AttributeError):
            return ""
    text = payload.get("text") if isinstance(payload, dict) else None
    return text.strip() if isinstance(text, str) else ""


def transcribe(provider: Provider, model: str, language: str, key: str, samples) -> str:
    """Отправляет фразу в облако и возвращает распознанный текст."""
    request = build_request(provider, model, language, key, to_wav(samples))
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310 https из каталога
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read(300).decode("utf-8", "replace").strip()
        raise CloudError(
            f"{provider.title}: ответ {e.code}. {detail}", fatal=e.code in FATAL_STATUSES
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CloudError(f"{provider.title}: нет связи с сервером ({e})") from None
    except ValueError:
        raise CloudError(f"{provider.title}: непонятный ответ сервера") from None
    return parse_response(provider, payload)


class CloudRecognizer:
    """Те же три метода, что у OfflineRecognizer из sherpa-onnx: его место занимает в _VadSession."""

    def __init__(self, provider: Provider, model: str, language: str, key: str):
        self.provider = provider
        self.model = model
        self.language = language
        self.key = key
        self.skipped = 0  # фраз, пропущенных из-за сбоев: для журнала, чтобы не засорять его

    def create_stream(self):
        return _Stream()

    def decode_stream(self, stream) -> None:
        if len(stream.samples) < MIN_PHRASE_SECONDS * SAMPLE_RATE:
            return
        try:
            stream.result.text = transcribe(self.provider, self.model, self.language, self.key, stream.samples)
        except CloudError as e:
            if e.fatal:
                raise
            self.skipped += 1
            if self.skipped <= 3 or self.skipped % 20 == 0:
                log.warning("Фраза не распознана (всего пропущено %d): %s", self.skipped, e)


class _Result:
    text = ""


class _Stream:
    def __init__(self):
        self.samples = ()
        self.result = _Result()

    def accept_waveform(self, sample_rate: int, samples) -> None:
        self.samples = samples
