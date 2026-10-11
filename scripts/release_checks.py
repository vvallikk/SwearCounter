"""Раздел "Проверка файла" в конце описания релиза: SHA-256, отчёт VirusTotal и подпись.

Запуск из release.yml после сборки (и подписи) архива:

    python scripts/release_checks.py dist/SwearCounter-vX.Y.Z-windows.zip docs/releases/vX.Y.Z.md [--signed]

Раздел дописывается в файл заметок, из которого создаётся релиз. Архив отправляется
на VirusTotal, если задана переменная окружения VT_API_KEY (бесплатный ключ из профиля
на virustotal.com); без ключа или при ошибке VirusTotal в разделе остаётся только SHA-256,
а релиз всё равно выходит. Программа показывает заметки без этого раздела: он начинается
с пометки CHECKS_MARKER, см. app/updater.py.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.updater import CHECKS_MARKER, file_sha256  # noqa: E402

API = "https://www.virustotal.com/api/v3"
REPORT_URL = "https://www.virustotal.com/gui/file/{sha256}"
WAIT_SECONDS = 15 * 60  # большой архив VirusTotal проверяет несколько минут
POLL_SECONDS = 30  # бесплатный ключ: не больше 4 запросов в минуту
# Вердикты антивирусов, которые входят в итог "N из M"; timeout, unsupported и т. п. не считаем.
COUNTED = ("malicious", "suspicious", "undetected", "harmless")


def detections(stats: dict) -> tuple[int, int]:
    """(сколько антивирусов нашли угрозу, сколько всего дали ответ) из last_analysis_stats."""
    found = stats.get("malicious", 0) + stats.get("suspicious", 0)
    return found, sum(stats.get(key, 0) for key in COUNTED)


def checks_section(sha256: str, stats: dict | None, scanned: bool, signed: bool) -> str:
    """Текст раздела. stats — итог проверки VirusTotal (None, если она ещё не закончилась)."""
    lines = [CHECKS_MARKER, "## Проверка файла · File check", "", f"- SHA-256: `{sha256}`"]
    if scanned:
        link = REPORT_URL.format(sha256=sha256)
        if stats:
            found, total = detections(stats)
            verdict = "угроз не найдено · no threats found" if found == 0 else "см. отчёт · see the report"
            lines.append(f"- VirusTotal: [{found}/{total}]({link}) ({verdict})")
        else:
            lines.append(f"- VirusTotal: [отчёт · report]({link})")
    if signed:
        lines.append(
            "- Подпись: SwearCounter.exe подписан сертификатом SignPath Foundation · "
            "Signed with a SignPath Foundation certificate"
        )
    return "\n".join(lines) + "\n"


def call(method: str, url: str, key: str, body: bytes | None = None, content_type: str | None = None) -> dict:
    request = urllib.request.Request(url, data=body, method=method, headers={"x-apikey": key, "accept": "application/json"})
    if content_type:
        request.add_header("content-type", content_type)
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.load(response)


def known_stats(sha256: str, key: str) -> dict | None:
    """Итог уже готовой проверки этого файла; None, если VirusTotal его ещё не видел."""
    try:
        attributes = call("GET", f"{API}/files/{sha256}", key)["data"]["attributes"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    stats = attributes.get("last_analysis_stats") or {}
    return stats if any(stats.values()) else None


def upload(path: Path, key: str) -> str:
    """Отправить файл на проверку; возвращает id анализа."""
    # Файлы больше 32 МБ принимаются только по отдельному адресу загрузки.
    url = call("GET", f"{API}/files/upload_url", key)["data"]
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return call("POST", url, key, body, f"multipart/form-data; boundary={boundary}")["data"]["id"]


def wait_for_analysis(analysis_id: str, key: str) -> dict | None:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        attributes = call("GET", f"{API}/analyses/{analysis_id}", key)["data"]["attributes"]
        if attributes.get("status") == "completed":
            return attributes.get("stats") or {}
    return None


def scan(path: Path, sha256: str, key: str) -> dict | None:
    stats = known_stats(sha256, key)
    if stats is None:
        stats = wait_for_analysis(upload(path, key), key)
    return stats


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("archive", type=Path)
    parser.add_argument("notes", type=Path)
    parser.add_argument("--signed", action="store_true", help="exe в архиве подписан SignPath")
    args = parser.parse_args(argv)

    sha256 = file_sha256(args.archive)
    stats, scanned = None, False
    key = os.environ.get("VT_API_KEY", "").strip()
    if key:
        try:
            stats = scan(args.archive, sha256, key)
            scanned = True
            if stats is None:
                print("::warning::VirusTotal не успел проверить архив, в заметках будет ссылка без итога")
        except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
            print(f"::warning::VirusTotal недоступен ({e}), в заметках будет только SHA-256")
    else:
        print("VT_API_KEY не задан: проверка VirusTotal пропущена")

    notes = args.notes.read_text(encoding="utf-8").rstrip()
    args.notes.write_text(f"{notes}\n\n{checks_section(sha256, stats, scanned, args.signed)}", encoding="utf-8")
    print(checks_section(sha256, stats, scanned, args.signed))


if __name__ == "__main__":
    main()
