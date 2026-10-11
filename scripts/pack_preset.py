"""Собирает папку личного оформления в zip, готовый к отправке (см. docs/PRESETS.md).

    .venv\\Scripts\\python.exe scripts\\pack_preset.py private\\ferret
    .venv\\Scripts\\python.exe scripts\\pack_preset.py private\\ferret -o D:\\ferret.zip

Архив проверяется теми же правилами, что и при установке в программе, поэтому
если скрипт его собрал, то и у пользователя он установится.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.custom_presets import builtin_preset_ids, pack_folder  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Упаковать личное оформление в zip")
    parser.add_argument("folder", type=Path, help="папка с preset.json")
    parser.add_argument("-o", "--output", type=Path, help="куда сохранить (по умолчанию <id>.zip рядом с папкой)")
    args = parser.parse_args(argv)
    try:
        info, data = pack_folder(args.folder, builtin_preset_ids(ROOT / "overlay"))
    except ValueError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    output = args.output or args.folder.resolve().parent / f"{info['id']}.zip"
    output.write_bytes(data)
    print(f"Готово: {output} ({len(data) / 1024:.0f} КБ), оформление «{info['title']}»")
    return 0


if __name__ == "__main__":
    sys.exit(main())
