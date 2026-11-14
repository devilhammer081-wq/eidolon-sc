"""Outings with company (GLOSSARY.md「外出」) — driven through the backend's external API,
the deployer's chat model playing from a script, who replies fixed by the fake random
source, by @-mentions, or by the affinities and relations kept in the database directly.

The opening is one ask of the model — a scene, then each of their first lines labelled
with her name — kept as the outing's opening lines, the outing under way from then on. A
turn is the producer's words kept with the replies of whoever he @-names alone, or one or
two drawn weighted (`group_turns.pick_speakers`), streamed to the browser as they are
written; one that fails keeps nothing of itself. A location event is one ask again, its
scene an event line carrying the event's identifier, the reactions drawn likewise. Ending
settles with each of them — her affinity changed as the model judged the outing, through
the affinity interface as it stands — and the outing remembered by each who came along.
Nothing is kept of an ask that fails."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from eidolon.characters import Character
from eidolon.config import Settings
from eidolon.group_turns import (
    AFFINITY_BASE,
    RELATION_STEP,
    Candidate,
    mentioned_in,
    parse_labelled,
    pick_speakers,
    speaker_weight,
)
from eidolon.llm import LLMError, Streamed
from eidolon.producer import Birthday
from tests.conftest import KOGANE_SHEET, MANO_SHEET, CharacterConfig, ClientFactory
from tests.fakes import FAKE_JUDGE, FakeClock, FakeIdentityProvider, FakeLLM, FakeRandom
from tests.test_affinity import keep
from tests.test_admin_users import ADMIN, admin_beside
from tests.test_solo_outings import backend_of, records

OPENING = (
    "傍晚的影院大堂，灯刚暗下来，爆米花的甜味飘在走廊里。\n"
    "櫻木真乃：哇，好暗……差点踩空台阶。\n"
    "月岡恋鐘：真乃，你走慢一点咯。"
)
"""The opening as the model is scripted to write it: a scene, then each of their first
lines, labelled."""
MANO_SAID = ["哇，是电影！"]
KOGANE_SAID = ["要坐哪一边？"]
"""Their replies, as the model is scripted to write them."""
EVENT_SCENE = (
    "海报墙前大家停下了脚步，谁也不让谁。\n"
    "櫻木真乃：我想看那部治愈系的……\n"
    "月岡恋鐘：我要看动作片，就它咯！"
)
"""The event's scene and reactions, as the model is scripted to write them."""
SETTLED = json.dumps({
    "characters": [{"id": "mano", "level": 4}, {"id": "kogane", "level": 3}],
    "ending": "散场了，大家边说边走出去。",
}, ensure_ascii=False)
"""The settlement as the model is scripted to write it."""
OUTINGS = "/api/admin/config/outings"


def a_character(id: str, name: str, sheet: str, color: str) -> Character:
    """One as simple as the engine's weights and mentions read her."""
    return Character(id, name, "", "voice", sheet, None, color, Birthday(4, 25), 16)


MANO = a_character("mano", "櫻木真乃", MANO_SHEET, "#ffbad6")
KOGANE = a_character("kogane", "月岡恋鐘", KOGANE_SHEET, "#f84cad")


async def start(
    client: httpx.AsyncClient, character_ids: list[str] | None = None, location: str = "cinema"
) -> httpx.Response:
    """Set the producer out with company, Mano and Kogane by default."""
    return await client.post("/api/outings", json={
        "character_ids": character_ids or ["mano", "kogane"], "location_id": location,
    })


async def turn(client: httpx.AsyncClient, outing_id: int, text: str) -> list[dict]:
    """Send a turn of the outing, and collect the server-sent events it streams back."""
    events: list[dict] = []
    async with client.stream(
        "POST", f"/api/outings/{outing_id}/turns", json={"text": text}
    ) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        async for line in res.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events


async def messages_of(client: httpx.AsyncClient, outing_id: int) -> list[dict]:
    """The lines of the outing, from the history."""
    listed = (await client.get("/api/outings")).json()["outings"]
    return next(o["messages"] for o in listed if o["id"] == outing_id)


def affinity_of(settings: Settings, character: str) -> float | None:
    """The producer's affinity with the character, as it is kept."""
    with sqlite3.connect(settings.database_path) as db:
        [(producer,)] = db.execute(
            "SELECT id FROM users WHERE name = 'producer'"
        ).fetchall()
        row = db.execute(
            "SELECT value FROM affinities WHERE user_id = ? AND character_id = ?",
            (producer, character),
        ).fetchone()
        return None if row is None else row[0]


def memories_of(settings: Settings) -> list[tuple[str, str]]:
    """The producer's memories, as they are kept: who each was told to, and what it
    says."""
    with sqlite3.connect(settings.database_path) as db:
        return db.execute(
            "SELECT source_character_id, text FROM memories ORDER BY id"
        ).fetchall()


async def test_the_opening_writes_the_scene_and_their_first_lines(make_client: ClientFactory):
    llm = FakeLLM([OPENING])
    client = make_client(llm, random=FakeRandom())

    begun = await start(client)

    assert begun.status_code == 201
    shown = begun.json()["outing"]
    assert shown["status"] == "ongoing"
    assert shown["kind"] == "outing"
    assert shown["location_name"] == "电影院"
    assert shown["participants"] == [
        {"character_id": "mano", "character_name": "櫻木真乃", "color": "#ffbad6"},
        {"character_id": "kogane", "character_name": "月岡恋鐘", "color": "#f84cad"},
    ]
    assert [(m["speaker"], m["kind"], m["text"]) for m in shown["messages"]] == [
        (None, "opening", "傍晚的影院大堂，灯刚暗下来，爆米花的甜味飘在走廊里。"),
        ("mano", "opening", "哇，好暗……差点踩空台阶。"),
        ("kogane", "opening", "真乃，你走慢一点咯。"),
    ]
    [prompt] = llm.prompts
    assert backend_of(client).outing_catalog["cinema"].scene in prompt[2].content
    assert MANO_SHEET in prompt[1].content and KOGANE_SHEET in prompt[1].content
    assert prompt[-1].content == "（制作人和櫻木真乃、月岡恋鐘一起来到电影院，大家都到了。）"


@pytest.mark.parametrize(
    "body, code, detail",
    [
        ({"character_ids": [], "location_id": "cinema"}, 422, None),
        ({"character_ids": ["mano"] * 4, "location_id": "cinema"}, 422, None),
        (
            {"character_ids": ["mano", "mano"], "location_id": "cinema"}, 422,
            "同行的角色里有重复",
        ),
        (
            {"character_ids": ["mano", "megumi"], "location_id": "cinema"}, 404,
            "没有这个角色：megumi",
        ),
        (
            {"character_ids": ["mano"], "location_id": "the-moon"}, 404,
            "没有这个外出地点：the-moon",
        ),
    ],
)
async def test_starting_refuses_what_cannot_be(
    make_client: ClientFactory, body: dict, code: int, detail: str | None
):
    client = make_client(FakeLLM(), random=FakeRandom())

    res = await client.post("/api/outings", json=body)

    assert res.status_code == code
    if detail is not None:
        assert res.json()["detail"] == detail
    assert (await client.get("/api/outings")).json()["outings"] == []


@pytest.mark.parametrize("reply", [LLMError("the model is down"), [""]])
async def test_an_opening_the_model_fails_or_leaves_empty_keeps_nothing(
    make_client: ClientFactory, settings: Settings, reply: Sequence[Streamed | object]
):
    client = make_client(FakeLLM(reply), random=FakeRandom())

    res = await start(client)

    assert res.status_code == 502
    assert res.json()["detail"] == "这次外出没有成行，请稍后再试"
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM outings").fetchone() == (0,)
    assert records(settings) == [("outing", "", "failed")]


async def test_a_turn_draws_one_or_two_responders(make_client: ClientFactory):
    """Two drawn: the count first, then each of them, the second against the first."""
    llm = FakeLLM([OPENING], MANO_SAID, KOGANE_SAID)
    client = make_client(llm, random=FakeRandom(1, 49, 0))  # two; Mano at 49 of 100; Kogane
    begun = (await start(client)).json()["outing"]
    llm.prompts.clear()

    events = await turn(client, begun["id"], "想看哪部？")

    assert [e["type"] for e in events] == [
        "user", "speaker", "delta", "speaker", "delta", "done",
    ]
    assert events[0] == {"type": "user", "text": "想看哪部？"}
    assert events[1] == {
        "type": "speaker", "character_id": "mano", "name": "櫻木真乃", "color": "#ffbad6",
    }
    assert events[2] == {"type": "delta", "speaker": "mano", "text": "哇，是电影！"}
    assert events[3]["character_id"] == "kogane"
    assert events[4] == {"type": "delta", "speaker": "kogane", "text": "要坐哪一边？"}
    assert [(m["speaker"], m["kind"], m["text"]) for m in events[-1]["messages"]] == [
        (None, "say", "想看哪部？"),
        ("mano", "say", "哇，是电影！"),
        ("kogane", "say", "要坐哪一边？"),
    ]
    assert await messages_of(client, begun["id"]) == [
        *begun["messages"], *events[-1]["messages"],
    ]
    [mano_prompt, kogane_prompt] = llm.prompts
    assert mano_prompt[0].content.startswith(MANO_SHEET)
    scene = backend_of(client).outing_catalog["cinema"].scene
    assert scene in mano_prompt[2].content
    assert "- 月岡恋鐘（L'Antica 的偶像）" in mano_prompt[2].content
    assert "# 到现在为止" in mano_prompt[2].content
    assert "（Asia/Shanghai）" in mano_prompt[-1].content
    assert "「想看哪部？」" in mano_prompt[-1].content
    # The second speaker sees the first's reply in the lines so far.
    assert "哇，是电影！" in kogane_prompt[2].content
    assert kogane_prompt[0].content.startswith(KOGANE_SHEET)


async def test_a_turn_draws_one_when_the_draw_says_one(make_client: ClientFactory):
    llm = FakeLLM([OPENING], MANO_SAID)
    client = make_client(llm, random=FakeRandom(0, 49))  # one; Mano
    begun = (await start(client)).json()["outing"]
    llm.prompts.clear()

    events = await turn(client, begun["id"], "想看哪部？")

    assert [e["type"] for e in events] == ["user", "speaker", "delta", "done"]
    assert len(llm.prompts) == 1


async def test_a_mentioned_character_replies_alone(make_client: ClientFactory):
    """No draw at all: whoever the @ names, alone, in the order of the mentions."""
    llm = FakeLLM([OPENING], KOGANE_SAID)
    client = make_client(llm, random=FakeRandom())  # nothing drawn
    begun = (await start(client)).json()["outing"]
    llm.prompts.clear()

    events = await turn(client, begun["id"], "@月岡恋鐘，你想看哪部？")

    assert [e["type"] for e in events] == ["user", "speaker", "delta", "done"]
    assert events[1]["character_id"] == "kogane"
    [prompt] = llm.prompts
    assert "制作人对月岡恋鐘说：「@月岡恋鐘，你想看哪部？」" in prompt[-1].content


async def test_a_mention_by_short_name_names_her_too(
    make_client: ClientFactory, settings: Settings, tmp_path: Path
):
    """配置里带了短名：@短名 也只点她一个。"""
    named = (
        CharacterConfig(tmp_path / "named")
        .add("mano", "櫻木真乃", MANO_SHEET, short_name="真乃")
        .add("kogane", "月岡恋鐘", KOGANE_SHEET, short_name="恋鐘")
    )
    llm = FakeLLM([OPENING], KOGANE_SAID)
    client = make_client(
        llm, settings=replace(settings, characters_path=named.path), random=FakeRandom()
    )
    begun = (await start(client)).json()["outing"]
    llm.prompts.clear()

    events = await turn(client, begun["id"], "@恋鐘，走这边")

    assert [e["type"] for e in events] == ["user", "speaker", "delta", "done"]
    assert events[1]["character_id"] == "kogane"


async def test_a_turn_that_fails_or_is_rejected_keeps_nothing(
    make_client: ClientFactory, settings: Settings
):
    llm = FakeLLM([OPENING], LLMError("the model is down"))
    client = make_client(llm, random=FakeRandom(0, 49))
    begun = (await start(client)).json()["outing"]
    before = begun["messages"]

    blank = await turn(client, begun["id"], "  ")
    assert blank[-1] == {"type": "error", "message": "没有收到要说的话。"}
    too_long = await turn(client, begun["id"], "长" * 2001)
    assert too_long[-1]["type"] == "error"

    failed = await turn(client, begun["id"], "爆米花要分吗？")
    assert failed[-1] == {"type": "error", "message": "角色暂时无法回复，请稍后再试。"}

    assert await messages_of(client, begun["id"]) == before
    assert [r[2] for r in records(settings)] == ["success", "failed"]


async def test_an_event_writes_its_scene_and_the_reactions(make_client: ClientFactory):
    llm = FakeLLM([OPENING], [EVENT_SCENE])
    client = make_client(llm, random=FakeRandom(1, 49, 0))  # two react: Mano, then Kogane
    begun = (await start(client)).json()["outing"]
    llm.prompts.clear()

    happened = await client.post(
        f"/api/outings/{begun['id']}/events", json={"event_id": "pick-a-film"}
    )

    assert happened.status_code == 200
    assert happened.json()["event"] == {"id": "pick-a-film", "trigger": "选片争执"}
    assert [
        (m["speaker"], m["kind"], m["text"], m["event"])
        for m in happened.json()["messages"]
    ] == [
        (None, "event", "海报墙前大家停下了脚步，谁也不让谁。", "pick-a-film"),
        ("mano", "say", "我想看那部治愈系的……", None),
        ("kogane", "say", "我要看动作片，就它咯！", None),
    ]
    assert (await messages_of(client, begun["id"]))[-3:] == happened.json()["messages"]
    [prompt] = llm.prompts
    assert "海报墙前大家想看的片子不一样" in prompt[2].content  # the event's own prompt
    assert prompt[-1].content == "（「选片争执」发生了。）"


async def test_an_event_the_location_has_not_is_not_set_off(make_client: ClientFactory):
    client = make_client(FakeLLM([OPENING]), random=FakeRandom())
    begun = (await start(client)).json()["outing"]

    res = await client.post(
        f"/api/outings/{begun['id']}/events", json={"event_id": "high-tide"}
    )

    assert res.status_code == 404
    assert res.json()["detail"] == "这个地点没有这个事件：high-tide"


async def test_ending_settles_with_each_and_keeps_their_memories(
    make_client: ClientFactory, settings: Settings
):
    """Affinity on: the model judges the outing once, each of them settled through the
    affinity interface, the ending line kept, and each who came along remembering it as a
    memory of hers."""
    settings = replace(settings, judge=FAKE_JUDGE)
    clock = FakeClock()
    llm = FakeLLM([OPENING], [SETTLED])
    client = make_client(llm, settings=settings, clock=clock, random=FakeRandom())
    keep(settings.database_path, "producer", 50, clock(), character="mano")
    keep(settings.database_path, "producer", 50, clock(), character="kogane")
    begun = (await start(client)).json()["outing"]

    ended = await client.post(f"/api/outings/{begun['id']}/end")

    assert ended.status_code == 200
    shown = ended.json()["outing"]
    assert shown["status"] == "ended"
    assert shown["ended_at"] is not None
    assert shown["messages"][-1]["kind"] == "ending"
    assert shown["messages"][-1]["text"] == "散场了，大家边说边走出去。"
    settlement = ended.json()["settlement"]
    assert [(s["character_id"], s["change"]) for s in settlement] == [
        ("mano", {"up": True, "tier": "trust", "tier_changed": False, "cooldown": False}),
        ("kogane", {"up": True, "tier": "trust", "tier_changed": False, "cooldown": False}),
    ]
    assert [s["affinity"] for s in settlement] == [
        {"tier": "trust", "cooldown_until": None},
    ] * 2
    assert affinity_of(settings, "mano") == 50.2
    assert affinity_of(settings, "kogane") == 50.1
    assert memories_of(settings) == [
        ("mano", "制作人和櫻木真乃、月岡恋鐘一起去了电影院。"),
        ("kogane", "制作人和月岡恋鐘、櫻木真乃一起去了电影院。"),
    ]
    settling = llm.prompts[-1]
    told = settling[-1].content
    assert "黑暗里并肩坐着" in told  # the location's affinity hint
    assert "（没有触发过地点事件）" in told
    assert "- mano（櫻木真乃）：不是她特别喜欢的那类地方" in told


async def test_ending_counts_the_events_that_happened(
    make_client: ClientFactory, settings: Settings
):
    settings = replace(settings, judge=FAKE_JUDGE)
    clock = FakeClock()
    llm = FakeLLM([OPENING], [EVENT_SCENE], [SETTLED])
    client = make_client(llm, settings=settings, clock=clock, random=FakeRandom(1, 49, 0))
    begun = (await start(client)).json()["outing"]
    assert (
        await client.post(
            f"/api/outings/{begun['id']}/events", json={"event_id": "pick-a-film"}
        )
    ).status_code == 200

    ended = await client.post(f"/api/outings/{begun['id']}/end")

    assert ended.status_code == 200
    told = llm.prompts[-1][-1].content
    assert "选片争执：争归争，肯陪对方看自己不想看的片子，好感反而更往上走。" in told
    assert memories_of(settings) == [
        ("mano", "制作人和櫻木真乃、月岡恋鐘一起去了电影院，碰上了选片争执。"),
        ("kogane", "制作人和月岡恋鐘、櫻木真乃一起去了电影院，碰上了选片争执。"),
    ]


async def test_ending_with_affinity_off_settles_nothing_and_remembers_all_the_same(
    make_client: ClientFactory, settings: Settings
):
    """No judge model: nothing asked, nothing changed, one plain ending line; the memory
    is kept all the same."""
    llm = FakeLLM([OPENING])  # nothing more to say: any ask would fail the test
    client = make_client(llm, random=FakeRandom())
    begun = (await start(client)).json()["outing"]

    ended = await client.post(f"/api/outings/{begun['id']}/end")

    assert ended.status_code == 200
    assert ended.json()["settlement"] == []
    assert ended.json()["outing"]["messages"][-1]["text"] == "大家一起回去了。"
    assert affinity_of(settings, "mano") is None
    assert memories_of(settings) == [
        ("mano", "制作人和櫻木真乃、月岡恋鐘一起去了电影院。"),
        ("kogane", "制作人和月岡恋鐘、櫻木真乃一起去了电影院。"),
    ]


async def test_a_settlement_the_model_gets_wrong_leaves_the_outing_as_it_was(
    make_client: ClientFactory, settings: Settings
):
    settings = replace(settings, judge=FAKE_JUDGE)
    llm = FakeLLM([OPENING], ["结算不了"])
    client = make_client(llm, settings=settings, clock=FakeClock(), random=FakeRandom())
    begun = (await start(client)).json()["outing"]

    res = await client.post(f"/api/outings/{begun['id']}/end")

    assert res.status_code == 502
    assert res.json()["detail"] == "这次外出没能结算，请稍后再试"
    listed = (await client.get("/api/outings")).json()["outings"]
    assert listed[0]["status"] == "ongoing"
    assert affinity_of(settings, "mano") is None
    assert memories_of(settings) == []


async def test_another_users_outing_is_not_written_to(make_client: ClientFactory):
    client = make_client(FakeLLM([OPENING]), random=FakeRandom())
    begun = (await start(client)).json()["outing"]
    other = make_client(FakeLLM(), user="another producer")

    turned = await other.post(f"/api/outings/{begun['id']}/turns", json={"text": "我也要去"})
    happened = await other.post(
        f"/api/outings/{begun['id']}/events", json={"event_id": "pick-a-film"}
    )
    ended = await other.post(f"/api/outings/{begun['id']}/end")

    assert turned.status_code == 404
    assert happened.status_code == 404
    assert ended.status_code == 404
    assert ((await client.get("/api/outings")).json()["outings"][0]["status"]) == "ongoing"


async def test_an_ended_outing_refuses_its_turns_and_a_second_ending(
    make_client: ClientFactory
):
    client = make_client(FakeLLM([OPENING]), clock=FakeClock(), random=FakeRandom())
    begun = (await start(client)).json()["outing"]
    assert (await client.post(f"/api/outings/{begun['id']}/end")).status_code == 200

    refused = await client.post(f"/api/outings/{begun['id']}/turns", json={"text": "还在吗"})
    assert refused.status_code == 409
    assert refused.json()["detail"] == "这次外出已经结束了"
    assert (
        await client.post(
            f"/api/outings/{begun['id']}/events", json={"event_id": "spilled-popcorn"}
        )
    ).status_code == 409
    assert (await client.post(f"/api/outings/{begun['id']}/end")).status_code == 409


async def test_the_admin_console_sets_how_many_reply(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    client = make_client(
        FakeLLM([OPENING], MANO_SAID),
        settings=replace(settings, admins=frozenset({ADMIN}), judge=FAKE_JUDGE),
        clock=FakeClock(),
        random=FakeRandom(49),  # no count drawn at the cap of one; Mano at 49 of 100
    )
    async with admin_beside(client, github) as admin:
        refused = [
            (
                await admin.put(
                    OUTINGS, json={"encounter_chance": 0.3, "responders_max": most}
                )
            ).status_code
            for most in (0, 4, True, "2")
        ]
        accepted = await admin.put(OUTINGS, json={"responders_max": 1})

    assert refused == [422, 422, 422, 422]
    assert accepted.status_code == 200
    assert accepted.json()["outings"]["effective"] == {
        "encounter_chance": 0.3, "responders_max": 1,
    }
    begun = (await start(client)).json()["outing"]

    events = await turn(client, begun["id"], "就一位来回话")

    assert [e["type"] for e in events] == ["user", "speaker", "delta", "done"]
    assert events[1]["character_id"] == "mano"


def test_who_replies_goes_by_her_affinity_her_relations_and_the_base():
    mano = Candidate(MANO, "trust", {})
    kogane = Candidate(KOGANE, "cold", {})
    assert speaker_weight(mano, []) == 40 + AFFINITY_BASE
    assert speaker_weight(kogane, []) == 0 + AFFINITY_BASE
    related = Candidate(MANO, "trust", {"kogane": "同一组合的队友。"})
    assert speaker_weight(related, ["kogane"]) == 40 + AFFINITY_BASE + RELATION_STEP
    assert speaker_weight(related, ["kogane", "megumi"]) == 40 + AFFINITY_BASE + RELATION_STEP
    # Drawn one at a time, the next against the one drawn: two who know each other both.
    mano = Candidate(MANO, "trust", {"kogane": "队友"})
    kogane = Candidate(KOGANE, "trust", {"mano": "队友"})
    both = pick_speakers([mano, kogane], [], 2, FakeRandom(49, 49))
    assert [each.character.id for each in both] == ["mano", "kogane"]
    only = pick_speakers([mano, kogane], [], 1, FakeRandom(49))  # 50 of the 100
    assert [each.character.id for each in only] == ["mano"]


def test_mentions_are_read_by_name_or_short_name():
    named = mentioned_in("@櫻木真乃 你怎么看？@月岡恋鐘 呢？", [
        Candidate(MANO, "trust", {}), Candidate(KOGANE, "trust", {}),
    ])
    assert [each.character.id for each in named] == ["mano", "kogane"]
    with_short = replace(KOGANE, short_name="恋鐘")
    assert [
        each.character.id
        for each in mentioned_in("恋鐘在吗？@恋鐘！", [Candidate(with_short, "trust", {})])
    ] == ["kogane"]
    assert mentioned_in("没有艾特", [Candidate(MANO, "trust", {})]) == []
    # A name that is not hers, or not after the @, names no one.
    assert mentioned_in("@megumi 转告真乃", [Candidate(MANO, "trust", {})]) == []


def test_labelled_lines_are_read_by_who_wrote_them():
    by_name = {"櫻木真乃": "mano", "真乃": "mano", "月岡恋鐘": "kogane"}
    narration, said = parse_labelled(
        "  \n走进大堂。\n灯暗了。\n真乃：哇。\n真乃：好暗。\n月岡恋鐘：走慢点。", by_name
    )
    assert narration == ["走进大堂。", "灯暗了。"]
    assert said == [("mano", "哇。 好暗。"), ("kogane", "走慢点。")]
    assert parse_labelled("旁白：没人说话。", by_name) == (["旁白：没人说话。"], [])
