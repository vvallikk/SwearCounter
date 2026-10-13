"""Проверка файлов на VirusTotal без релиза: сводка по каждому файлу и список сработавших движков.

Запуск из antivirus-check.yml (нужна переменная окружения VT_API_KEY):

    python scripts/vt_check.py dist/SwearCounter-v1.5.0-windows.zip dist/SwearCounter/SwearCounter.exe

Результат печатается и дописывается в GITHUB_STEP_SUMMARY, если он задан.
Код возврата 0, даже если что-то нашли: скрипт только сообщает.
"""

import argparse
import os
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.updater import file_sha256  # noqa: E402
from scripts.release_checks import API, REPORT_URL, call, detections, upload, wait_for_analysis  # noqa: E402

FLAGGED = ("malicious", "suspicious")


def flagged_engines(sha256: str, key: str) -> list[tuple[str, str]]:
    attributes = call("GET", f"{API}/files/{sha256}", key)["data"]["attributes"]
    results = attributes.get("last_analysis_results") or {}
    return sorted((name, r.get("result") or r["category"]) for name, r in results.items() if r["category"] in FLAGGED)


def check(path: Path, key: str) -> str:
    sha256 = file_sha256(path)
    # Новый файл ждёт результат; уже известный VirusTotal берётся из кэша.
    # Перепроверку не просим: итог должен быть тем, что увидят пользователи.
    try:
        call("GET", f"{API}/files/{sha256}", key)
        known = True
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        known = False
    if not known:
        stats = wait_for_analysis(upload(path, key), key)
        if stats is None:
            return f"### {path.name}\n\nVirusTotal не успел проверить файл: [отчёт]({REPORT_URL.format(sha256=sha256)})\n"
    attributes = call("GET", f"{API}/files/{sha256}", key)["data"]["attributes"]
    found, total = detections(attributes.get("last_analysis_stats") or {})
    lines = [
        f"### {path.name}",
        "",
        f"- SHA-256: `{sha256}`",
        f"- Итог: **{found}/{total}** ([отчёт]({REPORT_URL.format(sha256=sha256)}))",
    ]
    lines += [f"- {name}: `{verdict}`" for name, verdict in flagged_engines(sha256, key)]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    key = os.environ.get("VT_API_KEY", "").strip()
    if not key:
        print("::error::VT_API_KEY не задан")
        return 1
    report = "## VirusTotal\n\n" + "\n".join(check(path, key) for path in args.files)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
