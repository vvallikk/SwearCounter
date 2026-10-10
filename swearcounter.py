"""Точка входа для сборки exe (PyInstaller). Из исходников запускайте python -m app.main."""

import logging
import multiprocessing
import sys
import traceback

TITLE = "Счётчик матов"
MB_ICONERROR = 0x10
TRACEBACK_LINES = 15


def _show_error(text: str) -> None:
    # У exe нет консоли: ошибку показываем окном, иначе программа молча закроется.
    if sys.stderr is not None:
        print(text, file=sys.stderr)
    import ctypes

    ctypes.windll.user32.MessageBoxW(None, text, TITLE, MB_ICONERROR)


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
            _show_error(e.code)
        sys.exit(e.code if isinstance(e.code, int) else 1)
    except Exception:
        logging.getLogger("app").exception("Программа завершилась с ошибкой")
        tail = "".join(traceback.format_exc().splitlines(keepends=True)[-TRACEBACK_LINES:])
        _show_error(f"Программа завершилась с ошибкой (подробности — в swearcounter.log):\n\n{tail}")
        sys.exit(1)
