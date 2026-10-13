"""Отдельный процесс распознавания: модель, микрофон и распознавание.

Процесс нужен, чтобы загрузку модели можно было прервать в любой момент:
поток остановить нельзя, а процесс можно завершить, и Windows сразу вернёт
всю его память. Связь с основным процессом — два канала (Pipe).

Результаты (results), кортежами:

    ("loaded", секунды)               модель загружена в память
    ("listening", микрофон, частота)  микрофон открыт, идёт распознавание
    ("mic_error", описание)           микрофон не открылся; модель остаётся
                                      в памяти и ждёт другой микрофон
    ("text", текст, is_final)         распознанный текст
    ("level", пик)                    громкость последнего куска звука, 0..1
    ("monitor", включено, ошибка)     прослушивание включилось/выключилось;
                                      ошибка — строка, если не удалось
    ("error", описание)               ошибка; процесс после неё завершается

Команды (commands):

    ("device", микрофон)              переключиться на другой микрофон
                                      (полное имя, номер или None — по умолчанию);
                                      прослушивание при этом выключается
    ("monitor", включить)             проигрывать звук микрофона в системные
                                      динамики/наушники (True/False)
"""

import array
import multiprocessing
import os
import queue
import threading
import time
import traceback
from multiprocessing.connection import Connection

BLOCK_SECONDS = 0.1  # длина куска звука: распознавателю и для индикатора громкости
MONITOR_MAX_SECONDS = 0.3  # больше в очереди прослушивания не копим, иначе растёт задержка
SILENCE_TIMEOUT = 3.0  # столько секунд без звука — повод проверить, жив ли микрофон


class MicrophoneLost(Exception):
    pass


def run_worker(
    results: Connection,
    commands: Connection,
    model_path: str,
    device: int | str | None,
    api_key: str | None = None,
) -> None:
    _exit_with_parent()
    try:
        _Worker(results, commands, device).run(model_path, api_key)
    except (BrokenPipeError, EOFError):
        pass  # основной процесс закрыл канал: распознавание больше не нужно
    except Exception:
        _send_error(results)


class _Worker:
    def __init__(self, results: Connection, commands: Connection, device: int | str | None):
        self.results = results
        # Куски звука из микрофона; None — сигнал «пришла команда».
        self.chunks: queue.Queue[bytes | None] = queue.Queue()
        self._lock = threading.Lock()
        self._pending_device = device
        self._device_changed = False  # пришла команда сменить микрофон
        self._monitor_wanted = False  # меняет поток команд, применяет основной цикл
        self.monitor = _Monitor()
        threading.Thread(target=self._read_commands, args=(commands,), daemon=True).start()

    def run(self, model_path: str, api_key: str | None = None) -> None:
        # Импорт здесь, чтобы основной процесс не загружал библиотеки распознавания.
        from .engines import load_engine

        started = time.monotonic()
        # Ключ нужен только облачным моделям; остальным он не передаётся.
        engine = load_engine(model_path) if api_key is None else load_engine(model_path, api_key=api_key)
        self.results.send(("loaded", time.monotonic() - started))

        while True:
            device = self._take_device()
            try:
                stream, samplerate, name = self._open(device)
            except Exception as e:
                # Модель не выгружаем: ждём, пока выберут другой микрофон.
                self.results.send(("mic_error", str(e)))
                self._wait_for_command()
                continue
            try:
                self.results.send(("listening", name, samplerate))
                self._recognize(engine.session(samplerate), stream, samplerate)
            except MicrophoneLost:
                lost = True
            else:
                lost = False
            finally:
                self.monitor.stop()
                _close_stream(stream)
            if lost:
                # Поток уже закрыт; модель в памяти, ждём другой (или тот же, снова подключённый) микрофон.
                self.results.send(("mic_error", f"Микрофон «{name}» перестал отвечать"))
                self._wait_for_command()

    def _open(self, device: int | str | None):
        import sounddevice as sd

        from .audio_devices import display_name, refresh, resolve

        refresh()  # микрофон могли подключить после запуска
        index = resolve(device)
        info = sd.query_devices(index, "input")
        samplerate = int(info["default_samplerate"])

        def callback(indata, frames, time_info, status) -> None:
            self.chunks.put(bytes(indata))

        stream = sd.RawInputStream(
            device=index,
            samplerate=samplerate,
            blocksize=int(samplerate * BLOCK_SECONDS),
            dtype="int16",
            channels=1,
            callback=callback,
        )
        stream.start()
        return stream, samplerate, display_name(info["index"])

    def _recognize(self, session, stream, samplerate: int) -> None:
        """Распознаёт звук, пока не придёт команда сменить микрофон."""
        while True:
            try:
                data = self.chunks.get(timeout=SILENCE_TIMEOUT)
            except queue.Empty:
                if not stream.active:  # например, микрофон отключили
                    raise MicrophoneLost from None
                continue
            if data is None:
                with self._lock:
                    if self._device_changed:
                        return  # смена микрофона важнее: прослушивание закроется вместе с ним
                if self.monitor.running != self._monitor_wanted:
                    self._apply_monitor(samplerate)
                continue
            self.results.send(("level", peak_level(data)))
            self.monitor.feed(data)
            for text, is_final in session.accept(data):
                self.results.send(("text", text, is_final))

    def _apply_monitor(self, samplerate: int) -> None:
        if not self._monitor_wanted:
            self.monitor.stop()
            self.results.send(("monitor", False, None))
            return
        try:
            self.monitor.start(samplerate)
        except Exception as e:
            self._monitor_wanted = False
            self.results.send(("monitor", False, f"Не удалось включить прослушивание: {e}"))
            return
        self.results.send(("monitor", True, None))

    def _wait_for_command(self) -> None:
        while self.chunks.get() is not None:
            pass

    def _take_device(self) -> int | str | None:
        # Звук старого микрофона больше не нужен. Очередь чистим до чтения
        # устройства: команда, пришедшая после, снова положит в очередь None.
        while True:
            try:
                self.chunks.get_nowait()
            except queue.Empty:
                break
        with self._lock:
            self._device_changed = False
            return self._pending_device

    def _read_commands(self, commands: Connection) -> None:
        while True:
            try:
                kind, value = commands.recv()
            except (EOFError, OSError):
                os._exit(0)  # основной процесс закрыл канал
            if kind == "device":
                with self._lock:
                    self._pending_device = value
                    self._device_changed = True
                # Новый микрофон начинаем без прослушивания: его включают осознанно.
                self._monitor_wanted = False
                self.chunks.put(None)
            elif kind == "monitor":
                self._monitor_wanted = bool(value)
                self.chunks.put(None)


def _close_stream(stream) -> None:
    try:
        stream.abort()  # не ждём, пока доиграют буферы: звук старого микрофона не нужен
        stream.close()
    except Exception:  # noqa: S110
        pass  # у отключённого устройства закрытие может не получиться — это уже неважно


def peak_level(data: bytes) -> float:
    """Пиковая громкость куска звука (int16) от 0 до 1."""
    samples = array.array("h", data[: len(data) // 2 * 2])  # неполный отсчёт в конце пропускаем
    if not samples:
        return 0.0
    return min(max(max(samples), -min(samples)) / 32768, 1.0)


class _Monitor:
    """Прослушивание: звук микрофона в системные динамики или наушники."""

    def __init__(self):
        self.stream = None
        self._lock = threading.Lock()
        self._pending = bytearray()
        self._max_bytes = 0

    @property
    def running(self) -> bool:
        return self.stream is not None

    def start(self, samplerate: int) -> None:
        import sounddevice as sd

        self.stop()
        self._max_bytes = int(samplerate * MONITOR_MAX_SECONDS) * 2

        def callback(outdata, frames, time_info, status) -> None:
            need = len(outdata)
            with self._lock:
                chunk = bytes(self._pending[:need])
                del self._pending[:need]
            outdata[: len(chunk)] = chunk
            outdata[len(chunk) :] = bytes(need - len(chunk))  # тишина, если звука не хватило

        stream = sd.RawOutputStream(
            samplerate=samplerate, channels=1, dtype="int16", callback=callback
        )
        stream.start()
        self.stream = stream

    def feed(self, data: bytes) -> None:
        if self.stream is None:
            return
        with self._lock:
            self._pending += data
            # Если динамики не успевают, выбрасываем старое: лучше пропуск, чем эхо через секунду.
            overflow = len(self._pending) - self._max_bytes
            if overflow > 0:
                del self._pending[:overflow]

    def stop(self) -> None:
        if self.stream is not None:
            self.stream.abort()
            self.stream.close()
            self.stream = None
        with self._lock:
            self._pending.clear()


def _send_error(results: Connection) -> None:
    try:
        results.send(("error", traceback.format_exc()))
    except OSError:
        pass  # основной процесс уже закрыл канал


def _exit_with_parent() -> None:
    """Завершает процесс, если основной процесс умер (например, его убили)."""
    parent = multiprocessing.parent_process()
    if parent is None:
        return

    def watch() -> None:
        parent.join()
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()
