"""Точка входа для сборки exe (PyInstaller). Из исходников запускайте python -m app.main."""

import multiprocessing
import sys
import traceback


def _pause_if_interactive() -> None:
    # exe запускают двойным щелчком: без паузы окно консоли закроется вместе
    # с сообщением об ошибке, и его не успеют прочитать.
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nНажмите Enter, чтобы закрыть окно…")
        except EOFError:
            pass  # ввод не из консоли (например, NUL) — ждать нечего


if __name__ == "__main__":
    # В exe процесс распознавания запускается копией того же exe: freeze_support()
    # должен сработать раньше всего остального, иначе копия запустит второй сервер.
    multiprocessing.freeze_support()

    from app.main import main

    try:
        main()
    except SystemExit as e:
        if e.code in (None, 0):
            raise
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
        _pause_if_interactive()
        sys.exit(e.code if isinstance(e.code, int) else 1)
    except Exception:
        traceback.print_exc()
        _pause_if_interactive()
        sys.exit(1)
