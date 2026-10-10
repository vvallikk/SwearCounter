"""Список микрофонов и поиск по имени на поддельной таблице устройств Windows."""

import pytest

from app.stt import audio_devices
from conftest import HYPERX, REALTEK, STEAM, mme

# Номера MME-микрофонов в windows_devices().
REALTEK_INDEX, HYPERX_INDEX, STEAM_INDEX = 1, 2, 3


def test_list_inputs_uses_full_names_without_mapper(fake_sd):
    # Без «переназначения», без выходов, без WDM-KS и в порядке MME.
    assert audio_devices.list_inputs() == [REALTEK, HYPERX, STEAM]


def test_list_inputs_keeps_first_device_outside_mme(fake_sd):
    fake_sd.default.hostapi = 2  # WASAPI: «переназначения» там нет
    assert audio_devices.list_inputs() == [REALTEK, HYPERX, STEAM]


def test_display_name_ignores_wdm_ks_names(fake_sd):
    assert audio_devices.display_name(HYPERX_INDEX) == HYPERX


def test_display_name_keeps_short_name_without_long_match(fake_sd):
    fake_sd.devices[STEAM_INDEX]["name"] = "Line In (Virtual Cable)"
    assert audio_devices.display_name(STEAM_INDEX) == "Line In (Virtual Cable)"


def test_default_input_name(fake_sd):
    assert audio_devices.default_input_name() == REALTEK


@pytest.mark.parametrize("index", [None, -1])
def test_default_input_name_without_microphone(fake_sd, index):
    fake_sd.default.device = [index, 5]
    assert audio_devices.default_input_name() is None


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        (None, None),  # системный по умолчанию
        (7, 7),  # номер передаётся как есть
        (HYPERX, HYPERX_INDEX),  # полное имя из настроек
        (mme(HYPERX), HYPERX_INDEX),  # обрезанное имя MME
        (REALTEK, REALTEK_INDEX),
        ("steam", STEAM_INDEX),  # часть имени, как в --device, без учёта регистра
        ("Flight Wireless", HYPERX_INDEX),  # часть, которой нет в обрезанном имени
    ],
)
def test_resolve(fake_sd, device, expected):
    assert audio_devices.resolve(device) == expected


@pytest.mark.parametrize(
    "device",
    [
        "USB микрофон",  # отключённый микрофон
        "Микрофон",  # подходит к двум микрофонам
        "Переназначение звуковых устр. - Input",  # «переназначение» не выбирается
    ],
)
def test_resolve_unknown_or_ambiguous(fake_sd, device):
    with pytest.raises(ValueError, match="не найден"):
        audio_devices.resolve(device)


def test_refresh_reinitializes_portaudio(fake_sd):
    audio_devices.refresh()
    assert fake_sd.refreshes == 1
