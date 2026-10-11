"""Письмо автору: почтовая программа в реестре и сайты почт."""

from urllib.parse import parse_qs, urlsplit

import pytest

from app import mail

TO = "author@example.com"
SUBJECT = "SwearCounter: заказ оформления"
BODY = "Почта для связи: me@x.ru\n\nОгонь & звук?"


def query(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_mailto_encodes_everything():
    parts = urlsplit(mail.mailto(TO, SUBJECT, BODY))
    assert parts.scheme == "mailto" and parts.path == TO
    assert query(mail.mailto(TO, SUBJECT, BODY)) == {"subject": SUBJECT, "body": BODY}


@pytest.mark.parametrize(
    "sender, name, host",
    [
        ("me@gmail.com", "Gmail", "mail.google.com"),
        ("Me@GoogleMail.com", "Gmail", "mail.google.com"),
        ("me@outlook.com", "Outlook", "outlook.live.com"),
        ("me@hotmail.com", "Outlook", "outlook.live.com"),
        ("me@yahoo.com", "Yahoo Mail", "compose.mail.yahoo.com"),
    ],
)
def test_webmail_with_fields(sender, name, host):
    info = mail.webmail(sender, TO, SUBJECT, BODY)
    assert info["name"] == name and info["filled"] is True
    parts = urlsplit(info["url"])
    assert parts.scheme == "https" and parts.hostname == host
    fields = query(info["url"])
    assert fields["to"] == TO
    assert fields.get("su", fields.get("subject")) == SUBJECT
    assert fields["body"] == BODY


@pytest.mark.parametrize(
    "sender, host",
    [("me@yandex.ru", "mail.yandex.ru"), ("me@ya.ru", "mail.yandex.ru"),
     ("me@mail.ru", "e.mail.ru"), ("me@bk.ru", "e.mail.ru"), ("me@inbox.ru", "e.mail.ru")],
)
def test_webmail_through_mailto_handler(sender, host):
    """Яндекс и Mail принимают письмо целиком, как обработчик ссылок mailto:."""
    info = mail.webmail(sender, TO, SUBJECT, BODY)
    assert urlsplit(info["url"]).hostname == host and info["filled"] is True
    assert query(info["url"]) == {"mailto": mail.mailto(TO, SUBJECT, BODY)}


@pytest.mark.parametrize("sender", ["me@rambler.ru", "me@icloud.com"])
def test_webmail_without_fields(sender):
    info = mail.webmail(sender, TO, SUBJECT, BODY)
    assert info["filled"] is False and info["url"].startswith("https://")


@pytest.mark.parametrize("sender", ["me@example.com", "me@company.ru", "broken"])
def test_unknown_webmail(sender):
    assert mail.webmail(sender, TO, SUBJECT, BODY) is None


@pytest.fixture
def registry(monkeypatch):
    values: dict = {}
    keys: set = set()
    monkeypatch.setattr(mail.sys, "platform", "win32")
    monkeypatch.setattr(mail, "_registry_value", lambda root, path, name="": values.get((path, name)))
    monkeypatch.setattr(mail, "_registry_has_key", lambda root, path: path in keys)
    return values, keys


USER_CHOICE = (r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\mailto\UserChoice", "ProgId")


def test_mail_app_from_user_choice(registry):
    values, keys = registry
    values[USER_CHOICE] = "Outlook.URL.mailto.15"
    keys.add(r"Outlook.URL.mailto.15\shell\open")
    assert mail.has_mail_app()


def test_removed_mail_app(registry):
    """Выбор остался от удалённой «Почты» Windows: приложения уже нет."""
    values, _ = registry
    values[USER_CHOICE] = "AppXbx2ce4vcxjdhff3d1ms66qqzk12zn827"
    assert not mail.has_mail_app()


def test_mail_app_from_classic_handler(registry):
    values, _ = registry
    values[(r"mailto\shell\open\command", "")] = r'"C:\Program Files\Thunderbird\thunderbird.exe" -osint -compose "%1"'
    assert mail.has_mail_app()


def test_no_mail_app(registry):
    assert not mail.has_mail_app()


def test_not_windows(monkeypatch):
    monkeypatch.setattr(mail.sys, "platform", "linux")
    assert not mail.has_mail_app()
