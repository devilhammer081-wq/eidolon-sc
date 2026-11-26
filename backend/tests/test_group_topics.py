"""The topic scheduler of the 283 office's group chat (GLOSSARY.md「群聊」) — who opens a
topic, who carries it on, driven through the reading of the chat (`GET /api/group`), the
deployer's chat model playing from a script, the speakers fixed by the fake random source.

Reading the chat brings it up to now: with no topic underway, a new one is opened where
the Beijing day still has its quota (`topics_per_day`) and the last opening has had its
gap; with one underway, it is carried on by as many turns as the spacing says should have
come, to its `max_turns` at the most, whereupon it is closed by a quiet line. Whoever
spoke last does not speak again right after herself; a speaker not close to the producer
is told she may be short; a model that fails ends the catch-up quietly, keeping what was
kept. The two configured characters take turns by the one-rule exclusion: with just the
two of them, whoever did not speak last is the only one eligible."""

from dataclasses import replace

import httpx
import pytest
from tests.conftest import ClientFactory, FakeIdentityProvider

from eidolon.config import Settings
from eidolon.llm import LLMError
from tests.conftest import KOGANE_SHEET, MANO_SHEET  # noqa: F401 -- the sheets the characters fixture writes
from tests.fakes import FAKE_JUDGE, FakeClock, FakeLLM, FakeRandom
from tests.test_affinity import keep
from tests.test_admin_users import ADMIN, admin_beside
from tests.test_group_chat import backend_of, seed, the_producer
from tests.test_solo_outings import records

GROUP = "/api/admin/config/group_chat"

MANO_OPENS = ["新歌的编舞好难，谁来陪我加练！"]
THEIR_LINES = ["我来陪你练咯。", "带我一个。", "练完请吃冰淇淋。"]
"""The opening and the carry-on lines, as the model is scripted to write them."""


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With the judge model, as the weighted draw reads affinities."""
    return replace(settings, judge=FAKE_JUDGE)


async def read(client: httpx.AsyncClient) -> dict:
    """Read the producer's chat: what the timeline page takes, topics caught up first."""
    res = await client.get("/api/group")
    assert res.status_code == 200
    return res.json()


async def test_reading_opens_a_topic_when_the_day_has_room(
    make_client: ClientFactory, settings: Settings
):
    llm = FakeLLM(*MANO_OPENS)
    client = make_client(llm, settings=settings, clock=FakeClock(), random=FakeRandom(0))

    shown = await read(client)

    assert shown["topic"] == {
        "opener": "mano", "opener_name": "櫻木真乃", "spoken": ["mano"], "turns": 1,
    }
    # 开话题的话也按回复格式要：日语原文加中文字幕（防回归——少了它新话就是纯中文）。
    [prompt] = llm.prompts
    assert "<ja>日语原文</ja><zh>中文字幕</zh>" in prompt[2].content
    [(kind, speaker, text)] = [
        (line["kind"], line["speaker"], line["text"]) for line in shown["messages"]
    ]
    assert (kind, speaker, text) == ("topic_open", "mano", MANO_OPENS[0])
    assert shown["unseen"] is True  # the topic that came in this reading is news


async def test_no_new_topic_until_the_gap_has_passed(
    make_client: ClientFactory, settings: Settings
):
    llm = FakeLLM(MANO_OPENS)
    clock = FakeClock()
    client = make_client(llm, settings=settings, clock=clock, random=FakeRandom(0))
    await read(client)  # a topic opened

    # The topic over — the last opening was just now, so the gap has not passed.
    producer = await the_producer(client)
    await backend_of(client).group_chat.chats.end_topic(
        producer, "聊完了。", backend_of(client).clock()
    )
    llm.prompts.clear()

    shown = await read(client)

    assert shown["topic"] is None
    assert llm.prompts == []


async def test_a_new_topic_after_the_gap_still_uses_the_day(
    make_client: ClientFactory, settings: Settings
):
    from eidolon.group_topics import TOPIC_GAP

    llm = FakeLLM(*MANO_OPENS, THEIR_LINES[0])
    clock = FakeClock()
    client = make_client(llm, settings=settings, clock=clock, random=FakeRandom(0, 0))
    await read(client)  # a topic opened
    producer = await the_producer(client)
    await backend_of(client).group_chat.chats.end_topic(
        producer, "聊完了。", backend_of(client).clock()
    )

    clock.advance(seconds=TOPIC_GAP.total_seconds() + 60)
    shown = await read(client)

    assert shown["topic"] is not None  # the day had room, the gap had passed


async def test_the_topic_is_carried_on_by_the_spacing(
    make_client: ClientFactory, settings: Settings
):
    llm = FakeLLM(*THEIR_LINES[:2])
    clock = FakeClock()
    client = make_client(llm, settings=settings, clock=clock, random=FakeRandom())
    await seed(client)  # Mano opened, Kogane spoke: 2 turns, Kogane spoke last

    clock.advance(minutes=16)  # two turns due
    shown = await read(client)

    # With the two of them, whoever did not speak last is the only one eligible: Mano,
    # then Kogane.
    assert shown["topic"]["turns"] == 4
    assert shown["topic"]["spoken"] == ["mano", "kogane", "mano", "kogane"]
    said = [line["speaker"] for line in shown["messages"] if line["kind"] == "say"]
    assert said[-2:] == ["mano", "kogane"]
    assert shown["messages"][-2]["text"] == THEIR_LINES[0]
    assert shown["messages"][-1]["text"] == THEIR_LINES[1]


async def test_one_reading_catches_up_at_most_a_few_turns(
    make_client: ClientFactory, settings: Settings
):
    from eidolon.group_topics import CATCH_UP_AT_MOST

    llm = FakeLLM(*THEIR_LINES, *THEIR_LINES)
    clock = FakeClock()
    client = make_client(llm, settings=settings, clock=clock, random=FakeRandom())
    await seed(client)

    clock.advance(hours=6)  # far more turns due than one reading brings on
    shown = await read(client)

    assert shown["topic"]["turns"] == 2 + CATCH_UP_AT_MOST


async def test_the_topic_ends_at_its_max_turns(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    llm = FakeLLM(THEIR_LINES[0])
    clock = FakeClock()
    client = make_client(
        llm, settings=replace(settings, admins=frozenset({ADMIN})), clock=clock,
        random=FakeRandom(),
    )
    await seed(client)  # 2 turns already
    async with admin_beside(client, github) as admin:
        res = await admin.put(GROUP, json={"max_turns": 3})
        assert res.status_code == 200

    clock.advance(minutes=8)  # one turn due: the third, the last
    shown = await read(client)

    assert shown["topic"] is None
    assert shown["messages"][-1]["kind"] == "topic_end"


async def test_a_speaker_not_close_may_be_short(
    make_client: ClientFactory, settings: Settings
):
    llm = FakeLLM(*MANO_OPENS)
    clock = FakeClock()
    client = make_client(llm, settings=settings, clock=clock, random=FakeRandom(0))
    keep(settings.database_path, "producer", 0, clock(), character="mano")

    await read(client)

    [prompt] = llm.prompts
    assert any("敷衍" in message.content for message in prompt)


async def test_a_model_that_fails_ends_the_catch_up_quietly(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(FakeLLM(LLMError("down")), settings=settings, clock=FakeClock(),
                         random=FakeRandom(0))
    producer = await the_producer(client)
    before = await backend_of(client).group_chat.chats.timeline(producer)

    shown = await read(client)

    assert shown["topic"] is None  # nothing opened, nothing kept
    assert await backend_of(client).group_chat.chats.timeline(producer) == before
    assert [r[2] for r in records(settings)] == ["failed"]


async def test_the_uniform_draw_reads_no_weights(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    llm = FakeLLM(THEIR_LINES[0])
    client = make_client(
        llm, settings=replace(settings, admins=frozenset({ADMIN})), clock=FakeClock(),
        random=FakeRandom(1),
    )
    async with admin_beside(client, github) as admin:
        res = await admin.put(GROUP, json={"speaker_mode": "random", "topics_per_day": 3})
        assert res.status_code == 200

    shown = await read(client)

    assert shown["topic"]["opener"] == "kogane"  # index 1 of the two, no weights read
