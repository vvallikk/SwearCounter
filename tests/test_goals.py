"""Цели и пороги: особые числа, цель «осталось N» и сообщение milestone."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import goals
from app.goals import DEFAULT_MILESTONES, GoalsError, clean_goal, clean_milestones, reached
from app.server import Hub, create_app
from conftest import skip_greeting
from test_server import SMALL, FakeRecognizer


def test_clean_milestones_sorts_and_dedupes():
    assert clean_milestones([100, 10, 50, 10]) == [10, 50, 100]
    assert clean_milestones([]) == []


@pytest.mark.parametrize("values", [[0], [-5], [goals.MAX_VALUE + 1], list(range(1, goals.MAX_MILESTONES + 2))])
def test_clean_milestones_rejects(values):
    with pytest.raises(GoalsError):
        clean_milestones(values)


def test_clean_goal():
    assert clean_goal(0) == 0
    assert clean_goal(300) == 300
    with pytest.raises(GoalsError):
        clean_goal(-1)


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (9, 10, 10),
        (10, 11, None),  # уже праздновали
        (8, 9, None),
        (45, 105, 100),  # +60 разом — празднуем наибольшее
        (20, 30, 25),  # цель тоже особое число
    ],
)
def test_reached(before, after, expected):
    assert reached([10, 50, 100], 25, before, after) == expected


def test_reached_without_goal():
    assert reached([], 0, 0, 1_000) is None


# --- сервер ---


@pytest.fixture
def make_client(counter, models_dir, settings, tmp_path, fake_sd):
    from app.sound import Sound

    (models_dir / SMALL).mkdir()

    def make():
        hub = Hub(counter)
        app = create_app(hub, FakeRecognizer(models_dir / SMALL), settings, Sound(settings, tmp_path / "s"))
        return hub, TestClient(app, base_url="http://localhost")

    return make


def test_defaults(make_client):
    hub, client = make_client()
    with client:
        assert client.get("/api/goals").json() == {"milestones": DEFAULT_MILESTONES, "goal": 0}
    assert hub.milestones == DEFAULT_MILESTONES


def test_saved_goals_loaded(make_client, settings):
    settings.set("milestones", [5])
    settings.set("goal", 42)
    hub, client = make_client()
    assert (hub.milestones, hub.goal) == ([5], 42)


@pytest.mark.parametrize(("milestones", "goal"), [("10, 50", 0), ([0], 0), ([10], -3), ([10], "много")])
def test_broken_settings_fall_back(make_client, settings, milestones, goal):
    settings.set("milestones", milestones)
    settings.set("goal", goal)
    hub, _ = make_client()
    assert (hub.milestones, hub.goal) == (DEFAULT_MILESTONES, 0)


def test_set_goals_saves_and_broadcasts(make_client, settings):
    hub, client = make_client()
    with client, client.websocket_connect("ws://localhost/ws") as ws:
        greeting = skip_greeting(ws)
        assert greeting[3] == {"type": "goals", "milestones": DEFAULT_MILESTONES, "goal": 0}
        state = client.post("/api/goals", json={"milestones": [3, 1], "goal": 20}).json()
        assert state == {"milestones": [1, 3], "goal": 20}
        assert ws.receive_json() == {"type": "goals", "milestones": [1, 3], "goal": 20}
    assert settings.get("milestones") == [1, 3]
    assert settings.get("goal") == 20


@pytest.mark.parametrize("body", [{"milestones": [0]}, {"milestones": [], "goal": -1}, {"milestones": ["x"]}])
def test_set_goals_rejects(make_client, settings, body):
    _, client = make_client()
    with client:
        response = client.post("/api/goals", json=body)
    assert response.status_code in (400, 422)
    assert settings.get("milestones") is None


def test_increment_reports_milestone(make_client):
    _, client = make_client()
    with client:
        client.post("/api/goals", json={"milestones": [2], "goal": 3})
        with client.websocket_connect("ws://localhost/ws") as ws:
            skip_greeting(ws)
            seen = []
            for _ in range(4):
                client.post("/api/increment")
                message = ws.receive_json()
                assert ws.receive_json()["type"] == "timer"
                seen.append(message.get("milestone"))
    assert seen == [None, 2, 3, None]


def test_hub_milestone_for_big_delta(counter):
    hub = Hub(counter)
    hub.milestones = [10, 50]
    sent = []

    class Ws:
        async def send_json(self, message):
            sent.append(message)

    hub.clients.add(Ws())
    asyncio.run(hub.increment(60))
    assert sent[0] == {"type": "increment", "count": 60, "delta": 60, "milestone": 50}
