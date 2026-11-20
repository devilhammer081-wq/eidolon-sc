"""The 283 office's group chat (GLOSSARY.md「群聊」) — its lines and the state of its topic in
the store, and the producer's turns in it driven through the backend's external API, the
deployer's chat model playing from a script, who replies fixed by the fake random source or
by @-mentions.

A turn is the producer's words kept with the replies of whoever he @-names alone, or one or
two drawn — weighted (`group_turns.pick_speakers`) or uniformly, as the admin console has
the chat draw — streamed to the browser as they are written; one that fails keeps nothing of
itself. Reading the chat (`GET /api/group`) is what marks it read, a turn does too, and
`GET /api/group/unseen` says the unread part alone. While the deployer has the chat closed,
each of it is refused with 409."""

import json
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from eidolon.config import Settings
from eidolon.data_access import Database
from eidolon.group_chat import GroupChats, GroupState, Message, Topic
from eidolon.llm import LLMError
from eidolon.store import Store
from tests.conftest import KOGANE_SHEET, MANO_SHEET, CharacterConfig, ClientFactory
from tests.fakes import FakeClock, FakeIdentityProvider, FakeLLM, FakeRandom, START
from tests.test_admin_users import ADMIN, admin_beside
from tests.test_solo_outings import backend_of, records

A_WHILE_LATER = START + timedelta(hours=2)
A_LITTLE_LATER = A_WHILE_LATER + timedelta(minutes=1)
MANO_SAID = ["哇，是群聊！"]
KOGANE_SAID = ["有人冒泡咯。"]
"""Their replies, as the model is scripted to write them."""
GROUP = "/api/admin/config/group_chat"


@pytest.fixture
async def opened(tmp_path: Path) -> AsyncIterator[tuple[Store, GroupChats]]:
    """A store and the group chats of one database: the store for the users the chats are
    kept by."""
    db = Database(tmp_path / "eidolon.db")
    try:
        yield Store(db), GroupChats(db)
    finally:
        await db.close()


async def a_user(store: Store, name: str = "producer") -> str:
    return (await store.create_user(name)).id


async def test_lines_are_kept_in_the_order_said(
    opened: tuple[Store, GroupChats],
):
    store, chats = opened
    user = await a_user(store)

    producer = await chats.say(user, "大家晚上好", START)
    mano = await chats.say(user, "晚上好！", START, speaker="mano")
    kogane = await chats.say(user, "晚上好咯。", START, speaker="kogane")
    producer_again = await chats.say(user, "都吃过饭了吗", A_WHILE_LATER)

    assert producer == Message(1, user, None, "say", "大家晚上好", START)
    assert mano.speaker == "mano"
    kept = await chats.timeline(user)
    assert kept == [producer, mano, kogane, producer_again]


async def test_the_timeline_carries_the_latest_lines_only(
    opened: tuple[Store, GroupChats],
):
    store, chats = opened
    user = await a_user(store)
    kept = [
        await chats.say(user, f"第{each}句", START, speaker="mano") for each in range(5)
    ]

    assert await chats.timeline(user, 3) == kept[-3:]


async def test_a_topic_is_opened_carried_on_and_ended(
    opened: tuple[Store, GroupChats],
):
    store, chats = opened
    user = await a_user(store)

    assert await chats.state(user) == GroupState(user, None, None)
    opening = await chats.open_topic(user, "mano", "今天聊聊新歌吧！", START)

    assert opening == Message(1, user, "mano", "topic_open", "今天聊聊新歌吧！", START)
    assert await chats.state(user) == GroupState(user, Topic("mano", ("mano",), 1), None)
    await chats.say(user, "新歌？我也想听", START)  # the producer's line takes no turn
    await chats.say(user, "我昨天一直在练咯。", START, speaker="kogane")
    await chats.say(user, "我也是，唱给你听！", START, speaker="mano")

    assert await chats.state(user) == GroupState(
        user, Topic("mano", ("mano", "kogane", "mano"), 3), None
    )
    with pytest.raises(ValueError, match="还没有收掉"):
        await chats.open_topic(user, "kogane", "换我开一个", A_WHILE_LATER)
    ending = await chats.end_topic(user, "这个话题就聊到这里。", A_WHILE_LATER)

    assert ending == Message(5, user, None, "topic_end", "这个话题就聊到这里。", A_WHILE_LATER)
    assert await chats.state(user) == GroupState(user, None, None)
    with pytest.raises(ValueError, match="没有进行中的话题"):
        await chats.end_topic(user, "再收一次", A_WHILE_LATER)
    # a topic may be opened again once the last one is closed
    assert (await chats.open_topic(user, "kogane", "那我开一个！", A_WHILE_LATER)).speaker == (
        "kogane"
    )


async def test_a_characters_line_without_a_topic_is_kept_all_the_same(
    opened: tuple[Store, GroupChats],
):
    """The producer may interject with no topic underway: whoever replies, her line is
    kept, the state stays as it was."""
    store, chats = opened
    user = await a_user(store)

    kept = await chats.say(user, "有人吗", START, speaker="mano")

    assert kept.speaker == "mano"
    assert await chats.state(user) == GroupState(user, None, None)


async def test_what_is_unread_goes_by_when_the_producer_last_read(
    opened: tuple[Store, GroupChats],
):
    store, chats = opened
    user = await a_user(store)

    assert not await chats.unread(user)  # nothing said yet
    await chats.say(user, "我说一句不算", START)  # his own line is never unread
    assert not await chats.unread(user)
    await chats.say(user, "大家晚上好", START, speaker="mano")
    assert await chats.unread(user)

    await chats.mark_read(user, A_WHILE_LATER)
    assert not await chats.unread(user)
    await chats.say(user, "又有新的了", A_LITTLE_LATER, speaker="kogane")
    assert await chats.unread(user)
    await chats.mark_read(user, A_LITTLE_LATER)
    await chats.say(user, "我自己再说的不算", A_LITTLE_LATER)
    assert not await chats.unread(user)


async def test_no_ones_chat_is_anothers(opened: tuple[Store, GroupChats]):
    store, chats = opened
    user = await a_user(store, "producer")
    other = await a_user(store, "other")
    await chats.say(user, "晚上好", START, speaker="mano")
    await chats.open_topic(user, "mano", "开个话题", START)

    assert await chats.timeline(other) == []
    assert await chats.state(other) == GroupState(other, None, None)
    assert not await chats.unread(other)
    assert (await chats.state(user)).topic is not None


async def test_deleting_the_user_deletes_their_chat(
    opened: tuple[Store, GroupChats], tmp_path: Path
):
    store, chats = opened
    user = await a_user(store)
    await chats.open_topic(user, "mano", "开个话题", START)
    await chats.say(user, "晚上好", START, speaker="kogane")
    await chats.mark_read(user, START)

    await store.delete_user(user)

    with sqlite3.connect(tmp_path / "eidolon.db") as db:  # and the rows with them
        assert db.execute("SELECT COUNT(*) FROM group_messages").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM group_state").fetchone() == (0,)


async def the_producer(client: httpx.AsyncClient) -> str:
    """The id of the signed-in producer, whose chat the API tests seed."""
    user = await backend_of(client).store.first_user_named("producer")
    assert user is not None
    return user.id


async def seed(client: httpx.AsyncClient) -> None:
    """A topic underway in the producer's chat, opened by Mano and carried on by Kogane."""
    chats = backend_of(client).group_chat.chats
    user = await the_producer(client)
    now = backend_of(client).clock()
    await chats.open_topic(user, "mano", "今天聊聊新歌吧！", now)
    await chats.say(user, "我昨天一直在练咯。", now, speaker="kogane")


async def turn(client: httpx.AsyncClient, text: str) -> list[dict]:
    """Say something as the producer, and collect the server-sent events it streams back."""
    events: list[dict] = []
    async with client.stream("POST", "/api/group/turns", json={"text": text}) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        async for line in res.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events


async def messages_of(client: httpx.AsyncClient) -> list[dict]:
    """The lines of the producer's chat, from the timeline."""
    return (await client.get("/api/group")).json()["messages"]


async def test_the_timeline_is_read_with_its_topic_and_what_was_unread(
    make_client: ClientFactory
):
    client = make_client(FakeLLM(), clock=FakeClock())
    await seed(client)

    first = await client.get("/api/group")

    assert first.status_code == 200
    shown = first.json()
    assert [(m["speaker"], m["kind"], m["text"]) for m in shown["messages"]] == [
        ("mano", "topic_open", "今天聊聊新歌吧！"),
        ("kogane", "say", "我昨天一直在练咯。"),
    ]
    assert shown["messages"][0]["speaker_name"] == "櫻木真乃"
    assert shown["messages"][0]["color"] == "#ffbad6"
    assert shown["messages"][1]["speaker_name"] == "月岡恋鐘"
    assert shown["messages"][1]["color"] == "#f84cad"
    assert shown["topic"] == {
        "opener": "mano", "opener_name": "櫻木真乃", "spoken": ["mano", "kogane"], "turns": 2,
    }
    assert shown["unseen"] is True  # Kogane had spoken since he last read


async def test_reading_the_timeline_is_what_marks_it_read(make_client: ClientFactory):
    client = make_client(FakeLLM(), clock=FakeClock())
    await seed(client)

    assert (await client.get("/api/group/unseen")).json() == {"unseen": True}
    assert (await client.get("/api/group")).json()["unseen"] is True
    assert (await client.get("/api/group/unseen")).json() == {"unseen": False}


async def test_a_turn_draws_one_or_two_responders(make_client: ClientFactory):
    """Two drawn: the count first, then each of them, the second against the first."""
    llm = FakeLLM(MANO_SAID, KOGANE_SAID)
    client = make_client(llm, clock=FakeClock(), random=FakeRandom(1, 49, 49))
    await seed(client)
    llm.prompts.clear()

    events = await turn(client, "新歌什么时候发？")

    assert [e["type"] for e in events] == [
        "user", "speaker", "delta", "speaker", "delta", "done",
    ]
    assert events[0] == {"type": "user", "text": "新歌什么时候发？"}
    assert events[1] == {
        "type": "speaker", "character_id": "mano", "name": "櫻木真乃", "color": "#ffbad6",
    }
    assert events[2] == {"type": "delta", "speaker": "mano", "text": "哇，是群聊！"}
    assert events[3]["character_id"] == "kogane"
    assert events[4] == {"type": "delta", "speaker": "kogane", "text": "有人冒泡咯。"}
    assert [
        (m["speaker"], m["speaker_name"], m["kind"], m["text"])
        for m in events[-1]["messages"]
    ] == [
        (None, None, "say", "新歌什么时候发？"),
        ("mano", "櫻木真乃", "say", "哇，是群聊！"),
        ("kogane", "月岡恋鐘", "say", "有人冒泡咯。"),
    ]
    assert await messages_of(client) == [
        *(await client.get("/api/group")).json()["messages"][:2],
        *events[-1]["messages"],
    ]
    [mano_prompt, kogane_prompt] = llm.prompts
    assert mano_prompt[0].content.startswith(MANO_SHEET)
    assert "283事务所的群聊" in mano_prompt[2].content
    assert "- 月岡恋鐘（L'Antica 的偶像）" in mano_prompt[2].content
    assert "# 到现在为止" in mano_prompt[2].content
    assert "今天聊聊新歌吧！" in mano_prompt[2].content  # the topic's opening among the lines
    assert "（Asia/Shanghai）" in mano_prompt[-1].content
    assert "制作人对大家说：「新歌什么时候发？」" in mano_prompt[-1].content
    # The second speaker sees the first's reply in the lines so far.
    assert "哇，是群聊！" in kogane_prompt[2].content
    assert kogane_prompt[0].content.startswith(KOGANE_SHEET)


async def test_a_turn_draws_one_when_the_draw_says_one(make_client: ClientFactory):
    llm = FakeLLM(MANO_SAID)
    client = make_client(llm, clock=FakeClock(), random=FakeRandom(0, 49))  # one; Mano
    await seed(client)
    llm.prompts.clear()

    events = await turn(client, "新歌什么时候发？")

    assert [e["type"] for e in events] == ["user", "speaker", "delta", "done"]
    assert events[1]["character_id"] == "mano"


async def test_a_mentioned_character_replies_alone(make_client: ClientFactory):
    """No draw at all: whoever the @ names, alone."""
    llm = FakeLLM(KOGANE_SAID)
    client = make_client(llm, clock=FakeClock(), random=FakeRandom())  # nothing drawn
    await seed(client)
    llm.prompts.clear()

    events = await turn(client, "@月岡恋鐘，练得怎么样了？")

    assert [e["type"] for e in events] == ["user", "speaker", "delta", "done"]
    assert events[1]["character_id"] == "kogane"
    [prompt] = llm.prompts
    assert "制作人对月岡恋鐘说：「@月岡恋鐘，练得怎么样了？」" in prompt[-1].content


async def test_a_mention_by_short_name_names_her_too(
    make_client: ClientFactory, settings: Settings, tmp_path: Path
):
    named = (
        CharacterConfig(tmp_path / "named")
        .add("mano", "櫻木真乃", MANO_SHEET, short_name="真乃")
        .add("kogane", "月岡恋鐘", KOGANE_SHEET, short_name="恋鐘")
    )
    llm = FakeLLM(KOGANE_SAID)
    client = make_client(
        llm, settings=replace(settings, characters_path=named.path), clock=FakeClock(),
        random=FakeRandom(),
    )
    await seed(client)
    llm.prompts.clear()

    events = await turn(client, "@恋鐘，走这边")

    assert [e["type"] for e in events] == ["user", "speaker", "delta", "done"]
    assert events[1]["character_id"] == "kogane"


async def test_a_turn_takes_turns_of_the_topic_underway(make_client: ClientFactory):
    """Whoever replies, her line is a turn of the topic underway; his own is not."""
    llm = FakeLLM(MANO_SAID)
    client = make_client(llm, clock=FakeClock(), random=FakeRandom(0, 49))  # one; Mano
    await seed(client)  # already Mano's opening and Kogane's line: 2 turns

    await turn(client, "新歌什么时候发？")

    chats = backend_of(client).group_chat.chats
    producer = await the_producer(client)
    assert (await chats.state(producer)).topic == Topic(
        "mano", ("mano", "kogane", "mano"), 3
    )
    # a turn the producer watched counts as read
    assert not await chats.unread(producer)


async def test_a_turn_that_fails_or_is_rejected_keeps_nothing(
    make_client: ClientFactory, settings: Settings
):
    llm = FakeLLM(LLMError("the model is down"))
    client = make_client(llm, clock=FakeClock(), random=FakeRandom(0, 49))
    await seed(client)
    before = (await client.get("/api/group")).json()["messages"]

    blank = await turn(client, "  ")
    assert blank[-1] == {"type": "error", "message": "没有收到要说的话。"}
    too_long = await turn(client, "长" * 2001)
    assert too_long[-1]["type"] == "error"

    failed = await turn(client, "还在吗？")
    assert failed[-1] == {"type": "error", "message": "角色暂时无法回复，请稍后再试。"}

    assert await messages_of(client) == before
    assert [r[2] for r in records(settings)] == ["failed"]  # the model's failure alone


async def test_the_admin_console_sets_how_the_chat_draws(
    make_client: ClientFactory, github: FakeIdentityProvider, settings: Settings
):
    """The draw uniform instead of weighted: everyone as likely as everyone else, no
    weights read at all."""
    llm = FakeLLM(KOGANE_SAID, MANO_SAID)
    client = make_client(
        llm,
        settings=replace(settings, admins=frozenset({ADMIN})),
        clock=FakeClock(),
        random=FakeRandom(1, 1, 0),  # two; index 1 of 2; index 0 of the one left
    )
    async with admin_beside(client, github) as admin:
        await admin.put(GROUP, json={"speaker_mode": "random"})
    await seed(client)
    llm.prompts.clear()

    events = await turn(client, "新歌什么时候发？")

    assert [e["character_id"] for e in events if e["type"] == "speaker"] == [
        "kogane", "mano",
    ]


async def test_the_admin_console_sets_the_chat(
    make_client: ClientFactory, github: FakeIdentityProvider, settings: Settings
):
    client = make_client(
        FakeLLM(), settings=replace(settings, admins=frozenset({ADMIN})), clock=FakeClock(),
    )
    async with admin_beside(client, github) as admin:
        refused = [
            (
                await admin.put(
                    GROUP,
                    json={"enabled": True, "topics_per_day": topics, "max_turns": 8,
                          "speaker_mode": "relation_weighted"},
                )
            ).status_code
            for topics in (0, True, "3")
        ] + [
            (await admin.put(GROUP, json={"speaker_mode": "closest"})).status_code,
            (await admin.put(GROUP, json={"enabled": "yes"})).status_code,
        ]
        accepted = await admin.put(
            GROUP,
            json={"enabled": True, "topics_per_day": 2, "max_turns": 5,
                  "speaker_mode": "random"},
        )
        alone = await admin.put(GROUP, json={"max_turns": 4})

    assert refused == [422, 422, 422, 422, 422]
    assert accepted.status_code == 200
    assert accepted.json()["group_chat"]["effective"] == {
        "enabled": True, "topics_per_day": 2, "max_turns": 5, "speaker_mode": "random",
    }
    assert alone.json()["group_chat"]["effective"]["max_turns"] == 4  # the rest untouched
    assert alone.json()["group_chat"]["effective"]["topics_per_day"] == 2


async def test_a_closed_chat_refuses_to_be_read_or_spoken_in(
    make_client: ClientFactory, github: FakeIdentityProvider, settings: Settings
):
    client = make_client(
        FakeLLM(),
        settings=replace(settings, admins=frozenset({ADMIN})),
        clock=FakeClock(),
        random=FakeRandom(),
    )
    await seed(client)
    async with admin_beside(client, github) as admin:
        await admin.put(GROUP, json={"enabled": False})

    read = await client.get("/api/group")
    unseen = await client.get("/api/group/unseen")
    spoken = await client.post("/api/group/turns", json={"text": "还在吗？"})

    assert read.status_code == 409
    assert read.json()["detail"] == "群聊没有开放"
    assert unseen.status_code == 409
    assert spoken.status_code == 409
    assert spoken.json()["detail"] == "群聊没有开放"
    chats = backend_of(client).group_chat.chats
    producer = await the_producer(client)
    assert len(await chats.timeline(producer)) == 2  # and nothing new was kept


async def test_her_line_keeps_its_original_beside_its_subtitle(make_client: ClientFactory):
    """按回复格式说的话：中文做正文，日语原文带字幕留在这行的 segments 里。"""
    llm = FakeLLM(["<ja>こんにちは！</ja><zh>大家好！</zh>"])
    client = make_client(llm, clock=FakeClock(), random=FakeRandom(0, 49))
    await seed(client)

    events = await turn(client, "大家晚上好")

    kept = next(e for e in events if e["type"] == "done")["messages"]
    [hers] = [line for line in kept if line["speaker"] is not None]
    assert hers["text"] == "大家好！"
    assert hers["segments"] == [{"ja": "こんにちは！", "zh": "大家好！"}]
    read_back = (await client.get("/api/group")).json()["messages"]
    [again] = [
        line for line in read_back
        if line["kind"] == "say" and line["speaker"] == hers["speaker"]
    ]
    assert again["segments"] == hers["segments"]
