"""Минимальные HTTPS-запросы к API платформ (стандартная библиотека, JSON)."""

import json
import urllib.error
import urllib.request

TIMEOUT = 15.0
MAX_RESPONSE = 2 * 1024 * 1024


class HttpError(Exception):
    def __init__(self, status: int, reason: str = "", message: str = ""):
        super().__init__(message or reason or f"HTTP {status}")
        self.status = status
        self.reason = reason  # короткий код ошибки API, например quotaExceeded


def _error_reason(body: bytes) -> tuple[str, str]:
    """Код и текст ошибки из тела ответа Google или Twitch; пусто, если тело другое."""
    try:
        data = json.loads(body)
    except ValueError:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    error = data.get("error")
    if isinstance(error, dict):  # Google: {"error": {"errors": [{"reason": ...}], "message": ...}}
        errors = error.get("errors")
        reason = errors[0].get("reason", "") if isinstance(errors, list) and errors and isinstance(errors[0], dict) else ""
        return str(reason), str(error.get("message", ""))
    return "", str(data.get("message") or error or "")  # Twitch: {"error": "Unauthorized", "message": ...}


def request_json(url: str, headers: dict | None = None, body: dict | None = None, timeout: float = TIMEOUT) -> dict:
    """GET (или POST с JSON-телом) и разобранный JSON ответа; HttpError при коде не 2xx."""
    if not url.startswith("https://"):
        raise ValueError("Только https")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=dict(headers or {}), method="POST" if body is not None else "GET")  # noqa: S310
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read(MAX_RESPONSE)
    except urllib.error.HTTPError as e:
        reason, message = _error_reason(e.read(MAX_RESPONSE))
        raise HttpError(e.code, reason, message) from None
    except urllib.error.URLError as e:
        raise OSError(str(e.reason)) from None
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise OSError("Сервер вернул не JSON") from None
    return parsed if isinstance(parsed, dict) else {}
