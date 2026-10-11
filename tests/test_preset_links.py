"""Установка оформления по ссылке: разбор ссылок облаков и скачивание (сеть подменена)."""

import io
import json
import urllib.error

import pytest

from app import preset_links


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, headers: dict | None = None):
        super().__init__(data)
        self.headers = headers or {}


@pytest.fixture
def net(monkeypatch):
    """Подменённая сеть: адрес → ответ (bytes, FakeResponse или исключение)."""
    routes: dict = {}
    requested: list[str] = []

    def fake_open(request):
        url = request.full_url
        requested.append(url)
        for prefix, answer in routes.items():
            if url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer if isinstance(answer, FakeResponse) else FakeResponse(answer)
        raise AssertionError(f"неожиданный запрос {url}")

    monkeypatch.setattr(preset_links, "_open", fake_open)
    return routes, requested


@pytest.mark.parametrize(
    "link, kind",
    [
        ("https://disk.yandex.ru/d/AbCd123", "yandex"),
        ("https://yadi.sk/d/AbCd123", "yandex"),
        ("https://disk.yandex.com/i/AbCd123", "yandex"),
        ("https://disk.360.yandex.ru/d/AbCd123", "yandex"),
        ("https://drive.google.com/file/d/1AbC/view?usp=sharing", "google"),
        ("https://www.dropbox.com/scl/fi/xyz/pack.zip?rlkey=k&dl=0", "dropbox"),
        ("https://example.com/pack.zip", "direct"),
        ("  https://example.com/pack.zip  ", "direct"),
    ],
)
def test_service(link, kind):
    assert preset_links.service(link) == kind


@pytest.mark.parametrize("link", ["", "pack.zip", "file:///C:/pack.zip", "ftp://example.com/a.zip", "javascript:alert(1)"])
def test_not_a_link(link):
    with pytest.raises(ValueError, match="https://"):
        preset_links.service(link)


@pytest.mark.parametrize(
    "link",
    [
        "https://drive.google.com/file/d/1AbC_x-9/view?usp=sharing",
        "https://drive.google.com/open?id=1AbC_x-9",
        "https://drive.google.com/uc?id=1AbC_x-9&export=download",
    ],
)
def test_google_direct_url(link):
    url = preset_links.direct_url(link)
    assert url.startswith(preset_links.GOOGLE_DOWNLOAD)
    assert "id=1AbC_x-9" in url and "confirm=t" in url


def test_google_without_id():
    with pytest.raises(ValueError, match="id файла"):
        preset_links.direct_url("https://drive.google.com/drive/my-drive")


def test_dropbox_direct_url_keeps_rlkey():
    url = preset_links.direct_url("https://www.dropbox.com/scl/fi/xyz/pack.zip?rlkey=k&dl=0")
    assert url == "https://www.dropbox.com/scl/fi/xyz/pack.zip?rlkey=k&dl=1"


def test_yandex_asks_api_for_href(net):
    routes, requested = net
    routes[preset_links.YANDEX_API] = json.dumps({"href": "https://downloader.disk.yandex.ru/x"}).encode()
    assert preset_links.direct_url("https://disk.yandex.ru/d/AbCd") == "https://downloader.disk.yandex.ru/x"
    assert "public_key=https%3A%2F%2Fdisk.yandex.ru%2Fd%2FAbCd" in requested[0]


def test_yandex_not_found(net):
    routes, _ = net
    routes[preset_links.YANDEX_API] = urllib.error.HTTPError(preset_links.YANDEX_API, 404, "", {}, None)
    with pytest.raises(ValueError, match="не нашёл"):
        preset_links.direct_url("https://disk.yandex.ru/d/AbCd")


@pytest.mark.parametrize("answer", [b"not json", json.dumps({"href": "http://plain"}).encode(), b"[]"])
def test_yandex_bad_answer(net, answer):
    routes, _ = net
    routes[preset_links.YANDEX_API] = answer
    with pytest.raises(ValueError, match="Яндекс Диск"):
        preset_links.direct_url("https://disk.yandex.ru/d/AbCd")


def test_download_direct(net):
    routes, _ = net
    routes["https://example.com/"] = b"PK zip"
    assert preset_links.download("https://example.com/pack.zip") == b"PK zip"


def test_download_yandex(net):
    routes, requested = net
    routes[preset_links.YANDEX_API] = json.dumps({"href": "https://downloader.disk.yandex.ru/x"}).encode()
    routes["https://downloader.disk.yandex.ru/"] = b"PK zip"
    assert preset_links.download("https://disk.yandex.ru/d/AbCd") == b"PK zip"
    assert len(requested) == 2


def test_download_too_big_by_header(net):
    routes, _ = net
    routes["https://example.com/"] = FakeResponse(b"", {"Content-Length": "999999"})
    with pytest.raises(ValueError, match="больше"):
        preset_links.download("https://example.com/pack.zip", limit=1000)


def test_download_too_big_without_header(net, monkeypatch):
    monkeypatch.setattr(preset_links, "CHUNK", 100)
    routes, _ = net
    routes["https://example.com/"] = b"x" * 2000
    with pytest.raises(ValueError, match="больше"):
        preset_links.download("https://example.com/pack.zip", limit=1000)


@pytest.mark.parametrize(
    "link, message",
    [
        ("https://drive.google.com/file/d/1AbC/view", "Все, у кого есть ссылка"),
        ("https://www.dropbox.com/s/xyz/pack.zip", "Dropbox"),
        ("https://example.com/pack.zip", "прямая ссылка"),
    ],
)
def test_html_instead_of_zip(net, link, message):
    routes, _ = net
    routes["https://"] = FakeResponse(b"<html>", {"Content-Type": "text/html; charset=utf-8"})
    with pytest.raises(ValueError, match=message):
        preset_links.download(link)


def test_closed_link(net):
    routes, _ = net
    routes["https://"] = urllib.error.HTTPError("https://x", 403, "", {}, None)
    with pytest.raises(ValueError, match="Все, у кого есть ссылка"):
        preset_links.download("https://drive.google.com/file/d/1AbC/view")


def test_no_network(net):
    routes, _ = net
    routes["https://"] = urllib.error.URLError("offline")
    with pytest.raises(ValueError, match="интернет"):
        preset_links.download("https://example.com/pack.zip")
