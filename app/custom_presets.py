"""Личные оформления: наборы, которые ставятся из zip-архива в папку presets/ рядом с exe.

Набор не входит в программу и её репозиторий: автор делает его для конкретного человека
и передаёт архив только ему. Внутри архива (файлы в корне или в одной общей папке):

    preset.json    {"id", "title", "description", "color", "owner", "animation", "sound"}
    style.css      оформление, селекторы :root[data-preset="<id>"] (необязательно)
    animation.js   своя анимация прибавления (необязательно), см. docs/PRESETS.md
    картинки, шрифты и звуки, на которые ссылаются style.css и preset.json

Наборы устанавливает сам пользователь, как плагины OBS: animation.js выполняется
на странице оверлея. Поэтому устанавливать стоит только наборы от автора программы.
"""

import io
import json
import logging
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

log = logging.getLogger(__name__)

MAX_PACK_BYTES = 20 * 1024 * 1024  # архив и распакованные файлы вместе
MAX_PACK_FILES = 200
MAX_PRESETS = 50
MANIFEST = "preset.json"
STYLE = "style.css"
SCRIPT = "animation.js"
PRESET_ID = re.compile(r"[a-z0-9-]{1,32}")
HEX_COLOR = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
# Только то, что нужно оформлению и что браузер OBS открывает сам.
ALLOWED_SUFFIXES = {
    ".json", ".css", ".js", ".txt", ".md",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".woff", ".woff2", ".ttf", ".otf",
    ".mp3", ".wav", ".ogg",
}
SOUND_SUFFIXES = {".mp3", ".wav", ".ogg"}
TEXT_LIMITS = {"title": 40, "description": 300, "owner": 40}
URL_PREFIX = "/overlay/custom"


def builtin_preset_ids(overlay_dir: Path) -> set[str]:
    """Id встроенных пресетов из overlay/presets.js: личный набор не может их занять."""
    try:
        text = (Path(overlay_dir) / "presets.js").read_text(encoding="utf-8")
    except OSError:
        return set()
    return set(re.findall(r'\bid: "([^"]+)"', text))


class CustomPresets:
    def __init__(self, directory: Path, builtin_ids: set[str] = frozenset()):
        self.directory = Path(directory)
        self.builtin_ids = set(builtin_ids)

    def list(self) -> list[dict]:
        """Установленные наборы для оверлея и страницы управления; битые пропускаются."""
        result = []
        if not self.directory.is_dir():
            return result
        for folder in sorted(self.directory.iterdir(), key=lambda p: p.name):
            if not folder.is_dir() or folder.name.startswith(".") or folder.name in self.builtin_ids:
                continue
            try:
                manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8-sig"))
                info = validate_manifest(manifest, self.builtin_ids)
            except (OSError, ValueError) as e:
                log.warning("Оформление %s пропущено: %s", folder.name, e)
                continue
            if info["id"] != folder.name:
                log.warning("Оформление %s пропущено: id в preset.json — %s", folder.name, info["id"])
                continue
            result.append(self._describe(folder, info))
        return result

    def ids(self) -> set[str]:
        return {preset["id"] for preset in self.list()}

    def install(self, data: bytes) -> dict:
        """Ставит набор из zip (с заменой прежней версии). ValueError — если архив не подходит."""
        info, files = read_pack(data, self.builtin_ids)
        preset_id = info["id"]
        if preset_id not in self.ids() and len(self.list()) >= MAX_PRESETS:
            raise ValueError(f"Уже установлено {MAX_PRESETS} оформлений: удалите ненужные")
        self._write(preset_id, files)
        log.info("Установлено оформление %s", preset_id)
        return next(p for p in self.list() if p["id"] == preset_id)

    def export(self, preset_id: str) -> bytes:
        """Zip установленного набора, чтобы передать его дальше; KeyError, если такого нет."""
        if preset_id not in self.ids():
            raise KeyError(preset_id)
        return pack_folder(self.directory / preset_id, self.builtin_ids)[1]

    def remove(self, preset_id: str) -> None:
        """Удаляет набор; KeyError, если такого нет."""
        if preset_id not in self.ids():
            raise KeyError(preset_id)
        shutil.rmtree(self.directory / preset_id)
        log.info("Удалено оформление %s", preset_id)

    def _write(self, preset_id: str, files: dict[str, tuple[PurePosixPath, bytes]]) -> None:
        # Сначала во временную папку: при ошибке записи прежняя версия набора не пострадает.
        self.directory.mkdir(parents=True, exist_ok=True)
        staging = self.directory / f".{preset_id}.new"
        target = self.directory / preset_id
        shutil.rmtree(staging, ignore_errors=True)
        try:
            for relative, content in files.values():
                path = staging.joinpath(*relative.parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            shutil.rmtree(target, ignore_errors=True)
            staging.rename(target)
        except OSError as e:
            shutil.rmtree(staging, ignore_errors=True)
            raise ValueError(f"Не удалось сохранить оформление: {e}") from None

    def _describe(self, folder: Path, info: dict) -> dict:
        base = f"{URL_PREFIX}/{info['id']}"
        sound = info.get("sound")
        return {
            **info,
            "custom": True,
            "sound": f"{base}/{sound}" if sound else None,
            "style": f"{base}/{STYLE}" if (folder / STYLE).is_file() else None,
            "script": f"{base}/{SCRIPT}" if (folder / SCRIPT).is_file() else None,
        }


def read_pack(data: bytes, builtin_ids: set[str]) -> tuple[dict, dict[str, tuple[PurePosixPath, bytes]]]:
    """Проверенный preset.json и файлы набора из zip; ValueError с понятной причиной."""
    if len(data) > MAX_PACK_BYTES:
        raise ValueError(f"Архив больше {MAX_PACK_BYTES // (1024 * 1024)} МБ")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("Это не zip-архив с оформлением") from None
    with archive:
        files = _pack_files(archive)
    try:
        manifest = json.loads(files[MANIFEST][1].decode("utf-8-sig"))
    except KeyError:
        raise ValueError("В архиве нет preset.json") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("preset.json не читается: проверьте, что это JSON в UTF-8") from None
    info = validate_manifest(manifest, builtin_ids)
    sound = info.get("sound")
    if sound is not None and sound not in files:
        raise ValueError(f"Звука {sound} нет в архиве")
    return info, files


def pack_folder(folder: Path, builtin_ids: set[str] = frozenset()) -> tuple[dict, bytes]:
    """Собирает zip из папки набора и проверяет его так же, как при установке.

    Файлы лежат в архиве в папке <id>/: так архив выглядит понятно и после распаковки.
    """
    folder = Path(folder)
    if not (folder / MANIFEST).is_file():
        raise ValueError(f"В папке {folder} нет preset.json")
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("preset.json не читается: проверьте, что это JSON в UTF-8") from None
    preset_id = validate_manifest(manifest, builtin_ids)["id"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            relative = path.relative_to(folder).as_posix()
            if path.is_file() and not _ignored(relative) and not relative.startswith("."):
                archive.write(path, f"{preset_id}/{relative}")
    data = buffer.getvalue()
    info, _ = read_pack(data, builtin_ids)
    return info, data


def validate_manifest(manifest, builtin_ids: set[str]) -> dict:
    """Проверенные поля preset.json; ValueError с понятной причиной."""
    if not isinstance(manifest, dict):
        raise ValueError("preset.json должен быть объектом JSON")
    preset_id = manifest.get("id")
    if not isinstance(preset_id, str) or not PRESET_ID.fullmatch(preset_id):
        raise ValueError("id в preset.json: от 1 до 32 символов, латиница в нижнем регистре, цифры и -")
    if preset_id in builtin_ids:
        raise ValueError(f"id «{preset_id}» занят встроенным оформлением")
    info = {"id": preset_id}
    for field, limit in TEXT_LIMITS.items():
        value = manifest.get(field, "")
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise ValueError(f"{field} в preset.json: строка до {limit} символов")
        info[field] = " ".join(value.split())
    if not info["title"]:
        raise ValueError("В preset.json нет title — названия оформления")
    color = manifest.get("color", "#ffffff")
    if not isinstance(color, str) or not HEX_COLOR.fullmatch(color):
        raise ValueError("color в preset.json: цвет вида #ffcc00")
    info["color"] = color
    animation = manifest.get("animation")
    if animation is not None and (not isinstance(animation, str) or not PRESET_ID.fullmatch(animation)):
        raise ValueError("animation в preset.json: id встроенного оформления, например explosion")
    info["animation"] = animation
    sound = manifest.get("sound")
    if sound is not None:
        if (
            not isinstance(sound, str)
            or _safe_path(sound) is None
            or PurePosixPath(sound).suffix.lower() not in SOUND_SUFFIXES
        ):
            raise ValueError("sound в preset.json: имя файла .mp3, .wav или .ogg из архива")
        sound = str(_safe_path(sound))
    info["sound"] = sound
    return info


def _safe_path(name: str) -> PurePosixPath | None:
    """Путь внутри набора или None, если он выходит за его пределы."""
    path = PurePosixPath(name.replace("\\", "/"))
    if not name or path.is_absolute() or any(part in ("", ".", "..") or ":" in part for part in path.parts):
        return None
    return path


def _pack_files(archive: zipfile.ZipFile) -> dict[str, tuple[PurePosixPath, bytes]]:
    """Файлы набора: путь внутри набора (строкой) → (путь, содержимое).

    Если всё лежит в одной общей папке (так получается при «Сжать папку»), она убирается.
    """
    entries = [info for info in archive.infolist() if not info.is_dir()]
    entries = [info for info in entries if not _ignored(info.filename)]
    if not entries:
        raise ValueError("Архив пустой")
    if len(entries) > MAX_PACK_FILES:
        raise ValueError(f"В архиве больше {MAX_PACK_FILES} файлов")
    if sum(info.file_size for info in entries) > MAX_PACK_BYTES:
        raise ValueError(f"Распакованное оформление больше {MAX_PACK_BYTES // (1024 * 1024)} МБ")
    paths = []
    for info in entries:
        path = _safe_path(info.filename)
        if path is None:
            raise ValueError(f"Недопустимый путь в архиве: {info.filename}")
        paths.append(path)
    tops = {path.parts[0] for path in paths}
    if len(tops) == 1 and all(len(path.parts) > 1 for path in paths):
        paths = [PurePosixPath(*path.parts[1:]) for path in paths]
    files = {}
    for info, path in zip(entries, paths):
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError(f"Файл {path} не подходит для оформления")
        content = archive.read(info)
        if len(content) != info.file_size:
            raise ValueError("Архив повреждён")
        files[str(path)] = (path, content)
    return files


def _ignored(name: str) -> bool:
    """Служебные файлы, которые добавляют архиваторы macOS и Windows."""
    parts = name.replace("\\", "/").split("/")
    return "__MACOSX" in parts or parts[-1] in (".DS_Store", "Thumbs.db", "desktop.ini")
