"""Interaction actions (GLOSSARY.md「互动动作」): what the user does to her with a tap —
a pat on the head, a hug, a snack handed over — taken as a turn of its own by its
`interaction_id`, she answering as the action's scene and her tier say. Any action is
offered at any tier, each naming the tier it is meant for; taken below it she refuses or
is embarrassed and her affinity raises none, at or above it she takes it well and it
raises by its own delta, worn out by half as much each time it repeats among the
conversation's latest turns. The turn's message is marked with the action's id, that the
history may show it as it happened.

The catalog and its judgements are tested apart; the turns are driven through the
backend's external API, the judge model faked turn by turn, as `test_affinity_turns`
drives its."""

from dataclasses import replace

import httpx
import pytest

from eidolon.affinity import Judged
from eidolon.config import Settings
from eidolon.interactions import (
    BELOW_STEP,
    CATALOG,
    BY_ID,
    affinity_step,
    decay,
    reaches,
    she_may,
    taken_before,
    turn_lines,
    weariness_lines,
)
from eidolon.reply_format import take_action
from tests.test_text_turn import send_turn
from eidolon.store import Message
from tests.conftest import ClientFactory
from tests.fakes import FAKE_JUDGE, FakeClock, FakeServiceClients, FakeLLM, level
from tests.test_affinity import keep
from tests.test_affinity_turns import value
from tests.test_text_turn import start_conversation

REPLY = ["<ja>はい</ja><zh>好的</zh>"]


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With the judge model and affinity on in `.env`, as interaction turns are judged."""
    return replace(settings, judge=FAKE_JUDGE, affinity_and_gifts=True)


def user_message(interaction_id: str | None = None) -> Message:
    """A user's message as `taken_before` reads them, marked or not with an action."""
    return Message(1, "user", "（动作）", None, None, "2026-01-01T00:00:00+00:00",
                   interaction_id=interaction_id)


def test_the_catalog_names_every_action_once_in_its_tiers_order():
    """菜单按推荐档位从低到高排；同档位里保持写定的先后。"""
    assert [i.id for i in CATALOG] == [
        "high_five", "poke_cheek", "pat_head", "hug", "kiss", "hold_hands", "tidy_hair",
        "tidy_collar",
    ]
    assert [i.recommended_tier for i in CATALOG] == [
        "trust", "trust", "close", "close", "intimate", "intimate", "intimate", "intimate",
    ]
    assert len(BY_ID) == len(CATALOG)
    assert all(i.acted.startswith("（") for i in CATALOG)
    assert all(i.scene for i in CATALOG)


def test_where_a_tier_stands_against_the_recommended_one():
    pat = BY_ID["pat_head"]  # meant for close
    assert [reaches(pat, t) for t in ("cold", "distant", "trust", "close", "intimate")] == [
        "below", "below", "below", "at", "above",
    ]
    assert reaches(pat, None) == "at"  # affinity off: taken as at it


def test_the_reaction_told_her_by_her_tier():
    pat = BY_ID["pat_head"]
    below = turn_lines(pat, "trust", 0)
    at = turn_lines(pat, "close", 0)
    assert pat.scene in below and pat.scene in at
    assert any("还没有亲近到" in line for line in below)
    assert any("反应良好" in line for line in at)
    assert not any("亲近到" in line and "没有" in line for line in at)


def test_weariness_wears_the_action_out_by_half_each_time():
    assert [decay(n) for n in range(4)] == pytest.approx([1.0, 0.5, 0.25, 0.125])
    assert weariness_lines(0) == weariness_lines(1) == []
    assert len(weariness_lines(2)) == 1
    lines = turn_lines(BY_ID["high_five"], "trust", 2)
    assert any("好几次" in line for line in lines)


def test_how_many_times_the_same_action_was_taken_lately():
    messages = [user_message(), user_message("hug"), user_message("high_five"),
                user_message("high_five"), Message(2, "character", None, "", "", "2026-01-01T00:00:00+00:00")]
    assert taken_before(BY_ID["high_five"], messages) == 2
    assert taken_before(BY_ID["hug"], messages) == 1
    assert taken_before(BY_ID["hug"], [user_message("hug")] * 20) == 8  # the latest turns only


def test_the_step_an_action_changes_her_affinity_by():
    pat, judged_happy = BY_ID["pat_head"], Judged(4)
    # Below its recommended tier: none, however happy the judge model made its line.
    assert affinity_step(pat, "trust", judged_happy, 0) == BELOW_STEP
    # At or above: its own delta, worn out as it repeats.
    assert [affinity_step(pat, "close", judged_happy, n) for n in range(3)] == pytest.approx(
        [0.3, 0.15, 0.075]
    )
    assert affinity_step(BY_ID["kiss"], "intimate", judged_happy, 0) == pytest.approx(1.0)
    # Not judged, or judged to lower it — out of line above all: the judge's own.
    assert affinity_step(pat, "close", None, 0) is None
    assert affinity_step(pat, "close", Judged(0), 0) is None
    assert affinity_step(pat, "close", Judged(4, out_of_line=True), 0) is None


async def send_interaction(
    client: httpx.AsyncClient, conversation_id: str, interaction_id: str
) -> list[dict]:
    """Take a turn by its `interaction_id`, saying nothing with it, and collect the
    server-sent events it streams back."""
    import json

    events: list[dict] = []
    async with client.stream(
        "POST", f"/api/conversations/{conversation_id}/turns",
        json={"interaction_id": interaction_id},
    ) as res:
        assert res.status_code == 200
        async for line in res.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events


async def test_the_catalog_is_offered_over_the_api(make_client: ClientFactory):
    client = make_client(FakeLLM())
    listed = (await client.get("/api/interactions")).json()
    assert [i["id"] for i in listed] == [i.id for i in CATALOG]
    assert listed[0] == {
        "id": "high_five", "name": "击掌", "emoji": "🙌", "recommended_tier": "trust",
    }


async def test_an_unknown_interaction_is_rejected(make_client: ClientFactory):
    client = make_client(FakeLLM())
    conversation_id = await start_conversation(client)
    res = await client.post(
        f"/api/conversations/{conversation_id}/turns", json={"interaction_id": "nope"}
    )
    assert res.status_code == 422


async def test_an_interaction_turn_plays_the_action_and_is_kept_marked(
    make_client: ClientFactory, settings: Settings
):
    clients = FakeServiceClients()
    clients.judge.judgings = [level(4)]
    llm = FakeLLM(REPLY)
    client = make_client(llm, clients=clients, clock=FakeClock())
    conversation_id = await start_conversation(client)

    events = await send_interaction(client, conversation_id, "pat_head")

    pat = BY_ID["pat_head"]
    assert events[0] == {"type": "user", "text": pat.acted}  # the action plays, nothing typed
    assert events[-1]["type"] == "done"
    # Her prompt carries the action's scene and how she is to take it (trust, below close).
    system = "\n".join(m.content for m in llm.prompts[0] if m.role == "system")
    assert pat.scene in system and "还没有亲近到" in system
    # The user's message keeps its mark; the reply has none; the history tells it again.
    messages = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()
    assert [m.get("interaction_id") for m in messages] == ["pat_head", None]
    reopened = make_client(FakeLLM())
    again = (await reopened.get(f"/api/conversations/{conversation_id}/messages")).json()
    assert [m.get("interaction_id") for m in again] == ["pat_head", None]


async def test_an_interaction_changes_her_affinity_by_its_own_worn_out_step(
    make_client: ClientFactory, settings: Settings
):
    clock = FakeClock()
    clients = FakeServiceClients()
    clients.judge.judgings = [level(4)] * 3
    client = make_client(FakeLLM(*[REPLY] * 3), clients=clients, clock=clock)
    conversation_id = await start_conversation(client)
    keep(settings.database_path, "producer", 70, clock.now)  # close: a pat on the head is meant for it

    await send_interaction(client, conversation_id, "pat_head")
    await send_interaction(client, conversation_id, "pat_head")
    await send_interaction(client, conversation_id, "hug")  # close too

    # 0.3, then half as much again worn out; the hug's 0.5 takes it to 0.95, still under
    # the day's 1.0 for turns (GAINS_PER_DAY).
    assert value(settings.database_path) == pytest.approx(70.95)
    # Taken below its recommended tier, it raises none: trust, a kiss meant for intimate.
    keep(settings.database_path, "producer", 50, clock.now)
    await send_interaction(client, conversation_id, "kiss")
    assert value(settings.database_path) == pytest.approx(50)


# --- 她主动的互动动作（spec 的三条边界：只做 1:1、不加分、低于推荐档位她不会做） ---


def test_she_may_only_what_her_tier_reaches():
    """档位门控：够推荐档位才可选，低了不行；好感度关着时全都可以（视作信任）。"""
    hug = BY_ID["hug"]  # meant for close
    assert [she_may(hug, t) for t in ("cold", "distant", "trust", "close", "intimate")] == [
        False, False, False, True, True,
    ]
    assert she_may(hug, None) is True


def test_her_side_of_every_action_is_written():
    """每个动作都有她做的那一侧：叙述行和给她的场景。"""
    assert all(i.her_acted.startswith("（") and i.her_acted.endswith("。）") for i in CATALOG)
    assert all("你" in i.her_scene and "制作人" in i.her_scene for i in CATALOG)
    assert all(i.acted != i.her_acted for i in CATALOG)


def test_take_action_reads_the_tag_out_of_her_reply():
    """标签在台词之外：抽出来，台词原样留下；没写或没关上就什么都没有。"""
    assert take_action("<action>hug</action><ja>ぎゅっ</ja><zh>抱住你</zh>") == (
        "hug", "<ja>ぎゅっ</ja><zh>抱住你</zh>",
    )
    assert take_action("没有动作的回复") == ("", "没有动作的回复")
    assert take_action("<action>") == ("", "<action>")
    # 写了两个的只算第一个
    assert take_action("<action>hug</action>台词<action>kiss</action>") == (
        "hug", "台词<action>kiss</action>",
    )


async def test_she_takes_an_action_of_her_own_in_her_reply(
    make_client: ClientFactory, settings: Settings
):
    """她够档位：清单进 prompt，她写的动作全链路落库（她自己那条标着 id）。"""
    clients = FakeServiceClients()
    clients.judge.judgings = [level(4)]
    llm = FakeLLM(["<action>hug</action><ja>ぎゅっと</ja><zh>抱住了你</zh>"])
    clock = FakeClock()
    client = make_client(llm, clients=clients, clock=clock)
    conversation_id = await start_conversation(client)
    keep(settings.database_path, "producer", 70, clock(), character="mano")

    await send_turn(client, conversation_id, "辛苦了")

    # 她的清单在 prompt 里：拥抱（亲近）够档位，亲她那侧的场景也在。
    system = "\n".join(m.content for m in llm.prompts[0] if m.role == "system")
    assert "<action>hug</action>" in system and BY_ID["hug"].her_scene in system
    # 不够档位的（亲密档的亲吻，她只有亲近）不在清单里。
    assert "<action>kiss</action>" not in system
    # 她的消息带着动作，用户的没有；动作加不了好感（只有 judge 的那一步）。
    messages = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()
    assert [m.get("interaction_id") for m in messages] == [None, "hug"]
    # 她的动作不加分（spec 的第二条边界）：好感只按 judge 对台词的评判走一步。
    assert value(settings.database_path) == 70.2


async def test_an_action_beyond_her_tier_is_quietly_ignored(
    make_client: ClientFactory, settings: Settings
):
    """她不够档位：不在清单里，硬写也当作没发生——台词照常。"""
    clients = FakeServiceClients()
    clients.judge.judgings = [level(0)]
    llm = FakeLLM(["<action>kiss</action><ja>えっと</ja><zh>那个……</zh>"])
    client = make_client(llm, clients=clients, clock=FakeClock())
    conversation_id = await start_conversation(client)  # trust: kiss (intimate) is beyond her

    await send_turn(client, conversation_id, "辛苦了")

    system = "\n".join(m.content for m in llm.prompts[0] if m.role == "system")
    assert "<action>kiss</action>" not in system
    messages = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()
    assert [m.get("interaction_id") for m in messages] == [None, None]
    # 台词没有带标签地留下来了。
    assert messages[-1]["zh"] == "那个……"


async def test_she_does_not_do_the_same_action_twice_in_a_row(
    make_client: ClientFactory, settings: Settings
):
    """她上一条做过的动作，这一回合的清单里不给：换个动作或先不做出清单的事。"""
    clients = FakeServiceClients()
    clients.judge.judgings = [level(4)]
    llm = FakeLLM(
        ["<action>hug</action><ja>ぎゅっと</ja><zh>抱住了你</zh>"],
        ["<ja>またね</ja><zh>下次见</zh>"],
    )
    clock = FakeClock()
    client = make_client(llm, clients=clients, clock=clock)
    conversation_id = await start_conversation(client)
    keep(settings.database_path, "producer", 70, clock(), character="mano")
    await send_turn(client, conversation_id, "辛苦了")

    await send_turn(client, conversation_id, "明天见")

    system = "\n".join(m.content for m in llm.prompts[1] if m.role == "system")
    assert "<action>hug</action>" not in system  # her previous one held back
    assert "<action>pat_head</action>" in system  # others still offered
