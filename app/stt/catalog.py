"""Каталог моделей распознавания, которые можно выбрать на странице управления.

Модель доступна, если её папка `id` распакована в models/. Нескачанную
модель приложение скачивает само (см. downloader.py): архив url и/или отдельные
файлы files. Порядок списка — порядок на странице, от лёгких моделей к тяжёлым
(сначала русские, потом английские); первая установленная модель — модель по умолчанию.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..paths import MODELS_DIR

# Движки распознавания (см. engines.py). sherpa-* — разные виды моделей sherpa-onnx.
VOSK = "vosk"
SHERPA_TRANSDUCER = "sherpa-transducer"  # потоковая Zipformer: encoder, decoder, joiner
SHERPA_T_ONE = "sherpa-t-one"  # потоковая CTC-модель T-one
SHERPA_NEMO_CTC = "sherpa-nemo-ctc"  # распознаёт фразу целиком; фразы выделяет VAD
SHERPA_WHISPER = "sherpa-whisper"  # Whisper: тоже фразами через VAD, язык речи из language
CLOUD = "cloud"  # облачный сервис по API (cloud.py); локально лежит только детектор речи

RU = "ru"
EN = "en"

SHERPA_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
# Ссылки на Hugging Face закреплены за коммитом: файлы модели не поменяются без нашего ведома.
VOSK_STREAMING_RU = (
    "https://huggingface.co/alphacep/vosk-model-streaming-ru/resolve/83bbf6f40059480e96251be8aed3d32bc7c80c33"
)
WHISPER_SMALL = (
    "https://huggingface.co/csukuangfj/sherpa-onnx-whisper-small/resolve/8f3c18b358db4d1f2fc1eae49d75cd20989e4309"
)
WHISPER_SMALL_EN = (
    "https://huggingface.co/csukuangfj/sherpa-onnx-whisper-small.en/resolve/d9533f69affd85061aee349af7fea5cb2996dbbe"
)
SILERO_VAD = f"{SHERPA_RELEASES}/silero_vad.onnx"


@dataclass(frozen=True)
class ModelInfo:
    id: str  # имя папки в models/
    engine: str  # движок распознавания: VOSK или один из SHERPA_*
    title: str  # название в списке
    name: str  # техническое название (движок и версия), показывается в скобках
    summary: str  # короткая подпись рядом с названием
    description: str  # подробности, показываются по кнопке «Подробнее»
    disk: str  # размер распакованной модели
    download_size: str  # сколько скачивается
    memory: str
    load_time: str
    # Архив (.zip или .tar.bz2) с папкой id внутри; пусто, если модель качается по файлам.
    url: str
    # Отдельные файлы: кладутся в папку модели под своими именами (после распаковки url).
    files: tuple[str, ...] = ()
    # Файлы модели для sherpa-onnx: роль (encoder, model, tokens, vad...) → путь в папке модели.
    model_files: dict[str, str] = field(default_factory=dict, hash=False)
    language: str = "ru"  # язык речи: RU или EN
    provider: str = ""  # облачные модели: сервис из cloud.PROVIDERS
    api_model: str = ""  # облачные модели: имя модели у сервиса

    @property
    def cloud(self) -> bool:
        return self.engine == CLOUD

    @property
    def path(self) -> Path:
        return MODELS_DIR / self.id

    @property
    def installed(self) -> bool:
        return self.path.is_dir()

    def to_dict(self) -> dict:
        return asdict(self) | {"installed": self.installed, "cloud": self.cloud}


CATALOG = [
    ModelInfo(
        id="vosk-model-small-ru-0.22",
        engine=VOSK,
        title="Базовая",
        name="Vosk small-ru 0.22",
        summary="классическая Vosk, работает везде",
        description=(
            "Загружается за секунду и почти не нагружает компьютер во время игры или стрима. "
            "Распознаёт хуже: путает похожие слова, хуже справляется с быстрой речью, "
            "шумом и редкими словами, поэтому часть слов может не засчитаться."
        ),
        disk="90 МБ",
        download_size="45 МБ",
        memory="~0,3 ГБ",
        load_time="~1 с",
        url="https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip",
    ),
    ModelInfo(
        id="sherpa-onnx-streaming-zipformer-small-ru-vosk-int8-2025-08-16",
        engine=SHERPA_TRANSDUCER,
        title="Экономная",
        name="Vosk Streaming small, Zipformer",
        summary="самая лёгкая, для слабых ПК",
        description=(
            "Новая модель от авторов Vosk на современной архитектуре. Скачивается быстрее всех "
            "и занимает меньше памяти, чем базовая, а слова обычно распознаёт точнее. "
            "Почти не нагружает компьютер."
        ),
        disk="30 МБ",
        download_size="24 МБ",
        memory="~0,15 ГБ",
        load_time="~1 с",
        url=f"{SHERPA_RELEASES}/sherpa-onnx-streaming-zipformer-small-ru-vosk-int8-2025-08-16.tar.bz2",
        model_files={
            "encoder": "encoder.int8.onnx",
            "decoder": "decoder.onnx",
            "joiner": "joiner.int8.onnx",
            "tokens": "tokens.txt",
        },
    ),
    ModelInfo(
        id="vosk-model-streaming-ru-0.56",
        engine=SHERPA_TRANSDUCER,
        title="Сбалансированная",
        name="Vosk Streaming 0.56, Zipformer",
        summary="хорошая точность при малой памяти",
        description=(
            "Старшая версия экономной модели от авторов Vosk: крупнее и точнее, особенно на "
            "разговорной речи. Памяти занимает всё ещё немного, поэтому подойдёт, если модель "
            "для мощных ПК слишком тяжела для компьютера."
        ),
        disk="70 МБ",
        download_size="72 МБ",
        memory="~0,2 ГБ",
        load_time="~2 с",
        url="",
        files=(
            f"{VOSK_STREAMING_RU}/am-onnx/encoder.int8.onnx",
            f"{VOSK_STREAMING_RU}/am-onnx/decoder.int8.onnx",
            f"{VOSK_STREAMING_RU}/am-onnx/joiner.int8.onnx",
            f"{VOSK_STREAMING_RU}/lang/tokens.txt",
        ),
        model_files={
            "encoder": "encoder.int8.onnx",
            "decoder": "decoder.int8.onnx",
            "joiner": "joiner.int8.onnx",
            "tokens": "tokens.txt",
        },
    ),
    ModelInfo(
        id="sherpa-onnx-streaming-t-one-russian-2025-09-08",
        engine=SHERPA_T_ONE,
        title="Разговорная",
        name="T-one, Т-Банк",
        summary="для живой быстрой речи",
        description=(
            "Модель Т-Банка, обученная на живой разговорной речи, в том числе на звонках. "
            "Хорошо понимает быструю и не очень чёткую речь. Процессор нагружает немного "
            "сильнее экономной и сбалансированной, но для игр и стримов это незаметно."
        ),
        disk="140 МБ",
        download_size="128 МБ",
        memory="~0,5 ГБ",
        load_time="~1 с",
        url=f"{SHERPA_RELEASES}/sherpa-onnx-streaming-t-one-russian-2025-09-08.tar.bz2",
        model_files={"model": "model.onnx", "tokens": "tokens.txt"},
    ),
    ModelInfo(
        id="sherpa-onnx-nemo-ctc-giga-am-v3-russian-2025-12-16",
        engine=SHERPA_NEMO_CTC,
        title="Самая точная",
        name="GigaAM v3, Сбер",
        summary="лучшее распознавание, текст фразами",
        description=(
            "Модель Сбера, одна из самых точных для русского языка, а памяти занимает в разы "
            "меньше модели для мощных ПК. Распознаёт речь целыми фразами, поэтому текст обновляется "
            "примерно раз в секунду, а не после каждого слова."
        ),
        disk="215 МБ",
        download_size="164 МБ",
        memory="~0,4 ГБ",
        load_time="~1 с",
        url=f"{SHERPA_RELEASES}/sherpa-onnx-nemo-ctc-giga-am-v3-russian-2025-12-16.tar.bz2",
        # Детектор речи (Silero VAD) выделяет фразы, которые потом распознаёт модель.
        files=(SILERO_VAD,),
        model_files={"model": "model.int8.onnx", "tokens": "tokens.txt", "vad": "silero_vad.onnx"},
    ),
    ModelInfo(
        id="sherpa-onnx-whisper-small",
        engine=SHERPA_WHISPER,
        title="Устойчивая к шуму",
        name="Whisper small, OpenAI",
        summary="понимает речь сквозь шум и музыку",
        description=(
            "Модель Whisper от OpenAI, обученная на сотнях тысяч часов речи со всего интернета. "
            "Хорошо понимает речь сквозь шум, музыку и акценты. Распознаёт фразами, как самая точная, "
            "но процессор нагружает заметно сильнее: на слабом компьютере может мешать игре."
        ),
        disk="365 МБ",
        download_size="360 МБ",
        memory="~0,9 ГБ",
        load_time="~1 с",
        url="",
        files=(
            f"{WHISPER_SMALL}/small-encoder.int8.onnx",
            f"{WHISPER_SMALL}/small-decoder.int8.onnx",
            f"{WHISPER_SMALL}/small-tokens.txt",
            SILERO_VAD,
        ),
        model_files={
            "encoder": "small-encoder.int8.onnx",
            "decoder": "small-decoder.int8.onnx",
            "tokens": "small-tokens.txt",
            "vad": "silero_vad.onnx",
        },
    ),
    ModelInfo(
        id="vosk-model-ru-0.42",
        engine=VOSK,
        title="Для мощных ПК",
        name="Vosk ru 0.42",
        summary="точная, но нужно 5,5 ГБ памяти",
        description=(
            "Ошибается в 1,5–2,5 раза реже базовой и лучше понимает разговорную речь. "
            "Требует много оперативной памяти и заметнее нагружает процессор: "
            "на слабом компьютере может мешать игре и трансляции."
        ),
        disk="3,5 ГБ",
        download_size="1,8 ГБ",
        memory="~5,5 ГБ",
        load_time="1,5–2 мин",
        url="https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip",
    ),
    # --- Английская речь ---
    ModelInfo(
        id="vosk-model-small-en-us-0.15",
        engine=VOSK,
        language=EN,
        title="Базовая",
        name="Vosk small-en-us 0.15",
        summary="классическая Vosk, работает везде",
        description=(
            "Загружается за секунду и почти не нагружает компьютер во время игры или стрима. "
            "Распознаёт хуже остальных: с быстрой речью и шумом часть слов может не засчитаться."
        ),
        disk="70 МБ",
        download_size="40 МБ",
        memory="~0,3 ГБ",
        load_time="~1 с",
        url="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
    ),
    ModelInfo(
        id="sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06",
        engine=SHERPA_TRANSDUCER,
        language=EN,
        title="Современная",
        name="Kroko Streaming, Zipformer",
        summary="точнее базовой при малой памяти",
        description=(
            "Новая потоковая модель на современной архитектуре: слова распознаёт точнее базовой, "
            "особенно в разговорной речи, а памяти занимает немного."
        ),
        disk="70 МБ",
        download_size="55 МБ",
        memory="~0,3 ГБ",
        load_time="~2 с",
        url=f"{SHERPA_RELEASES}/sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06.tar.bz2",
        model_files={
            "encoder": "encoder.onnx",
            "decoder": "decoder.onnx",
            "joiner": "joiner.onnx",
            "tokens": "tokens.txt",
        },
    ),
    ModelInfo(
        id="vosk-model-en-us-0.22-lgraph",
        engine=VOSK,
        language=EN,
        title="Точная",
        name="Vosk en-us 0.22 lgraph",
        summary="крупнее базовой, с большим словарём",
        description=(
            "Старшая модель Vosk с большим словарём: реже путает похожие слова и лучше "
            "узнаёт редкие. Памяти и процессора нужно чуть больше, чем базовой."
        ),
        disk="205 МБ",
        download_size="125 МБ",
        memory="~0,5 ГБ",
        load_time="~1 с",
        url="https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip",
    ),
    ModelInfo(
        id="sherpa-onnx-whisper-small.en",
        engine=SHERPA_WHISPER,
        language=EN,
        title="Устойчивая к шуму",
        name="Whisper small.en, OpenAI",
        summary="понимает речь сквозь шум и музыку",
        description=(
            "Английская модель Whisper от OpenAI, обученная на сотнях тысяч часов речи. "
            "Обычно точнее остальных английских моделей и лучше понимает речь сквозь шум, музыку "
            "и акценты. Распознаёт фразами и заметно сильнее нагружает процессор: "
            "на слабом компьютере может мешать игре."
        ),
        disk="365 МБ",
        download_size="360 МБ",
        memory="~0,9 ГБ",
        load_time="~1 с",
        url="",
        files=(
            f"{WHISPER_SMALL_EN}/small.en-encoder.int8.onnx",
            f"{WHISPER_SMALL_EN}/small.en-decoder.int8.onnx",
            f"{WHISPER_SMALL_EN}/small.en-tokens.txt",
            SILERO_VAD,
        ),
        model_files={
            "encoder": "small.en-encoder.int8.onnx",
            "decoder": "small.en-decoder.int8.onnx",
            "tokens": "small.en-tokens.txt",
            "vad": "silero_vad.onnx",
        },
    ),
]


# Облачные модели: (сервис, имя у сервиса, название, подпись, описание).
_CLOUD_MODELS = [
    (
        "deepgram", "nova-2", "Nova-2", "быстрая и недорогая, от Deepgram",
        "Проверенная модель Deepgram: распознаёт быстро, цена за минуту невысокая. "
        "Подходит, если нужна скорость и недорого.",
    ),
    (
        "deepgram", "nova-3", "Nova-3", "новая модель Deepgram, точнее Nova-2",
        "Новая модель Deepgram: точнее Nova-2, лучше справляется с шумом и разговорной речью.",
    ),
    (
        "openai", "gpt-4o-mini-transcribe", "GPT-4o mini Transcribe", "экономная модель OpenAI",
        "Облегчённая модель OpenAI: точнее исходного Whisper и дешевле GPT-4o Transcribe.",
    ),
    (
        "openai", "gpt-4o-transcribe", "GPT-4o Transcribe", "самая точная у OpenAI",
        "Самая точная модель распознавания OpenAI. Стоит дороже остальных у этого сервиса.",
    ),
    (
        "openai", "whisper-1", "Whisper", "классический Whisper через API OpenAI",
        "Whisper large-v2, работающий на серверах OpenAI: нагрузки на компьютер нет совсем.",
    ),
    (
        "groq", "whisper-large-v3-turbo", "Whisper large-v3 turbo", "Whisper на Groq, очень быстро и дёшево",
        "Whisper large-v3 turbo на серверах Groq: самый дешёвый способ получить Whisper, "
        "работает быстро. Сервис округляет каждый запрос до 10 секунд, поэтому короткие "
        "фразы обходятся как десятисекундные.",
    ),
    (
        "groq", "whisper-large-v3", "Whisper large-v3", "самый точный Whisper на Groq",
        "Полная Whisper large-v3 на серверах Groq: точнее turbo-версии. Сервис округляет "
        "каждый запрос до 10 секунд.",
    ),
    (
        "elevenlabs", "scribe_v2", "Scribe v2", "модель ElevenLabs",
        "Модель распознавания речи ElevenLabs, точная на многих языках, в том числе на русском.",
    ),
]


def _cloud_catalog() -> list[ModelInfo]:
    from .cloud import PROVIDERS

    models = []
    for language in (RU, EN):
        for provider_id, api_model, name, summary, description in _CLOUD_MODELS:
            provider = PROVIDERS[provider_id]
            models.append(
                ModelInfo(
                    id=f"cloud-{provider_id}-{api_model}-{language}",
                    engine=CLOUD,
                    language=language,
                    title=f"Облако: {provider.title}",
                    name=name,
                    summary=summary,
                    description=(
                        f"{description} Звук ваших фраз отправляется в {provider.title} и оплачивается "
                        "по вашему API-ключу. Остальное распознавание остаётся на компьютере: "
                        "в облако уходят только законченные фразы. Нужен интернет."
                    ),
                    disk="2 МБ",
                    download_size="2 МБ",
                    memory="—",
                    load_time="—",
                    url="",
                    # Локально нужен только детектор речи, который выделяет фразы.
                    files=(SILERO_VAD,),
                    model_files={"vad": "silero_vad.onnx"},
                    provider=provider_id,
                    api_model=api_model,
                )
            )
    return models


# Облачные модели — в конце своего языка: страница группирует модели по языку.
for _model in _cloud_catalog():
    _last = max(i for i, m in enumerate(CATALOG) if m.language == _model.language)
    CATALOG.insert(_last + 1, _model)


def find_model(model_id: str) -> ModelInfo | None:
    return next((m for m in CATALOG if m.id == model_id), None)


def installed_models() -> list[ModelInfo]:
    return [m for m in CATALOG if m.installed]
