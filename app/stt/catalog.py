"""Каталог моделей распознавания, которые можно выбрать на странице управления.

Модель доступна, если её папка `id` распакована в models/. Нескачанную
модель приложение скачивает само по ссылке url (см. downloader.py). Порядок списка —
порядок в выпадающем списке; первая установленная модель — модель по умолчанию.
"""

from dataclasses import asdict, dataclass
from pathlib import Path

from ..paths import MODELS_DIR


@dataclass(frozen=True)
class ModelInfo:
    id: str  # имя папки в models/
    engine: str  # движок распознавания; пока только "vosk"
    title: str  # название в списке
    name: str  # техническое название (движок и версия), показывается в скобках
    summary: str  # короткая подпись рядом с названием
    description: str  # подробности, показываются по кнопке «Подробнее»
    disk: str  # размер распакованной модели
    download_size: str  # размер архива, который скачивается
    memory: str
    load_time: str
    url: str  # откуда скачать архив

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
        engine="vosk",
        title="Маленькая",
        name="Vosk small-ru 0.22",
        summary="быстрая, мало памяти",
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
        id="vosk-model-ru-0.42",
        engine="vosk",
        title="Большая",
        name="Vosk ru 0.42",
        summary="точная, много памяти",
        description=(
            "Ошибается в 1,5–2,5 раза реже маленькой и лучше понимает разговорную речь. "
            "Требует много оперативной памяти и заметнее нагружает процессор: "
            "на слабом компьютере может мешать игре и трансляции."
        ),
        disk="3,5 ГБ",
        download_size="1,8 ГБ",
        memory="~5,5 ГБ",
        load_time="1,5–2 мин",
        url="https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip",
    ),
]


def find_model(model_id: str) -> ModelInfo | None:
    return next((m for m in CATALOG if m.id == model_id), None)


def installed_models() -> list[ModelInfo]:
    return [m for m in CATALOG if m.installed]
