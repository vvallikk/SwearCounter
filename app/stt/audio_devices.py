"""Список микрофонов и поиск микрофона по имени.

Микрофон открывается через стандартный для системы интерфейс (на Windows это
MME: работает с любой частотой и без монопольного доступа). Но MME обрезает
имена до 31 символа, поэтому для показа берём полное имя того же устройства
из других интерфейсов (DirectSound, WASAPI), где имя начинается так же.

Микрофон в настройках хранится по полному имени: номера устройств меняются,
когда что-то подключают или отключают.
"""

import sounddevice as sd


def refresh() -> None:
    """Перечитывает список устройств: PortAudio запоминает его при запуске."""
    sd._terminate()
    sd._initialize()


def _system_inputs() -> list[tuple[int, str]]:
    """(номер, имя) микрофонов основного интерфейса системы, без «переназначения»."""
    api = sd.default.hostapi
    inputs = [
        (index, device["name"])
        for index, device in enumerate(sd.query_devices())
        if device["hostapi"] == api and device["max_input_channels"] > 0
    ]
    # В MME первое устройство ввода — «Переназначение звуковых устр.» (Sound Mapper),
    # то есть просто системный микрофон по умолчанию; его заменяет пункт «По умолчанию».
    if sd.query_hostapis(api)["name"] == "MME" and inputs:
        inputs = inputs[1:]
    return inputs


# Интерфейсы, где имена устройств полные и такие же, как в настройках звука Windows.
# В WDM-KS имена служебные (например, «Микрофон (... Wave)»), их не берём.
_LONG_NAME_APIS = ("Windows DirectSound", "Windows WASAPI")


def _long_names() -> list[str]:
    apis = {i for i, api in enumerate(sd.query_hostapis()) if api["name"] in _LONG_NAME_APIS}
    return [
        d["name"]
        for d in sd.query_devices()
        if d["hostapi"] in apis and d["max_input_channels"] > 0
    ]


def _full_name(short: str, all_names: list[str]) -> str:
    candidates = [name for name in all_names if name.startswith(short)]
    return max(candidates, key=len, default=short)


def list_inputs() -> list[str]:
    """Полные имена микрофонов в порядке системы."""
    all_names = _long_names()
    return [_full_name(name, all_names) for _, name in _system_inputs()]


def display_name(index: int) -> str:
    """Полное имя устройства с номером index."""
    all_names = _long_names()
    return _full_name(sd.query_devices(index)["name"], all_names)


def default_input_name() -> str | None:
    """Полное имя системного микрофона по умолчанию."""
    index = sd.default.device[0]
    if index is None or index < 0:
        return None
    return display_name(index)


def resolve(device: int | str | None) -> int | None:
    """Номер устройства для открытия: по полному имени, номеру или None (по умолчанию)."""
    if device is None or isinstance(device, int):
        return device
    inputs = _system_inputs()
    for index, name in inputs:
        if device.startswith(name):
            return index
    # Часть имени, как в ключе --device: подходит, если совпадение одно.
    all_names = _long_names()
    matches = [i for i, name in inputs if device.lower() in _full_name(name, all_names).lower()]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f"Микрофон «{device}» не найден: возможно, он отключён")
