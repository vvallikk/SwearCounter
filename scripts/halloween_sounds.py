"""Сборка звуков события «Хеллоуин» (overlay/sounds/halloween/) из исходников CC0.

Временный инструмент события: после 1 ноября его можно удалить вместе с папкой звуков.
Нужны numpy и ffmpeg в PATH (в программу и requirements не входят).

Исходники (CC0, OpenGameArt, ссылки — в overlay/sounds/halloween/README.md) скачиваются
в одну папку с теми же именами, что на сайте:
    python scripts/halloween_sounds.py private/halloween-sounds-src

Скримерам нужна резкость: тишина в начале срезается, атака жёсткая, а поверх визга и ударов
кладётся синтезированный «удар смычком» — кластер из соседних полутонов, как в фильмах ужасов
(его генерирует этот скрипт, это наша работа, тоже CC0).
"""

import subprocess
import sys
from pathlib import Path

import numpy as np

RATE = 44100
OUT = Path(__file__).resolve().parent.parent / "overlay" / "sounds" / "halloween"
HITS = "horror_hit_soundpack_1/Horror Hit Soundpack 1/Sound/Pitches"


def load(path: Path, start: float = 0.0, length: float | None = None) -> np.ndarray:
    args = ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start)]
    if length is not None:
        args += ["-t", str(length)]
    args += ["-i", str(path), "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(args, capture_output=True, check=True).stdout, dtype=np.float32).copy()


def trim_silence(x: np.ndarray, threshold_db: float = -30) -> np.ndarray:
    """Срезает тишину в начале: звук начинается сразу, а не через полсекунды."""
    level = 10 ** (threshold_db / 20) * np.abs(x).max()
    loud = np.flatnonzero(np.abs(x) > level)
    return x[max(loud[0] - int(0.003 * RATE), 0):] if loud.size else x


def envelope(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / RATE
    return np.minimum(t / attack, 1.0) * np.exp(-t / decay)


def fade_out(x: np.ndarray, seconds: float) -> np.ndarray:
    n = min(int(seconds * RATE), len(x))
    x = x.copy()
    x[-n:] *= np.linspace(1, 0, n) ** 2
    return x


def stab(length: float, base: float = 1046.5, decay: float = 0.6, seed: int = 1) -> np.ndarray:
    """Удар смычком: кластер полутонов пилой с вибрато и шумом смычка, высота чуть ползёт вверх."""
    rng = np.random.default_rng(seed)
    n = int(length * RATE)
    t = np.arange(n) / RATE
    out = np.zeros(n)
    for step in range(5):
        freq = base * 2 ** (step / 12) * (1 + 0.04 * t)  # визг: тон ползёт вверх
        vibrato = 1 + 0.012 * np.sin(2 * np.pi * (6 + rng.random()) * t + rng.random() * 6)
        phase = 2 * np.pi * np.cumsum(freq * vibrato) / RATE
        for harmonic in range(1, 9):  # пила без лишних гармоник выше ~10 кГц
            if base * harmonic < 10000:
                out += np.sin(harmonic * phase) / harmonic
    noise = np.convolve(rng.standard_normal(n), [1, -1], "same")  # шум смычка без низа
    out = out / np.abs(out).max() + 0.15 * noise / np.abs(noise).max()
    return out * envelope(n, 0.004, decay)


def crack(length: float = 0.08, seed: int = 2) -> np.ndarray:
    """Щелчок в самом начале: короткий яркий шум, с ним удар слышен сразу."""
    n = int(length * RATE)
    noise = np.convolve(np.random.default_rng(seed).standard_normal(n), [1, -1], "same")
    return noise / np.abs(noise).max() * envelope(n, 0.0005, 0.015)


def mix(*layers: tuple[np.ndarray, float]) -> np.ndarray:
    n = max(len(x) for x, _ in layers)
    out = np.zeros(n)
    for x, gain in layers:
        out[: len(x)] += gain * x / (np.abs(x).max() or 1)
    return out


def speed(x: np.ndarray, factor: float) -> np.ndarray:
    """Быстрее и выше (как пластинка): визг становится пронзительнее."""
    positions = np.arange(0, len(x) - 1, factor)
    return np.interp(positions, np.arange(len(x)), x)


def save(name: str, x: np.ndarray, fade: float = 0.3) -> None:
    x = fade_out(x, fade)
    raw = (x / np.abs(x).max()).astype(np.float32).tobytes()
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", "-",
         "-af", "acompressor=threshold=-18dB:ratio=4:attack=1:release=120,loudnorm=I=-14:TP=-1:LRA=7,"
                "aresample=44100,alimiter=limit=0.89:attack=1:level=false",
         "-c:a", "libvorbis", "-q:a", "5", str(OUT / name)],
        input=raw, check=True,
    )
    print(name, f"{len(x) / RATE:.2f} с")


def main(src: Path) -> None:
    shriek = load(src / "scaryhighpitchedghost_0.ogg", 11.3, 2.4)
    hit = trim_silence(load(src / HITS / "Bassy/Bassy 5.wav", 0, 3))
    low = trim_silence(load(src / HITS / "Very Bassy/Very Bassy 1.wav", 0, 3))

    save("scream-stab.ogg", mix((crack(), 0.6), (stab(1.8), 1.0), (shriek[: int(1.8 * RATE)], 0.8), (hit[: int(1.8 * RATE)], 0.9)), 0.5)
    save("ghost-shriek.ogg", mix((crack(), 0.5), (shriek[: int(2.0 * RATE)], 1.0), (stab(2.0, 1568, 0.25, 3), 0.35)), 0.5)
    save("banshee.ogg", mix((crack(), 0.5), (speed(shriek, 1.3)[: int(1.8 * RATE)], 1.0), (stab(1.8, 2093, 0.4, 4), 0.5)), 0.5)
    save("jumpscare-hit.ogg", mix((crack(), 0.8), (hit[: int(2.0 * RATE)], 1.0), (stab(1.2, 1046.5, 0.25, 5), 0.7)), 0.6)
    save("jumpscare-low.ogg", mix((crack(), 0.7), (low[: int(2.2 * RATE)], 1.0), (stab(1.5, 261.6, 0.35, 6), 0.6)), 0.6)
    save("witch-cackle.ogg", trim_silence(load(src / "witch_cackle-1_0.ogg")), 0.15)
    save("evil-laugh.ogg", trim_silence(load(src / "laugh-evil-1_0.ogg")), 0.3)
    save("demon-laugh.ogg", trim_silence(load(src / "evil_laughs/Evil Laughs/Laugh 7.mp3", 1.3, 3.9)), 0.6)
    save("ghost-moan.ogg", trim_silence(load(src / "qubodup-GhostMoans/qubodup-GhostMoans/mp3/qubodup-GhostMoan01.mp3")), 0.4)
    save("door-creak.ogg", trim_silence(load(src / "creaky_door_hinge.wav", 0, 3.15)), 0.4)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
