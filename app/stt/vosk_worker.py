"""Отдельный процесс распознавания: модель Vosk, микрофон и распознавание.

Процесс нужен, чтобы загрузку модели можно было прервать в любой момент:
поток остановить нельзя, а процесс можно завершить, и Windows сразу вернёт
всю его память. Результаты отправляются в основной процесс через канал (Pipe)
кортежами:

    ("loaded", секунды)               модель загружена в память
    ("listening", микрофон, частота)  микрофон открыт, идёт распознавание
    ("text", текст, is_final)         распознанный текст
    ("error", описание)               ошибка; процесс после неё завершается
"""

import json
import multiprocessing
import os
import queue
import threading
import time
import traceback
from multiprocessing.connection import Connection

BLOCK_SECONDS = 0.25  # длина одного куска звука, который отдаём распознавателю


def run_worker(conn: Connection, model_path: str, device: int | str | None) -> None:
    _exit_with_parent()
    try:
        _recognize(conn, model_path, device)
    except (BrokenPipeError, EOFError):
        pass  # основной процесс закрыл канал: распознавание больше не нужно
    except Exception:
        _send_error(conn)


def _recognize(conn: Connection, model_path: str, device: int | str | None) -> None:
    # Тяжёлые импорты здесь, чтобы основной процесс их не загружал.
    import sounddevice as sd
    import vosk

    vosk.SetLogLevel(-1)  # иначе Kaldi засыпает консоль служебными сообщениями

    started = time.monotonic()
    model = vosk.Model(model_path)
    conn.send(("loaded", time.monotonic() - started))

    info = sd.query_devices(device, "input")
    samplerate = int(info["default_samplerate"])
    rec = vosk.KaldiRecognizer(model, samplerate)
    chunks: queue.Queue[bytes] = queue.Queue()

    def callback(indata, frames, time_info, status) -> None:
        chunks.put(bytes(indata))

    with sd.RawInputStream(
        device=device,
        samplerate=samplerate,
        blocksize=int(samplerate * BLOCK_SECONDS),
        dtype="int16",
        channels=1,
        callback=callback,
    ):
        conn.send(("listening", info["name"], samplerate))
        last_partial = ""
        while True:
            if rec.AcceptWaveform(chunks.get()):
                text = json.loads(rec.Result())["text"]
                last_partial = ""
                if text:
                    conn.send(("text", text, True))
            else:
                partial = json.loads(rec.PartialResult())["partial"]
                if partial and partial != last_partial:
                    last_partial = partial
                    conn.send(("text", partial, False))


def _send_error(conn: Connection) -> None:
    try:
        conn.send(("error", traceback.format_exc()))
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
