"""Библиотека звуков оповещения (app/sound.py)."""

import pytest

from app.settings import Settings
from app.sound import MAX_SOUND_BYTES, MAX_SOUNDS, Sound

WAV = b"RIFF....WAVEfmt fake"


@pytest.fixture
def sound(tmp_path):
    return Sound(Settings(tmp_path / "settings.json"), tmp_path / "sounds")


def test_initial_state_is_standard_sound(sound):
    state = sound.state()
    assert state["active"] is None
    assert state["sounds"] == []
    assert state["volume"] == 100


def test_add_saves_file_and_makes_it_active(sound):
    sound_id = sound.add(WAV, "audio/wav", "дзынь.wav")
    state = sound.state()
    assert state["active"] == sound_id
    assert state["active_name"] == "дзынь.wav"
    assert state["sounds"] == [{"id": sound_id, "name": "дзынь.wav"}]
    assert sound.path(sound_id).read_bytes() == WAV
    assert sound.path(sound_id).suffix == ".wav"


def test_every_change_bumps_version(sound):
    versions = [sound.state()["version"]]
    sound_id = sound.add(WAV, "audio/wav", "a.wav")
    versions.append(sound.state()["version"])
    sound.select(None)
    versions.append(sound.state()["version"])
    sound.delete(sound_id)
    versions.append(sound.state()["version"])
    assert versions == sorted(set(versions))


@pytest.mark.parametrize(
    "content_type, data, message",
    [
        ("text/plain", WAV, "MP3, WAV и OGG"),
        ("audio/wav", b"", "пустой"),
        ("audio/mpeg", b"0" * (MAX_SOUND_BYTES + 1), "больше"),
    ],
    ids=["wrong-type", "empty", "too-big"],
)
def test_add_rejects_bad_files(sound, content_type, data, message):
    with pytest.raises(ValueError, match=message):
        sound.add(data, content_type, "x")
    assert sound.state()["sounds"] == []


def test_content_type_parameters_are_ignored(sound):
    sound_id = sound.add(WAV, "audio/mpeg; charset=binary", "a.mp3")
    assert sound.path(sound_id).suffix == ".mp3"


def test_library_size_is_limited(sound):
    for i in range(MAX_SOUNDS):
        sound.add(WAV, "audio/wav", f"{i}.wav")
    with pytest.raises(ValueError, match="удалите"):
        sound.add(WAV, "audio/wav", "лишний.wav")


def test_select_switches_between_sounds_and_standard(sound):
    first = sound.add(WAV, "audio/wav", "1.wav")
    second = sound.add(WAV, "audio/ogg", "2.ogg")
    assert sound.state()["active"] == second
    sound.select(first)
    assert sound.state()["active"] == first
    sound.select(None)
    assert sound.state()["active"] is None


def test_select_unknown_raises(sound):
    with pytest.raises(KeyError):
        sound.select("nope")


def test_delete_active_falls_back_to_standard(sound):
    sound_id = sound.add(WAV, "audio/wav", "a.wav")
    path = sound.path(sound_id)
    sound.delete(sound_id)
    assert not path.exists()
    assert sound.state()["active"] is None
    assert sound.state()["sounds"] == []


def test_delete_inactive_keeps_active(sound):
    first = sound.add(WAV, "audio/wav", "1.wav")
    second = sound.add(WAV, "audio/wav", "2.wav")
    sound.delete(first)
    assert sound.state()["active"] == second


def test_delete_unknown_raises(sound):
    with pytest.raises(KeyError):
        sound.delete("nope")


def test_entries_with_missing_files_are_hidden(sound):
    sound_id = sound.add(WAV, "audio/wav", "a.wav")
    sound.path(sound_id).unlink()
    assert sound.state()["sounds"] == []
    assert sound.path(sound_id) is None


def test_volume_is_clamped_and_persisted(tmp_path):
    settings_file = tmp_path / "settings.json"
    sound = Sound(Settings(settings_file), tmp_path / "sounds")
    sound.set_volume(150)
    assert sound.state()["volume"] == 100
    sound.set_volume(-5)
    assert sound.state()["volume"] == 0
    sound.set_volume(42)
    assert Sound(Settings(settings_file), tmp_path / "sounds").state()["volume"] == 42


def test_library_survives_restart(tmp_path):
    settings_file = tmp_path / "settings.json"
    sound_id = Sound(Settings(settings_file), tmp_path / "sounds").add(WAV, "audio/wav", "a.wav")
    restored = Sound(Settings(settings_file), tmp_path / "sounds").state()
    assert restored["active"] == sound_id
    assert restored["sounds"] == [{"id": sound_id, "name": "a.wav"}]


def test_migrates_single_custom_sound_from_previous_version(tmp_path):
    directory = tmp_path / "sounds"
    directory.mkdir()
    (directory / "custom.wav").write_bytes(WAV)
    settings = Settings(tmp_path / "settings.json")
    settings.set("sound_custom", {"file": "custom.wav", "name": "старый.wav"})

    sound = Sound(settings, directory)
    state = sound.state()
    assert state["active_name"] == "старый.wav"
    assert [s["name"] for s in state["sounds"]] == ["старый.wav"]
    assert sound.path(state["active"]).read_bytes() == WAV
    assert settings.get("sound_custom") is None
