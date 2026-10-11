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

RU = "ru"
EN = "en"

SHERPA_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
# Ссылки на Hugging Face закреплены за коммитом: файлы модели не поменяются без нашего ведома.
VOSK_STREAMING_RU = (
    "https://huggingface.co/alphacep/vosk-model-streaming-ru/resolve/83bbf6f40059480e96251be8aed3d32bc7c80c33"
)


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

    @property
    def path(self) -> Path:
        return MODELS_DIR / self.id

    @property
    def installed(self) -> bool:
        return self.path.is_dir()

    def to_dict(self) -> dict:
        return asdict(self) | {"installed": self.installed}


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
        files=(f"{SHERPA_RELEASES}/silero_vad.onnx",),
        model_files={"model": "model.int8.onnx", "tokens": "tokens.txt", "vad": "silero_vad.onnx"},
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
]


def find_model(model_id: str) -> ModelInfo | None:
    return next((m for m in CATALOG if m.id == model_id), None)


def installed_models() -> list[ModelInfo]:
    return [m for m in CATALOG if m.installed]
