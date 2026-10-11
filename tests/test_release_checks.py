"""Раздел "Проверка файла" в описании релиза: SHA-256, VirusTotal и подпись."""

import hashlib

from app.updater import release_notes, update_policy
from scripts import release_checks
from scripts.release_checks import checks_section, detections

SHA = "a" * 64
STATS = {"malicious": 0, "suspicious": 0, "undetected": 60, "harmless": 6, "timeout": 2, "type-unsupported": 9}


def test_detections_count_only_real_verdicts():
    assert detections(STATS) == (0, 66)
    assert detections({"malicious": 1, "suspicious": 2, "undetected": 7}) == (3, 10)
    assert detections({}) == (0, 0)


def test_section_with_clean_scan_and_signature():
    text = checks_section(SHA, STATS, scanned=True, signed=True)
    assert text.startswith("<!-- checks -->\n")
    assert f"- SHA-256: `{SHA}`" in text
    assert f"[0/66](https://www.virustotal.com/gui/file/{SHA})" in text
    assert "угроз не найдено" in text
    assert "SignPath Foundation" in text


def test_section_with_detections_points_to_report():
    text = checks_section(SHA, {"malicious": 2, "undetected": 60}, scanned=True, signed=False)
    assert "[2/62]" in text and "см. отчёт" in text
    assert "SignPath" not in text


def test_section_while_scan_is_running_has_plain_link():
    text = checks_section(SHA, None, scanned=True, signed=False)
    assert f"[отчёт · report](https://www.virustotal.com/gui/file/{SHA})" in text


def test_section_without_virustotal_has_only_hash():
    text = checks_section(SHA, None, scanned=False, signed=False)
    assert "VirusTotal" not in text
    assert f"`{SHA}`" in text


def test_main_without_key_appends_hash(tmp_path, monkeypatch):
    archive = tmp_path / "SwearCounter-v9.9.9-windows.zip"
    archive.write_bytes(b"zip")
    notes = tmp_path / "v9.9.9.md"
    notes.write_text("## Что нового\n\n- Пункт\n<!-- update: full-force -->\n", encoding="utf-8")
    monkeypatch.delenv("VT_API_KEY", raising=False)

    release_checks.main([str(archive), str(notes)])

    body = notes.read_text(encoding="utf-8")
    assert hashlib.sha256(b"zip").hexdigest() in body
    # Программа видит заметки без раздела, а пометка обновления по-прежнему читается.
    assert release_notes(body) == "## Что нового\n\n- Пункт\n<!-- update: full-force -->"
    assert update_policy(body)["type"] == "full-force"


def test_main_survives_virustotal_errors(tmp_path, monkeypatch):
    archive = tmp_path / "a.zip"
    archive.write_bytes(b"zip")
    notes = tmp_path / "notes.md"
    notes.write_text("Что нового", encoding="utf-8")
    monkeypatch.setenv("VT_API_KEY", "key")

    def broken(*args):
        raise OSError("нет сети")

    monkeypatch.setattr(release_checks, "scan", broken)
    release_checks.main([str(archive), str(notes), "--signed"])

    body = notes.read_text(encoding="utf-8")
    assert "VirusTotal" not in body and "SignPath Foundation" in body


def test_scan_uses_existing_report(monkeypatch):
    monkeypatch.setattr(release_checks, "known_stats", lambda sha, key: STATS)

    def no_upload(*args):
        raise AssertionError("файл уже проверен, повторно отправлять не нужно")

    monkeypatch.setattr(release_checks, "upload", no_upload)
    assert release_checks.scan(None, SHA, "key") == STATS


def test_scan_uploads_new_file(monkeypatch):
    monkeypatch.setattr(release_checks, "known_stats", lambda sha, key: None)
    monkeypatch.setattr(release_checks, "upload", lambda path, key: "analysis-1")
    monkeypatch.setattr(release_checks, "wait_for_analysis", lambda aid, key: {"undetected": 5} if aid == "analysis-1" else None)
    assert release_checks.scan(None, SHA, "key") == {"undetected": 5}
