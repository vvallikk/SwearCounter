"""Сборка THIRD_PARTY_LICENSES.txt: лицензии всего чужого, что попадает в exe.

Пакеты Python — зависимости из requirements.txt со всеми их зависимостями:
тексты лицензий берутся из их dist-info. Компоненты, которые ставятся не через pip
или не кладут лицензию в пакет (сам Python, Vosk, PortAudio и др.), описаны в EXTRAS,
нужные тексты лежат в scripts/third_party/.
"""

import re
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent
TEXTS = Path(__file__).resolve().parent / "third_party"
_LICENSE_FILE_RE = re.compile(r"(licen[cs]e|copying|notice|authors)", re.IGNORECASE)
RULE = "=" * 78

HEADER = """Счётчик матов распространяется по лицензии GNU GPL v3 (файл LICENSE).
В программу входят компоненты сторонних авторов; ниже — их лицензии.

Swear Counter is licensed under the GNU GPL v3 (see LICENSE).
It includes third-party components; their licenses follow.
"""

# Имя, описание, файлы с текстами лицензий (из scripts/third_party/).
EXTRAS = [
    (
        "Vosk (vosk, libvosk.dll, включает Kaldi)",
        "Copyright Alpha Cephei Inc. Apache License 2.0. https://github.com/alphacep/vosk-api\n"
        "Модели распознавания в программу не входят: их скачивают с alphacephei.com,\n"
        "они распространяются Alpha Cephei Inc. по той же лицензии Apache 2.0.",
        ["Apache-2.0.txt"],
    ),
    (
        "PyInstaller (загрузчик SwearCounter.exe)",
        "GNU GPL v2 или новее с исключением для загрузчика: собранные программы можно\n"
        "распространять на любых условиях. https://pyinstaller.org/en/stable/license.html",
        [],
    ),
    (
        "PortAudio (libportaudio*.dll из пакета sounddevice)",
        "http://www.portaudio.com",
        ["PortAudio.txt"],
    ),
    (
        "MinGW-w64 runtime (libgcc_s_seh-1.dll, libstdc++-6.dll, libwinpthread-1.dll из пакета vosk)",
        "libgcc и libstdc++ — GNU GPL v3 с GCC Runtime Library Exception,\n"
        "libwinpthread — MIT/BSD. https://www.mingw-w64.org",
        [],
    ),
    (
        "Microsoft Edge WebView2 SDK (Microsoft.Web.WebView2.*.dll из пакета pywebview)",
        "Copyright Microsoft Corporation. Распространяется на условиях лицензии WebView2 SDK:\n"
        "https://www.nuget.org/packages/Microsoft.Web.WebView2/ (License Info)",
        [],
    ),
]


def runtime_distributions(requirements: Path = ROOT / "requirements.txt") -> list:
    """Пакеты из requirements.txt и все их зависимости (для текущей платформы)."""
    pending = [
        Requirement(line.split("#")[0].strip())
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.split("#")[0].strip() and not line.startswith("-")
    ]
    found = {}
    while pending:
        req = pending.pop()
        name = canonicalize_name(req.name)
        if name in found:
            continue
        try:
            dist = distribution(req.name)
        except PackageNotFoundError:
            continue  # зависимость для другой платформы или необязательная
        found[name] = dist
        for spec in dist.requires or []:
            dep = Requirement(spec)
            if dep.marker is None or dep.marker.evaluate({"extra": ""}):
                pending.append(dep)
    return sorted(found.values(), key=lambda d: canonicalize_name(d.metadata["Name"]))


def _license_files(dist) -> list[tuple[str, str]]:
    texts = []
    for file in dist.files or []:
        if ".dist-info" not in str(file) or not _LICENSE_FILE_RE.search(file.name):
            continue
        try:
            texts.append((file.name, file.locate().read_text(encoding="utf-8", errors="replace")))
        except OSError:
            pass
    return texts


def _license_name(dist) -> str:
    meta = dist.metadata
    name = meta.get("License-Expression") or (meta.get("License") or "").split("\n")[0].strip()
    if name and name != "UNKNOWN" and len(name) < 80:
        return name
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License")]
    return ", ".join(classifiers) or "см. сайт проекта"


def _project_url(urls: list[str]) -> str:
    """Главная страница проекта из Project-URL: «Homepage» или «Source», иначе первая."""
    pairs = [u.split(",", 1) for u in urls if "," in u]
    for label, url in pairs:
        if label.strip().lower() in ("homepage", "home", "source", "source code", "code", "repository"):
            return url.strip()
    return pairs[0][1].strip() if pairs else ""


def _section(title: str, about: str, texts: list[tuple[str, str]]) -> str:
    parts = [RULE, title, RULE, about.strip(), ""]
    for name, text in texts:
        parts += [f"--- {name} ---", text.strip(), ""]
    return "\n".join(parts)


def build_notices() -> str:
    sections = [HEADER]
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    sections.append(
        _section(
            f"Python {sys.version.split()[0]}",
            "Python Software Foundation License. https://www.python.org",
            [("LICENSE.txt", python_license.read_text(encoding="utf-8", errors="replace"))]
            if python_license.exists()
            else [],
        )
    )
    for dist in runtime_distributions():
        meta = dist.metadata
        url = meta.get("Home-page") or _project_url(meta.get_all("Project-URL") or [])
        about = f"Версия {dist.version}. Лицензия: {_license_name(dist)}. {url}".strip()
        sections.append(_section(meta["Name"], about, _license_files(dist)))
    for title, about, files in EXTRAS:
        texts = [(name, (TEXTS / name).read_text(encoding="utf-8")) for name in files]
        sections.append(_section(title, about, texts))
    return "\n".join(sections)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(build_notices())
