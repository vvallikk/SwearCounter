"""Письмо автору: почтовая программа, если она есть, иначе сайт почты отправителя.

Почтовыми программами мало кто пользуется, а Windows сообщает, что mailto: открылся,
даже когда назначенное для него приложение давно удалено. Поэтому программа сама
проверяет реестр и, если приложения нет, предлагает написать письмо на сайте почты:
по домену адреса отправителя открывается страница нового письма, уже заполненная.
"""

import sys
from urllib.parse import quote, urlencode

# Домен адреса → (название почты, адрес страницы нового письма или None, если заполнить
# письмо по ссылке нельзя и открывается просто почта).
WEBMAIL = {
    "gmail": ("Gmail", "https://mail.google.com/mail/?view=cm&fs=1&{query}"),
    "yandex": ("Яндекс Почте", "https://mail.yandex.ru/compose?{mailto}"),
    "mailru": ("Почте Mail", "https://e.mail.ru/compose/?{mailto}"),
    "outlook": ("Outlook", "https://outlook.live.com/mail/0/deeplink/compose?{query}"),
    "yahoo": ("Yahoo Mail", "https://compose.mail.yahoo.com/?{query}"),
    "rambler": ("Рамблер Почте", "https://mail.rambler.ru/"),
    "icloud": ("iCloud Почте", "https://www.icloud.com/mail/"),
}
DOMAINS = {
    "gmail": ("gmail.com", "googlemail.com"),
    "yandex": ("yandex.ru", "ya.ru", "yandex.com", "yandex.by", "yandex.kz", "yandex.ua", "narod.ru"),
    "mailru": ("mail.ru", "inbox.ru", "list.ru", "bk.ru", "internet.ru", "mail.ua"),
    "outlook": ("outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.ru", "hotmail.ru"),
    "yahoo": ("yahoo.com", "ymail.com"),
    "rambler": ("rambler.ru", "lenta.ru", "autorambler.ru", "myrambler.ru", "ro.ru"),
    "icloud": ("icloud.com", "me.com", "mac.com"),
}
PROVIDER_BY_DOMAIN = {domain: provider for provider, domains in DOMAINS.items() for domain in domains}


def mailto(to: str, subject: str, body: str) -> str:
    return f"mailto:{to}?subject={quote(subject)}&body={quote(body)}"


def webmail(sender: str, to: str, subject: str, body: str) -> dict | None:
    """Сайт почты отправителя: {"name", "url", "filled"}; None, если почта незнакомая."""
    provider = PROVIDER_BY_DOMAIN.get(sender.rpartition("@")[2].strip().lower())
    if provider is None:
        return None
    name, template = WEBMAIL[provider]
    if "{" not in template:
        return {"name": name, "url": template, "filled": False}
    if provider == "gmail":
        query = urlencode({"to": to, "su": subject, "body": body}, quote_via=quote)
    else:
        query = urlencode({"to": to, "subject": subject, "body": body}, quote_via=quote)
    url = template.format(query=query, mailto=urlencode({"mailto": mailto(to, subject, body)}, quote_via=quote))
    return {"name": name, "url": url, "filled": True}


def _registry_value(root, path: str, name: str = "") -> str | None:
    """Значение из реестра или None; отдельной функцией, чтобы тесты подменяли реестр."""
    import winreg

    try:
        with winreg.OpenKey(root, path) as key:
            value = winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None
    return value if isinstance(value, str) else None


def _registry_has_key(root, path: str) -> bool:
    import winreg

    try:
        winreg.OpenKey(root, path).Close()
    except OSError:
        return False
    return True


def has_mail_app() -> bool:
    """Назначено ли для mailto: приложение, которое ещё установлено."""
    if sys.platform != "win32":
        return False
    import winreg

    prog_id = _registry_value(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\mailto\UserChoice",
        "ProgId",
    )
    if prog_id:
        # Выбор пользователя ссылается на ProgId; у удалённого приложения его уже нет.
        return _registry_has_key(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open")
    return bool(_registry_value(winreg.HKEY_CLASSES_ROOT, r"mailto\shell\open\command"))
