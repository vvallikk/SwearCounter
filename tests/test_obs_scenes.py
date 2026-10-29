"""Правила смены сцены OBS: старые настройки, выбор правила по порогу и возврат прежней сцены."""

import asyncio

import pytest

from app import obs_scenes
from app.obs import ObsError

SECOND = 0.02


@pytest.mark.parametrize("saved, rules", [
    ({}, []),
    ({"scene": "", "scene_at": 0}, []),
    ({"scene": "Ад", "scene_at": 50}, [{"at": 50, "scene": "Ад"}]),
    ({"scene": "Ад", "scene_at": 0}, [{"at": 0, "scene": "Ад"}]),  # недозаполненное правило не теряется
    ({"scene_rules": [{"at": 5, "scene": "Ад"}, {"at": -1, "scene": "x"}, "мусор", {"at": True, "scene": "x"}],
      "scene": "Старое", "scene_at": 1}, [{"at": 5, "scene": "Ад"}]),
    ({"scene_rules": "мусор"}, []),
])
def test_saved_options_rules(saved, rules):
    assert obs_scenes.saved_options(saved)["scene_rules"] == rules


def test_saved_options_mirrors_first_rule_and_cleans_return():
    options = obs_scenes.saved_options({"scene_rules": [{"at": 3, "scene": "Ад"}], "scene_return": -5})
    assert options == {"scene_rules": [{"at": 3, "scene": "Ад"}], "scene_return": 0, "scene": "Ад", "scene_at": 3}


def test_saved_options_keeps_at_most_max_rules():
    rules = [{"at": i, "scene": "Ад"} for i in range(1, 9)]
    assert len(obs_scenes.saved_options({"scene_rules": rules})["scene_rules"]) == obs_scenes.MAX_RULES


@pytest.mark.parametrize("before, count, scene", [
    (0, 1, None), (4, 5, "Ад"), (5, 6, None), (4, 20, "Финал"), (9, 10, "Финал"), (10, 5, None),
])
def test_crossed_scene(before, count, scene):
    rules = [{"at": 10, "scene": "Финал"}, {"at": 5, "scene": "Ад"}, {"at": 7, "scene": ""}, {"at": 0, "scene": "Игра"}]
    assert obs_scenes.crossed_scene(rules, before, count) == scene


@pytest.mark.parametrize("rules, back, message", [
    ([(1, "Ад")] * 6, 0, "не больше"),
    ([(-1, "Ад")], 0, "Порог"),
    ([(1, "x" * 300)], 0, "длинное"),
    ([], obs_scenes.MAX_RETURN + 1, "Возврат"),
])
def test_check_options_rejects(rules, back, message):
    with pytest.raises(obs_scenes.ScenesError, match=message):
        obs_scenes.check_options(rules, back)


class FakeProgram:
    """Синхронный request(тип, данные), как у ObsLink: помнит текущую сцену и все запросы."""

    def __init__(self, scene="Игра", fail=()):
        self.scene, self.fail, self.calls = scene, set(fail), []

    def __call__(self, request_type, data=None):
        self.calls.append(request_type)
        if request_type in self.fail:
            raise ObsError("нет")
        if request_type == "GetCurrentProgramScene":
            return {"currentProgramSceneName": self.scene}  # obs-websocket до 5.3
        self.scene = data["sceneName"]
        return {}

    def switches(self):
        return self.calls.count("SetCurrentProgramScene")


def test_return_to_previous_scene():
    obs = FakeProgram()

    async def go():
        switcher = obs_scenes.SceneSwitcher(obs, SECOND)
        await switcher.switch("Ад", 1)
        assert obs.scene == "Ад"
        await asyncio.sleep(SECOND * 4)

    asyncio.run(go())
    assert obs.scene == "Игра"


def test_no_return_when_zero():
    obs = FakeProgram()

    async def go():
        await obs_scenes.SceneSwitcher(obs, SECOND).switch("Ад", 0)
        await asyncio.sleep(SECOND * 3)

    asyncio.run(go())
    assert obs.scene == "Ад" and "GetCurrentProgramScene" not in obs.calls


def test_next_rule_postpones_return_to_first_scene():
    obs = FakeProgram()

    async def go():
        switcher = obs_scenes.SceneSwitcher(obs, SECOND)
        await switcher.switch("Ад", 3)
        await asyncio.sleep(SECOND * 2)
        await switcher.switch("Финал", 3)
        await asyncio.sleep(SECOND * 2)  # первый возврат уже прошёл бы
        assert obs.scene == "Финал"
        await asyncio.sleep(SECOND * 3)

    asyncio.run(go())
    assert obs.scene == "Игра"


def test_manual_scene_change_cancels_return():
    obs = FakeProgram()

    async def go():
        await obs_scenes.SceneSwitcher(obs, SECOND).switch("Ад", 1)
        obs.scene = "Чат"
        await asyncio.sleep(SECOND * 4)

    asyncio.run(go())
    assert obs.scene == "Чат" and obs.switches() == 1


def test_unknown_current_scene_still_switches():
    obs = FakeProgram(fail={"GetCurrentProgramScene"})

    async def go():
        await obs_scenes.SceneSwitcher(obs, SECOND).switch("Ад", 1)
        await asyncio.sleep(SECOND * 3)

    asyncio.run(go())
    assert obs.scene == "Ад" and obs.switches() == 1


def test_close_cancels_return():
    obs = FakeProgram()

    async def go():
        switcher = obs_scenes.SceneSwitcher(obs, SECOND)
        await switcher.switch("Ад", 1)
        switcher.close()
        await asyncio.sleep(SECOND * 3)

    asyncio.run(go())
    assert obs.scene == "Ад"
