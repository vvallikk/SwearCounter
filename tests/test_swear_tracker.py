"""Счёт матов по ходу фразы: промежуточный текст с задержкой, окончательный — без повторов."""

import asyncio
import logging
from functools import partial

from app.profanity import SwearTracker, find_profanity

ROOTS = ("бля", "хрен")
DELAY = 0.05
WAIT = DELAY * 3  # заведомо дольше задержки


def run(steps) -> list[int]:
    """Прогоняет шаги: ("p", текст) — промежуточный, ("f", текст) — окончательный, число — пауза,
    "pause"/"resume" — пауза распознавания."""
    added: list[int] = []
    paused = [False]

    async def add(words: list[str]) -> None:
        added.append(len(words))

    async def scenario() -> None:
        tracker = SwearTracker(add, partial(find_profanity, roots=ROOTS), delay=DELAY, paused=lambda: paused[0])
        for step in steps:
            if step in ("pause", "resume"):
                paused[0] = step == "pause"
            elif isinstance(step, float):
                await asyncio.sleep(step)
            else:
                kind, text = step
                await tracker.feed(text, kind == "f")
        tracker.stop()

    asyncio.run(scenario())
    return added


def test_final_only_counts_like_before():
    assert run([("f", "бля хрен")]) == [2]


def test_stable_partial_counted_before_final():
    assert run([("p", "ну бля"), WAIT]) == [1]


def test_final_adds_only_missing():
    assert run([("p", "ну бля"), WAIT, ("f", "ну бля и хрен")]) == [1, 1]


def test_no_double_count_when_final_repeats():
    assert run([("p", "бля"), WAIT, ("p", "бля ну"), WAIT, ("f", "бля ну")]) == [1]


def test_swear_lost_in_final_still_counted():
    # Vosk переписал фразу и мат из окончательного текста пропал.
    assert run([("p", "бля быстро"), WAIT, ("f", "для быстро")]) == [1]


def test_flicker_not_counted():
    # Мелькнуло и исчезло раньше, чем прошла задержка.
    assert run([("p", "бля"), ("p", "для"), WAIT]) == []


def test_final_before_delay_cancels_timer():
    assert run([("p", "бля"), ("f", "бля"), WAIT]) == [1]


def test_counter_resets_between_phrases():
    assert run([("p", "бля"), WAIT, ("f", "бля"), ("p", "бля"), WAIT, ("f", "бля")]) == [1, 1]


def test_growing_partial_counted_after_delay():
    assert run([("p", "бля"), ("p", "бля хрен"), WAIT]) == [2]


def test_spoken_text_not_logged_at_info(caplog):
    """В файл журнала (INFO) попадают только числа, а не сказанное."""
    with caplog.at_level(logging.INFO, logger="app"):
        assert run([("p", "секретная бля"), WAIT, ("f", "секретная бля фраза")]) == [1]
    assert caplog.records
    assert not any("секретная" in record.getMessage() for record in caplog.records)


def test_paused_text_is_not_counted():
    assert run(["pause", ("p", "бля"), WAIT, ("f", "бля хрен")]) == []


def test_phrase_started_before_pause_is_forgotten():
    # Мат ещё не продержался в промежуточном тексте, а распознавание уже на паузе.
    assert run([("p", "ну бля"), "pause", ("p", "ну бля"), "resume", ("f", "ну бля")]) == [1]
    assert run([("p", "ну бля"), "pause", ("p", "ну бля"), WAIT, "resume", ("f", "ну")]) == []


def test_counting_resumes_after_pause():
    assert run(["pause", ("f", "бля"), "resume", ("f", "хрен")]) == [1]


def run_words(steps) -> list[list[str]]:
    """Как run, но возвращает корни засчитанных слов."""
    added: list[list[str]] = []

    async def add(words: list[str]) -> None:
        added.append(words)

    async def scenario() -> None:
        tracker = SwearTracker(add, partial(find_profanity, roots=ROOTS), delay=DELAY)
        for step in steps:
            if isinstance(step, float):
                await asyncio.sleep(step)
            else:
                kind, text = step
                await tracker.feed(text, kind == "f")
        tracker.stop()

    asyncio.run(scenario())
    return added


def test_words_reported_as_roots():
    assert run_words([("f", "бляха хреново бля")]) == [["бля", "хрен", "бля"]]


def test_final_reports_only_new_root():
    assert run_words([("p", "ну бля"), WAIT, ("f", "ну бля и хрен")]) == [["бля"], ["хрен"]]


def test_rewritten_phrase_reports_unseen_root():
    # Засчитали «бля», в окончательном тексте вместо него два «хрен»: новое слово одно — «хрен».
    assert run_words([("p", "бля"), WAIT, ("f", "хрен хрен")]) == [["бля"], ["хрен"]]
