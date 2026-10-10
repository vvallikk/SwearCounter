"""Рисует иконку приложения: assets/icon.ico (exe) и assets/icon.png (трей).

Запуск из корня проекта (нужен Pillow):  .venv\\Scripts\\python.exe scripts/make_icon.py
Готовые файлы лежат в репозитории, перерисовывать нужно только при смене дизайна.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZE = 256
BACKGROUND = (220, 38, 38)
TEXT = "#!"


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def draw() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas = ImageDraw.Draw(image)
    canvas.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=56, fill=BACKGROUND)
    canvas.text((SIZE / 2, SIZE / 2 + 6), TEXT, font=_font(150), fill="white", anchor="mm")
    return image


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    image = draw()
    image.save(ASSETS / "icon.png")
    image.save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Готово: {ASSETS / 'icon.ico'}, {ASSETS / 'icon.png'}")


if __name__ == "__main__":
    main()
