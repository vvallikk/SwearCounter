"""Счётчик матов (и любых других слов) по голосу с оверлеем для OBS."""

__version__ = "1.1.1"

# Куда можно поддержать автора. Пустой список — кнопки «Поддержать» нет ни в окне, ни в трее.
# qr — картинка с QR-кодом в папке control/ (необязательно).
# Почта для заказа личного оформления и тема письма. Пустая строка — ссылки «заказать» нет.
ORDER_EMAIL = ""
ORDER_SUBJECT = "SwearCounter: заказ оформления"

SUPPORT_LINKS = [
    {
        "name": "Boosty",
        "url": "https://boosty.to/walikk/single-payment/donation/834276/target?share=target_link",
        "qr": "support/boosty.png",
    },
    {
        "name": "DonationAlerts",
        "url": "https://www.donationalerts.com/r/vvalikk",
        "qr": "support/donationalerts.png",
    },
]
