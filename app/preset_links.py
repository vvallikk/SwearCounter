"""Установка личного оформления по ссылке: Яндекс Диск, Google Диск, Dropbox или прямая ссылка.

Автор кладёт zip-архив в облако, открывает доступ по ссылке и присылает её. Программа
сама превращает ссылку на страницу просмотра в ссылку на файл и скачивает архив
(не больше MAX_PACK_BYTES), а ставит его как обычно, через CustomPresets.install.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from .custom_presets import MAX_PACK_BYTES

log = logging.getLogger(__name__)

TIMEOUT = 30
YANDEX_API = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
GOOGLE_DOWNLOAD = "https://drive.usercontent.google.com/download"
CHUNK = 64 * 1024


def _open(request: urllib.request.Request):
    """Отдельной функцией, чтобы тесты подменяли сеть."""
    return urllib.request.urlopen(request, timeout=TIMEOUT)


def service(link: str) -> str:
    """Чья ссылка: yandex, google, dropbox или direct; ValueError, если это не ссылка."""
    parts = urllib.parse.urlsplit(link.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Вставьте ссылку, которая начинается с https://")
    host = parts.hostname.lower()
    if host == "yadi.sk" or host.startswith("disk.yandex.") or host == "disk.360.yandex.ru":
        return "yandex"
    if host in ("drive.google.com", "docs.google.com", "drive.usercontent.google.com"):
        return "google"
    if host in ("dropbox.com", "www.dropbox.com", "dl.dropboxusercontent.com"):
        return "dropbox"
    return "direct"


def google_file_id(link: str) -> str | None:
    """Id файла из ссылок вида /file/d/<id>/view, ?id=<id> и /uc?id=<id>."""
    parts = urllib.parse.urlsplit(link.strip())
    segments = [s for s in parts.path.split("/") if s]
    if "d" in segments and segments.index("d") + 1 < len(segments):
        return segments[segments.index("d") + 1]
    ids = urllib.parse.parse_qs(parts.query).get("id")
    return ids[0] if ids else None


def dropbox_direct(link: str) -> str:
    """Та же ссылка с dl=1: Dropbox отдаёт файл, а не страницу просмотра."""
    parts = urllib.parse.urlsplit(link.strip())
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if k not in ("dl", "raw")]
    query.append(("dl", "1"))
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def direct_url(link: str) -> str:
    """Адрес самого файла. Для Яндекс Диска его выдаёт API, поэтому здесь нужна сеть."""
    link = link.strip()
    kind = service(link)
    if kind == "yandex":
        query = urllib.parse.urlencode({"public_key": link})
        try:
            with _open(_request(f"{YANDEX_API}?{query}")) as response:
                answer = json.loads(response.read(CHUNK).decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError("Яндекс Диск не нашёл файл: проверьте ссылку и что доступ по ссылке открыт") from None
            raise ValueError(f"Яндекс Диск ответил ошибкой {e.code}") from None
        except urllib.error.URLError:
            raise ValueError("Нет связи с Яндекс Диском: проверьте интернет") from None
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Яндекс Диск прислал непонятный ответ") from None
        href = answer.get("href") if isinstance(answer, dict) else None
        if not isinstance(href, str) or not href.startswith("https://"):
            raise ValueError("Яндекс Диск не дал ссылку на скачивание")
        return href
    if kind == "google":
        file_id = google_file_id(link)
        if not file_id:
            raise ValueError("В ссылке Google Диска нет id файла: скопируйте ссылку через «Поделиться»")
        query = urllib.parse.urlencode({"id": file_id, "export": "download", "confirm": "t"})
        return f"{GOOGLE_DOWNLOAD}?{query}"
    if kind == "dropbox":
        return dropbox_direct(link)
    return link


def download(link: str, limit: int = MAX_PACK_BYTES) -> bytes:
    """Скачивает архив по ссылке; ValueError с понятной причиной."""
    kind = service(link)
    url = direct_url(link)
    log.info("Скачивание оформления по ссылке (%s)", kind)
    too_big = f"Файл по ссылке больше {limit // (1024 * 1024)} МБ"
    try:
        with _open(_request(url)) as response:
            length = response.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > limit:
                raise ValueError(too_big)
            if "text/html" in (response.headers.get("Content-Type") or ""):
                raise ValueError(_html_hint(kind))
            data = bytearray()
            while chunk := response.read(CHUNK):
                data += chunk
                if len(data) > limit:
                    raise ValueError(too_big)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            raise ValueError(_html_hint(kind)) from None
        raise ValueError(f"Сервер ответил ошибкой {e.code}") from None
    except urllib.error.URLError:
        raise ValueError("Не удалось скачать: проверьте интернет и ссылку") from None
    except TimeoutError:
        raise ValueError("Скачивание заняло слишком долго: попробуйте ещё раз") from None
    return bytes(data)


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": "SwearCounter"})


def _html_hint(kind: str) -> str:
    """Вместо архива пришла страница: обычно доступ по ссылке не открыт."""
    hints = {
        "yandex": "Яндекс Диск не отдал файл: проверьте, что доступ по ссылке открыт",
        "google": "Google Диск не отдал файл: в «Поделиться» выберите «Все, у кого есть ссылка»",
        "dropbox": "Dropbox не отдал файл: проверьте, что ссылка открыта для всех",
    }
    return hints.get(kind, "По ссылке не zip-архив, а страница: нужна прямая ссылка на файл")
