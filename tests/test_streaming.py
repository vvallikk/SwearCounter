"""Интеграции со стримами: разбор чата, связь с Twitch и YouTube на подделках, логика счётчика, API."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.server import Hub, create_app
from app.sound import Sound
from app.streaming import Streaming, chat, options
from app.streaming import manager as manager_module
from app.streaming.chat import TWITCH, YOUTUBE, ChatMessage
from app.streaming.http import HttpError
from app.streaming.link import CONNECTED, ERROR, OFF, LinkError
from app.streaming.twitch import TwitchLink, validate_token
from app.streaming.youtube import YouTubeLink, youtube_message
from test_server import FakeRecognizer, SMALL


def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "не дождались"
        time.sleep(0.01)


# --- разбор чата ---


def test_parse_irc_tags_and_message():
    line = chat.parse_irc(
        "@badges=moderator/1;display-name=Vasya\\sP;mod=1;bits=100 :vasya!vasya@vasya.tmi.twitch.tv "
        "PRIVMSG #streamer :!маты +2"
    )
    assert line.command == "PRIVMSG"
    assert line.tags["display-name"] == "Vasya P"
    assert line.nick == "vasya"
    message = chat.twitch_message(line)
    assert message == ChatMessage(TWITCH, "Vasya P", "!маты +2", True, bits=100)


def test_twitch_message_viewer_action_and_other_commands():
    viewer = chat.twitch_message(chat.parse_irc("@badges=subscriber/6 :a!a@a PRIVMSG #c :привет"))
    assert not viewer.privileged
    me = chat.twitch_message(chat.parse_irc(":a!a@a PRIVMSG #c :\x01ACTION !маты\x01"))
    assert me.text == "!маты"
    assert chat.twitch_message(chat.parse_irc(":tmi.twitch.tv ROOMSTATE #c")) is None
    owner = chat.twitch_message(chat.parse_irc("@badges=broadcaster/1 :a!a@a PRIVMSG #c :x"))
    assert owner.privileged


def test_parse_irc_ping():
    line = chat.parse_irc("PING :tmi.twitch.tv")
    assert (line.command, line.trailing) == ("PING", "tmi.twitch.tv")


@pytest.mark.parametrize(
    ("text", "privileged", "mod_commands", "expected"),
    [
        ("!маты", False, True, chat.Action("show")),
        ("!МАТЫ", False, True, chat.Action("show")),
        ("!матыч", False, True, None),
        ("привет !маты", False, True, None),
        ("", False, True, None),
        ("!маты +3", True, True, chat.Action("add", 3)),
        ("!маты +3", False, True, chat.Action("show")),  # зритель не может менять счёт
        ("!маты +3", True, False, chat.Action("show")),
        ("!маты сброс", True, True, chat.Action("reset")),
        ("!маты reset", True, True, chat.Action("reset")),
        ("!маты +0", True, True, chat.Action("show")),
        ("!маты +101", True, True, chat.Action("show")),
        ("!маты -5", True, True, chat.Action("show")),
    ],
)
def test_parse_command(text, privileged, mod_commands, expected):
    assert chat.parse_command(text, "!маты", privileged, mod_commands) == expected


def test_render_keeps_unknown_placeholders():
    assert chat.render("Маты: {count} {user} {oops}", count=5, user="Вася") == "Маты: 5 Вася {oops}"


# --- настройки ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Streamer_1", "streamer_1"), ("@streamer", "streamer"), ("https://www.twitch.tv/Streamer", "streamer"),
     ("twitch.tv/streamer/videos", "streamer"), ("", "")],
)
def test_clean_channel(value, expected):
    assert options.clean_channel(value) == expected


@pytest.mark.parametrize("value", ["a", "bad name", "https://example.com/streamer", "ю" * 5])
def test_clean_channel_rejects(value):
    with pytest.raises(options.OptionsError):
        options.clean_channel(value)


@pytest.mark.parametrize(
    "value",
    ["dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5", "https://youtu.be/dQw4w9WgXcQ?si=x",
     "youtube.com/live/dQw4w9WgXcQ", "https://m.youtube.com/watch?v=dQw4w9WgXcQ"],
)
def test_clean_video(value):
    assert options.clean_video(value) == "dQw4w9WgXcQ"


def test_clean_video_rejects_other_sites():
    with pytest.raises(options.OptionsError):
        options.clean_video("https://example.com/watch?v=dQw4w9WgXcQ")


def test_clean_command_adds_exclamation_mark():
    assert options.clean_command("счёт") == "!счёт"
    with pytest.raises(options.OptionsError):
        options.clean_command("!два слова")


def test_load_defaults_and_corrupted():
    assert options.load(None)["twitch"]["enabled"] is False
    loaded = options.load({"twitch": {"enabled": True, "channel": "bad name"}, "youtube": "oops"})
    assert loaded["twitch"]["enabled"] is False  # испорченное — по умолчанию
    assert loaded["youtube"] == options.DEFAULTS["youtube"]


def test_token_prefix_is_stripped():
    assert options.clean_token("  oauth:abc123 ") == "abc123"
    assert options.clean_token("abc") == "abc"


# --- Twitch: связь ---


class FakeIrc:
    def __init__(self, incoming=()):
        self.incoming = list(incoming)
        self.sent: list[str] = []
        self.closed = False

    def send(self, line):
        self.sent.append(line)

    def read(self, timeout):
        if self.incoming:
            item = self.incoming.pop(0)
            if isinstance(item, Exception):
                raise item
            return [item]
        time.sleep(0.01)
        return []

    def close(self):
        self.closed = True


IDENTITY = {"login": "streamer", "user_id": "42", "client_id": "cid", "scopes": ["chat:read", "chat:edit"]}


def twitch_link(conn, messages, statuses=None, validate=lambda token: IDENTITY, post=None, retry=0.05):
    kwargs = {"post": post} if post else {}
    return TwitchLink(
        messages.append,
        lambda name, state: statuses.append((name, state)) if statuses is not None else None,
        connect=lambda: conn,
        validate=validate,
        retry=retry,
        **kwargs,
    )


def test_twitch_joins_reads_chat_and_answers_ping():
    conn = FakeIrc([":tmi.twitch.tv ROOMSTATE #streamer", "PING :tmi.twitch.tv",
                    "@mod=0;display-name=A :a!a@a PRIVMSG #streamer :!маты"])
    messages = []
    link = twitch_link(conn, messages)
    link.configure_chat("streamer", "tok")
    link.start()
    try:
        wait_for(lambda: len(messages) == 1)
        assert link.connected
        assert messages[0].text == "!маты"
        assert conn.sent[:4] == [
            "CAP REQ :twitch.tv/tags twitch.tv/commands",
            "PASS oauth:tok",
            "NICK streamer",
            "JOIN #streamer",
        ]
        assert "PONG :tmi.twitch.tv" in conn.sent
        assert link.say("Маты: 3")
        wait_for(lambda: "PRIVMSG #streamer :Маты: 3" in conn.sent)
        assert link.state()["login"] == "streamer"
        assert link.state()["can_mark"] is False  # у токена нет права на маркеры
    finally:
        link.stop()
    assert conn.closed
    assert link.state()["login"] == ""


def test_twitch_say_without_connection_is_dropped():
    link = twitch_link(FakeIrc(), [])
    assert link.say("привет") is False
    assert link.status == OFF


def test_twitch_bad_token_is_reported_and_no_connection_opened():
    def reject(token):
        raise LinkError("Twitch не принял токен", 60)

    opened = []
    link = TwitchLink(lambda m: None, connect=lambda: opened.append(1), validate=reject, retry=5)
    link.configure_chat("streamer", "bad")
    link.start()
    try:
        wait_for(lambda: link.status == ERROR)
        assert "токен" in link.state()["error"]
        assert opened == []
    finally:
        link.stop()


def test_twitch_auth_failed_notice():
    conn = FakeIrc([":tmi.twitch.tv NOTICE * :Login authentication failed"])
    link = twitch_link(conn, [])
    link.configure_chat("streamer", "tok")
    link.start()
    try:
        wait_for(lambda: link.status == ERROR)
    finally:
        link.stop()
    assert conn.closed


def test_twitch_reconnects_after_connection_loss():
    first = FakeIrc([ConnectionError("Twitch закрыл соединение")])
    second = FakeIrc([":tmi.twitch.tv ROOMSTATE #streamer"])
    conns = [first, second]
    link = TwitchLink(lambda m: None, connect=lambda: conns.pop(0), validate=lambda t: IDENTITY, retry=0.05)
    link.configure_chat("streamer", "tok")
    link.start()
    try:
        wait_for(lambda: link.connected)
    finally:
        link.stop()
    assert first.closed


def test_twitch_disable_closes_connection():
    conn = FakeIrc([":tmi.twitch.tv ROOMSTATE #streamer"])
    link = twitch_link(conn, [])
    link.configure_chat("streamer", "tok")
    link.start()
    try:
        wait_for(lambda: link.connected)
        link.configure_chat("", "tok")
        wait_for(lambda: link.status == OFF)
        assert conn.closed
    finally:
        link.stop()


def test_validate_token_checks_scopes():
    ok = {"login": "Streamer", "user_id": "1", "client_id": "c", "scopes": ["chat:read", "chat:edit"]}
    assert validate_token("t", get=lambda url, headers: ok)["login"] == "streamer"
    with pytest.raises(LinkError, match="chat:edit"):
        validate_token("t", get=lambda url, headers: ok | {"scopes": ["chat:read"]})

    def unauthorized(url, headers):
        raise HttpError(401, "", "invalid access token")

    with pytest.raises(LinkError, match="токен"):
        validate_token("t", get=unauthorized)


def test_twitch_marker_needs_scope_and_own_channel():
    posts = []
    conn = FakeIrc([":tmi.twitch.tv ROOMSTATE #streamer"])
    identity = IDENTITY | {"scopes": ["chat:read", "chat:edit", "channel:manage:broadcast"]}
    link = twitch_link(conn, [], validate=lambda t: identity, post=lambda url, headers, body: posts.append((url, headers, body)))
    link.configure_chat("streamer", "tok")
    link.start()
    try:
        wait_for(lambda: link.connected)
        link.marker("Мат №5")
    finally:
        link.stop()
    url, headers, body = posts[0]
    assert url.endswith("/streams/markers")
    assert headers == {"Authorization": "Bearer tok", "Client-Id": "cid"}
    assert body == {"user_id": "42", "description": "Мат №5"}


def test_twitch_marker_unavailable_for_foreign_channel():
    conn = FakeIrc([":tmi.twitch.tv ROOMSTATE #other"])
    link = twitch_link(conn, [])
    link.configure_chat("other", "tok")
    link.start()
    try:
        wait_for(lambda: link.connected)
        assert link.state()["can_mark"] is False
        with pytest.raises(LinkError):
            link.marker("x")
    finally:
        link.stop()


# --- YouTube: связь ---


def chat_item(kind="textMessageEvent", text="!маты", moderator=False):
    snippet = {"type": kind, "textMessageDetails": {"messageText": text}}
    return {"snippet": snippet, "authorDetails": {"displayName": "Вася", "isChatModerator": moderator, "isChatOwner": False}}


class FakeYouTubeApi:
    def __init__(self, pages):
        self.pages = list(pages)
        self.urls: list[str] = []

    def __call__(self, url, headers=None, body=None, timeout=None):
        self.urls.append(url)
        if "/videos?" in url:
            return {"items": [{"snippet": {"title": "Стрим"}, "liveStreamingDetails": {"activeLiveChatId": "CHAT"}}]}
        page = self.pages.pop(0) if self.pages else {"items": [], "pollingIntervalMillis": 20}
        if isinstance(page, Exception):
            raise page
        return page


def youtube_link(api, messages, **kwargs):
    return YouTubeLink(messages.append, get=api, retry=0.05, min_poll=0.01, **kwargs)


def test_youtube_skips_history_and_delivers_new_messages():
    api = FakeYouTubeApi([
        {"items": [chat_item(text="!маты старое")], "nextPageToken": "T1", "pollingIntervalMillis": 20},
        {"items": [chat_item(text="!маты +1", moderator=True)], "nextPageToken": "T2", "pollingIntervalMillis": 20},
    ])
    messages = []
    link = youtube_link(api, messages)
    link.configure_chat("dQw4w9WgXcQ", "KEY")
    link.start()
    try:
        wait_for(lambda: len(messages) == 1)
    finally:
        link.stop()
    assert messages[0] == ChatMessage(YOUTUBE, "Вася", "!маты +1", True)
    assert link.title == "Стрим"
    poll_urls = [u for u in api.urls if "liveChat/messages" in u]
    assert "pageToken" not in poll_urls[0]
    assert "pageToken=T1" in poll_urls[1]
    assert "key=KEY" in poll_urls[0]


def test_youtube_quota_error_is_reported():
    api = FakeYouTubeApi([HttpError(403, "quotaExceeded", "quota")])
    link = youtube_link(api, [])
    link.configure_chat("dQw4w9WgXcQ", "KEY")
    link.start()
    try:
        wait_for(lambda: link.status == ERROR)
        assert "квота" in link.state()["error"]
    finally:
        link.stop()


def test_youtube_no_active_chat():
    def api(url, headers=None, body=None, timeout=None):
        return {"items": [{"snippet": {"title": "Запись"}, "liveStreamingDetails": {}}]}

    link = youtube_link(api, [])
    link.configure_chat("dQw4w9WgXcQ", "KEY")
    link.start()
    try:
        wait_for(lambda: link.status == ERROR)
        assert "нет активного чата" in link.state()["error"]
    finally:
        link.stop()


def test_youtube_message_kinds():
    assert youtube_message(chat_item(kind="superChatEvent")).paid == 1
    assert youtube_message(chat_item(kind="newSponsorEvent")) is None
    assert youtube_message({"snippet": {}}) is None


# --- логика: чат ↔ счётчик ---


class FakeLink:
    def __init__(self):
        self.said: list[str] = []
        self.markers: list[str] = []
        self.connected = True
        self.can_mark = True

    def say(self, text):
        self.said.append(text)
        return True

    def marker(self, description):
        self.markers.append(description)

    def state(self):
        return {"status": CONNECTED, "error": "", "can_mark": self.can_mark}

    def configure_chat(self, *args):
        pass

    def start(self):
        pass

    def stop(self):
        pass


@pytest.fixture
def rig(counter, settings):
    hub = Hub(counter)
    twitch = FakeLink()
    streaming = Streaming(hub, settings, twitch=twitch, youtube=FakeLink())
    streaming.attach()

    def configure(platform=TWITCH, **values):
        saved = streaming.options()
        saved[platform] = saved[platform] | {"enabled": True, "channel": "streamer", "video": "dQw4w9WgXcQ"} | values
        settings.set(options.SETTING, saved)

    streaming.configure = configure
    streaming.fake_twitch = twitch
    return streaming


def run(streaming, scenario):
    async def go():
        streaming._loop = asyncio.get_running_loop()
        await scenario()
        await asyncio.sleep(0)
        for task in list(streaming._background):
            await task

    asyncio.run(go())


def viewer(text, **kwargs):
    return ChatMessage(TWITCH, "Зритель", text, **kwargs)


def test_command_replies_with_count_and_respects_cooldown(rig):
    rig.configure(cooldown=60)

    async def scenario():
        await rig.hub.increment(4)
        await rig.handle_message(viewer("!маты"))
        await rig.handle_message(viewer("!маты"))  # слишком быстро
        await rig.handle_message(viewer("!маты", privileged=True))  # модератору отвечаем всегда

    run(rig, scenario)
    assert rig.fake_twitch.said == ["Маты: 4", "Маты: 4"]


def test_disabled_platform_ignores_chat(rig):
    async def scenario():
        await rig.handle_message(viewer("!маты"))
        await rig.handle_message(viewer("!маты +5", privileged=True, bits=500))

    run(rig, scenario)
    assert rig.fake_twitch.said == []
    assert rig.hub.counter.value == 0


def test_moderator_can_add_and_reset(rig):
    rig.configure()

    async def scenario():
        await rig.handle_message(viewer("!маты +3", privileged=True))
        assert rig.hub.counter.value == 3
        await rig.handle_message(viewer("!маты +9"))  # зритель — просто показать
        assert rig.hub.counter.value == 3
        await rig.handle_message(viewer("!маты сброс", privileged=True))
        assert rig.hub.counter.value == 0

    run(rig, scenario)
    assert rig.fake_twitch.said[-1] == "Маты: 0"


def test_bits_add_swears(rig):
    rig.configure(bits_per_swear=100)

    async def scenario():
        await rig.handle_message(viewer("держи", bits=250))
        await rig.handle_message(viewer("мало", bits=50))

    run(rig, scenario)
    assert rig.hub.counter.value == 2


def test_superchat_adds_swears_on_youtube(rig):
    rig.configure(YOUTUBE, superchat_swears=3)

    async def scenario():
        await rig.handle_message(ChatMessage(YOUTUBE, "Зритель", "", paid=1))
        await rig.handle_message(ChatMessage(YOUTUBE, "Зритель", "просто текст"))

    run(rig, scenario)
    assert rig.hub.counter.value == 3
    assert rig.fake_twitch.said == []  # ответов в YouTube нет


def test_youtube_command_does_not_reply_but_mod_add_works(rig):
    rig.configure(YOUTUBE)

    async def scenario():
        await rig.handle_message(ChatMessage(YOUTUBE, "М", "!маты +2", privileged=True))
        await rig.handle_message(ChatMessage(YOUTUBE, "З", "!маты"))

    run(rig, scenario)
    assert rig.hub.counter.value == 2
    assert rig.fake_twitch.said == []


def test_announces_milestones_and_every_n(rig):
    rig.configure(announce_every=7)
    rig.hub.milestones, rig.hub.goal = [3], 0

    async def scenario():
        await rig.hub.increment(3)  # особое число 3
        await rig.hub.increment(1)  # ничего
        await rig.hub.increment(3)  # 7: каждые 7

    run(rig, scenario)
    assert rig.fake_twitch.said == ["🎉 Счёт достиг 3! Сейчас: 3", "🎉 Счёт достиг 7! Сейчас: 7"]


def test_markers_are_throttled(rig, monkeypatch):
    rig.configure(markers=True, announce_milestones=False)

    async def scenario():
        await rig.hub.increment(1)
        await rig.hub.increment(1)  # сразу за первым — маркер не ставим

    run(rig, scenario)
    assert rig.fake_twitch.markers == ["Мат №1"]


def test_markers_off_by_default_and_without_scope(rig):
    rig.configure()

    async def scenario():
        await rig.hub.increment(1)

    run(rig, scenario)
    assert rig.fake_twitch.markers == []
    rig.configure(markers=True)
    rig.fake_twitch.can_mark = False
    rig._last_marker = float("-inf")
    run(rig, scenario)
    assert rig.fake_twitch.markers == []


def test_no_announcements_when_twitch_not_connected(rig):
    rig.configure(announce_every=1)
    rig.fake_twitch.connected = False

    async def scenario():
        await rig.hub.increment(1)

    run(rig, scenario)
    assert rig.fake_twitch.said == []


# --- API ---


@pytest.fixture
def api_client(tmp_path, settings, counter, fake_sd, models_dir):
    (models_dir / SMALL).mkdir()
    app = create_app(Hub(counter), FakeRecognizer(models_dir / SMALL), settings, Sound(settings, tmp_path / "sounds"))
    streaming = app.state.streaming

    def no_network(token):
        raise LinkError("проверка токена в тесте не выполняется", 60)

    streaming.twitch._validate = no_network
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def test_api_defaults(api_client):
    state = api_client.get("/api/streaming").json()
    assert state["twitch"]["enabled"] is False
    assert state["twitch"]["status"] == "off"
    assert state["twitch"]["has_token"] is False
    assert state["twitch"]["command"] == "!маты"
    assert state["youtube"]["status"] == "off"


def test_api_saves_options_and_hides_secrets(api_client, settings):
    body = {"twitch": {"enabled": True, "channel": "https://twitch.tv/Streamer", "token": "oauth:SECRET",
                       "announce_every": 5, "markers": True}}
    state = api_client.post("/api/streaming", json=body).json()
    assert state["twitch"]["channel"] == "streamer"
    assert state["twitch"]["has_token"] is True
    assert "SECRET" not in api_client.get("/api/streaming").text
    assert settings.get("twitch_token") == "SECRET"
    wait_for(lambda: api_client.get("/api/streaming").json()["twitch"]["status"] == "error")
    # Токен None — оставить сохранённый; настройки youtube не менялись.
    again = api_client.post("/api/streaming", json={"twitch": {"enabled": False, "channel": "streamer"}}).json()
    assert again["twitch"]["has_token"] is True
    assert again["twitch"]["announce_every"] == 0  # поля, которых нет в запросе, — по умолчанию


def test_api_requires_secret_when_enabled(api_client, settings):
    response = api_client.post("/api/streaming", json={"youtube": {"enabled": True, "video": "dQw4w9WgXcQ"}})
    assert response.status_code == 400
    assert settings.get(options.SETTING) is None


def test_api_validates_input(api_client):
    bad_channel = api_client.post("/api/streaming", json={"twitch": {"channel": "a b"}})
    assert bad_channel.status_code == 400
    bad_video = api_client.post("/api/streaming", json={"youtube": {"video": "https://example.com/x"}})
    assert bad_video.status_code == 400
    bad_number = api_client.post("/api/streaming", json={"twitch": {"announce_every": -1}})
    assert bad_number.status_code == 400


def test_api_twitch_test_requires_connection(api_client):
    assert api_client.post("/api/streaming/twitch/test").status_code == 400


def test_manager_module_has_no_unused_marker_interval_regression():
    assert manager_module.MARKER_INTERVAL >= 1
