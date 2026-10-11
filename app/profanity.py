"""Поиск слов в распознанном тексте по списку корней (см. app/wordlists.py)."""

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\w+")
# Сколько мат должен продержаться в промежуточном тексте, чтобы засчитаться до конца фразы.
DEBOUNCE_SECONDS = 1.5

# Как часто проверять, не изменили ли файл списка (его правят, не закрывая приложение).
RELOAD_CHECK_SECONDS = 1.0

# Корни, загруженные load_words(); используются count_profanity по умолчанию.
_roots: tuple[str, ...] = ()
_source: Path | None = None  # файл, из которого они загружены
_stamp: tuple[int, int] | None = None  # его время изменения и размер при загрузке
_checked_at = 0.0


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def load_words(path: Path) -> tuple[str, ...]:
    """Читает корни из файла: по одному на строку, пустые строки и # пропускаются."""
    global _roots, _source, _stamp, _checked_at
    path = Path(path)
    _source, _stamp, _checked_at = path, _file_stamp(path), time.monotonic()
    try:
        _roots = read_roots(path)
    except OSError as e:
        log.error("Не удалось прочитать список слов %s: %s", path, e)
        _roots = ()
    log.info("Загружено корней: %d (%s)", len(_roots), path)
    return _roots


def read_roots(path: Path) -> tuple[str, ...]:
    """Корни из файла списка; OSError, если его не прочитать."""
    roots = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            roots.append(normalize(line))
    return tuple(dict.fromkeys(roots))  # без повторов, порядок сохраняем


def current_roots() -> tuple[str, ...]:
    """Загруженные корни; если файл с ними изменился, сначала перечитывает его."""
    global _checked_at
    if _source is None or time.monotonic() - _checked_at < RELOAD_CHECK_SECONDS:
        return _roots
    _checked_at = time.monotonic()
    stamp = _file_stamp(_source)
    # Удалённый (или как раз пересохраняемый) файл не трогаем: работаем со старым списком.
    if stamp is not None and stamp != _stamp:
        log.info("Список слов изменился, перечитываю")
        load_words(_source)
    return _roots


def _file_stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def count_profanity(text: str, roots: tuple[str, ...] | None = None) -> int:
    """Количество слов в тексте, начинающихся с одного из корней."""
    roots = current_roots() if roots is None else tuple(roots)
    if not roots:
        return 0
    words = _WORD_RE.findall(normalize(text))
    return sum(1 for word in words if word.startswith(roots))


class SwearTracker:
    """Считает маты по ходу фразы, не дожидаясь её конца.

    Vosk выдаёт окончательный текст фразы только после паузы и при этом часто
    переписывает её: при быстрой речи маты, которые были в промежуточном тексте,
    из окончательного пропадают. Поэтому мат, продержавшийся в промежуточном
    тексте DEBOUNCE_SECONDS, засчитывается сразу (дребезг распознавания —
    мелькнувшие на долю секунды слова — отсеивается), а окончательный текст
    добавляет только то, что ещё не засчитано в этой фразе.
    """

    def __init__(
        self,
        add: Callable[[int], Awaitable[object]],
        count: Callable[[str], int] = count_profanity,
        delay: float = DEBOUNCE_SECONDS,
        paused: Callable[[], bool] = lambda: False,
    ):
        self.add = add
        self.count = count
        self.delay = delay
        self.paused = paused  # на паузе текст пропускается
        self.counted = 0  # уже засчитано в текущей фразе
        self.partial = ""
        self._timer: asyncio.Task | None = None

    async def feed(self, text: str, is_final: bool) -> None:
        if self.paused():
            # Фразу, начатую до паузы или во время неё, после паузы не досчитываем.
            self.reset()
            return
        if not is_final:
            self.partial = text
            if self._timer is None and self.count(text) > self.counted:
                self._timer = asyncio.create_task(self._settle())
            return
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        found = self.count(text)
        new = found - self.counted
        # Сказанное не пишем в журнал на диске: текст виден только в консоли разработчика (DEBUG).
        log.debug("Распознано: %r", text)
        log.info("Фраза: найдено %d, уже засчитано по ходу фразы: %d", found, self.counted)
        self.counted, self.partial = 0, ""
        if new > 0:
            await self.add(new)

    async def _settle(self) -> None:
        await asyncio.sleep(self.delay)
        self._timer = None  # дальше не отменяем: засчитанное уже не вернуть
        new = self.count(self.partial) - self.counted
        if new > 0:
            self.counted += new
            log.debug("Промежуточный текст: %r", self.partial)
            log.info("Засчитано по ходу фразы: %d", new)
            await self.add(new)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def reset(self) -> None:
        """Забывает текущую фразу: незасчитанное в ней уже не засчитается."""
        self.stop()
        self.counted, self.partial = 0, ""
