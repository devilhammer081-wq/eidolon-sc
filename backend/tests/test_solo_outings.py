"""The producer's walks on his own (GLOSSARY.md「独自外出」) and the chance meetings they
end in (GLOSSARY.md「偶遇」) — driven through the backend's external API, with the walk's
location usually named by the request, the chance fixed by the fake random source or by the
admin console, and whom he meets told by her affinity, kept in the database directly, and by
her place likes.

A walk is one or two paragraphs of notes, written by the deployer's chat model from the
location's scene and who the producer is, kept as the outing's opening lines and ended at
once, nothing kept should the model fail or say nothing. A meeting, drawn at the configured
chance, opens her conversation — a new one, hers from then on — with her first words kept as
her reaching out is, and the outing ends with a line naming her its speaker: who was met,
read back by the outings' history. Who is met is drawn weighted, by her affinity with the
producer and by whether she likes the kinds of place the location counts as."""

import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from eidolon.assembly import Backend
from eidolon.characters import Character
from eidolon.config import Settings
from eidolon.llm import LLMError, Streamed
from eidolon.outing_catalog import OutingLocation
from eidolon.outing_prompt import ENCOUNTER_RULES, MET_HIM, WALK_RULES, parse_walk_notes
from eidolon.producer import Birthday
from eidolon.randomness import falls_in
from eidolon.solo_outings import encounter_weight, likes_the_place_of
from tests.conftest import CharacterConfig, ClientFactory, KOGANE_SHEET, MANO_SHEET
from tests.fakes import (
    FAKE_JUDGE,
    FakeClock,
    FakeIdentityProvider,
    FakeLLM,
    FakeRandom,
    context_of,
    system_of,
)
from tests.test_affinity import keep
from tests.test_admin_users import ADMIN, admin_beside
from tests.test_text_turn import send_turn, start_conversation

NOTES = (
    "傍晚的海边没什么人。海风把浪一层层推上来，又退回去。",
    "远处防波堤上落了几只海鸥，卖冰淇淋的小屋收了摊。",
)
"""The walk's notes, as the model is scripted to write them, two paragraphs."""
NOTE_REPLY = [NOTES[0] + "\n\n" + NOTES[1]]
OPENING = [
    "<ja>[happily] わっ、プロデューサーさん！</ja><zh>哇，制作人！</zh>",
    "<ja>海を見に来たの？</ja><zh>来看海吗？</zh>",
]
"""Her opening of the meeting, as the model is scripted to write it, in segments."""
REPLY = ["<ja>こんにちは！</ja><zh>你好！</zh>"]
"""Her reply to the turn before the walk, as the model is scripted to write it."""
OUTINGS = "/api/admin/config/outings"


@pytest.fixture
def characters(tmp_path: Path) -> CharacterConfig:
    """Mano, who likes the seaside among her kinds of place, and Kogane, who likes none an
    outing location counts as."""
    return (
        CharacterConfig(tmp_path / "characters")
        .add("mano", "櫻木真乃", MANO_SHEET, place_likes=("seaside", "cafe"))
        .add("kogane", "月岡恋鐘", KOGANE_SHEET, place_likes=("books", "shrine"))
    )


def backend_of(client: httpx.AsyncClient) -> Backend:
    return client._transport.app.state.backend  # pyright: ignore[reportAttributeAccessIssue]


async def walk(
    client: httpx.AsyncClient, location_id: str | None = "seaside"
) -> httpx.Response:
    """Set the signed-in producer out on his own, at `location_id` or anywhere."""
    return await client.post("/api/outings/solo", json={"location_id": location_id})


async def outings_of(client: httpx.AsyncClient) -> list[dict]:
    res = await client.get("/api/outings")
    assert res.status_code == 200
    return res.json()["outings"]


def records(settings: Settings) -> list[tuple[str, str, str]]:
    """The activity records' kinds, characters and results, in the order they began."""
    with sqlite3.connect(settings.database_path) as db:
        return db.execute(
            "SELECT kind, character_id, result FROM activity_records ORDER BY id"
        ).fetchall()


async def test_a_walk_writes_one_or_two_paragraphs_of_notes_and_ends_the_outing(
    make_client: ClientFactory, settings: Settings
):
    """The chance missed: just the notes, no meeting, one ask of the model."""
    llm = FakeLLM(NOTE_REPLY)
    client = make_client(llm, random=FakeRandom(999_999))  # the chance, missed

    walked = await walk(client)

    assert walked.status_code == 201
    assert walked.json() == {
        "outing": {
            "id": walked.json()["outing"]["id"],
            "kind": "solo",
            "location_id": "seaside",
            "location_name": "海边",
            "participants": [],
            "status": "ended",
            "created_at": walked.json()["outing"]["created_at"],
            "ended_at": walked.json()["outing"]["ended_at"],
            "encounter": None,
            "messages": [
                {
                    "speaker": None, "kind": "opening", "text": NOTES[0], "event": None,
                    "created_at": walked.json()["outing"]["created_at"],
                },
                {
                    "speaker": None, "kind": "opening", "text": NOTES[1], "event": None,
                    "created_at": walked.json()["outing"]["created_at"],
                },
            ],
        },
        "encounter": None,
    }
    assert walked.json()["outing"]["created_at"] == walked.json()["outing"]["ended_at"]
    [listed] = await outings_of(client)
    assert listed == walked.json()["outing"]
    assert len(llm.prompts) == 1  # no opening asked of the model
    prompt = llm.prompts[0]
    scene = backend_of(client).outing_catalog["seaside"].scene
    assert scene in system_of(prompt)
    assert "# 制作人" in system_of(prompt)
    assert WALK_RULES in system_of(prompt)
    assert prompt[-1].content == "（制作人走进这个地方，一个人慢慢走。）"
    assert records(settings) == [("outing", "", "success")]


async def test_more_notes_than_two_are_kept_as_two(make_client: ClientFactory):
    client = make_client(
        FakeLLM(["一。\n\n二。\n\n三。"]), random=FakeRandom(999_999)
    )

    walked = await walk(client)

    assert [m["text"] for m in walked.json()["outing"]["messages"]] == ["一。", "二。"]


async def test_a_location_left_unnamed_is_drawn_from_the_catalog(make_client: ClientFactory):
    client = make_client(FakeLLM(NOTE_REPLY), random=FakeRandom(0, 999_999))

    walked = await walk(client, None)

    assert walked.json()["outing"]["location_id"] == "cinema"  # the first in the catalog


async def test_a_location_the_catalog_has_not_is_no_walk(make_client: ClientFactory):
    client = make_client(FakeLLM())

    assert (await walk(client, "the-moon")).status_code == 404
    assert await outings_of(client) == []


@pytest.mark.parametrize("reply", [LLMError("the model is down"), [""]])
async def test_a_walk_the_model_fails_or_leaves_empty_keeps_nothing(
    make_client: ClientFactory, settings: Settings, reply: Sequence[Streamed | object] | LLMError
):
    client = make_client(FakeLLM(reply), random=FakeRandom(999_999))

    walked = await walk(client)

    assert walked.status_code == 502
    assert walked.json()["detail"] == "这次外出没有成行，请稍后再试"
    assert await outings_of(client) == []
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM outings").fetchone() == (0,)
    assert records(settings) == [("outing", "", "failed")]


async def test_a_meeting_is_drawn_at_the_chance_the_admin_console_sets(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    """0 never meets, even at the best roll there is; and only a number from 0 to 1 is a
    chance at all."""
    client = make_client(
        FakeLLM(NOTE_REPLY, NOTE_REPLY),
        settings=replace(settings, admins=frozenset({ADMIN})),
        random=FakeRandom(999_999, 999_999),  # the worst roll there is, twice
    )

    assert (await walk(client)).json()["encounter"] is None  # at the default 0.3, missed

    async with admin_beside(client, github) as admin:
        described = (await admin.get("/api/admin/config")).json()["outings"]
        refused = [
            (await admin.put(OUTINGS, json={"encounter_chance": chance})).status_code
            for chance in (1.5, -0.1, True, "30%")
        ]
        never = await admin.put(OUTINGS, json={"encounter_chance": 0})
        never_met = await walk(client)

    assert described == {
        "status": "env",
        "env": {"encounter_chance": 0.3, "responders_max": 2},
        "effective": {"encounter_chance": 0.3, "responders_max": 2},
        "override": None, "failure": None,
    }
    assert refused == [422, 422, 422, 422]
    assert never.status_code == 200
    assert never.json()["outings"]["effective"] == {
        "encounter_chance": 0, "responders_max": 2
    }
    assert never_met.json()["encounter"] is None


async def test_at_the_full_chance_he_always_meets_someone(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    client = make_client(
        FakeLLM(NOTE_REPLY, OPENING),
        settings=replace(settings, admins=frozenset({ADMIN})),
        random=FakeRandom(999_999, 0),  # the worst roll there is, met anyway; the draw, Mano
    )
    async with admin_beside(client, github) as admin:
        await admin.put(OUTINGS, json={"encounter_chance": 1})

    walked = await walk(client)

    assert walked.json()["encounter"]["character_id"] == "mano"


async def test_a_meeting_opens_her_conversation_with_her_first_words(
    make_client: ClientFactory, settings: Settings
):
    """Mano, drawn by the roll and her liking of the seaside: a new conversation of hers,
    opened by her reaching out, from the scene and his notes; the outing naming her its
    ending line."""
    llm = FakeLLM(NOTE_REPLY, OPENING)
    client = make_client(llm, random=FakeRandom(0, 99))

    walked = await walk(client)

    assert walked.status_code == 201
    encounter = walked.json()["encounter"]
    assert encounter["character_id"] == "mano"
    conversation = encounter["conversation_id"]
    opening = encounter["opening"]
    assert opening["ja"] == "わっ、プロデューサーさん！海を見に来たの？"
    assert opening["zh"] == "哇，制作人！来看海吗？"
    [ending] = [
        m for m in walked.json()["outing"]["messages"] if m["kind"] == "ending"
    ]
    assert ending["speaker"] == "mano"
    assert ending["text"] == "在海边偶遇了櫻木真乃。"
    [listed] = await outings_of(client)
    assert listed["encounter"] == {"character_id": "mano", "character_name": "櫻木真乃"}
    assert records(settings) == [("outing", "mano", "success")]

    said = await client.get(f"/api/conversations/{conversation}/messages")
    assert said.status_code == 200
    assert [entry["type"] for entry in said.json()] == ["reach_out"]
    latest = (await client.get("/api/conversations/latest")).json()
    assert [c for c in latest if c["character_id"] == "mano"] == [{
        "character_id": "mano",
        "conversation_id": conversation,
        "created_at": latest[0]["created_at"],
        "last_message": {
            "role": "character", "text": None, "ja": opening["ja"], "zh": opening["zh"],
            "created_at": opening["created_at"], "reach_out": True,
        },
        "unseen_reach_out": False,  # reading the conversation has seen it
        "unread_letter": False,
    }]

    [notes_prompt, opening_prompt] = llm.prompts
    assert opening_prompt[0].content.startswith(MANO_SHEET)
    context = context_of(opening_prompt)
    assert "海边" in context
    assert NOTES[0] in context and NOTES[1] in context
    assert ENCOUNTER_RULES in context
    assert opening_prompt[-1].content == MET_HIM


async def test_who_he_meets_goes_by_her_affinity_with_him(
    make_client: ClientFactory, settings: Settings
):
    """Mano cold, Kogane in trust, at a place neither likes: the draw at ten of sixty meets
    Kogane, not Mano."""
    settings = replace(settings, judge=FAKE_JUDGE)
    clock = FakeClock()
    llm = FakeLLM(NOTE_REPLY, OPENING)
    client = make_client(llm, settings=settings, clock=clock, random=FakeRandom(0, 10))
    keep(settings.database_path, "producer", 5, clock(), character="mano")

    walked = await walk(client, "cinema")

    assert walked.json()["encounter"]["character_id"] == "kogane"
    assert walked.json()["encounter"]["opening"]["ja"] == "わっ、プロデューサーさん！海を見に来たの？"


@pytest.mark.parametrize("drawn", [99, 100])
async def test_who_he_meets_goes_by_her_place_likes(
    make_client: ClientFactory, characters: CharacterConfig, drawn: int
):
    """Mano likes the seaside, Kogane no outing location's kind: of their hundred and fifty
    chances, the first hundred are Mano's."""
    client = make_client(
        FakeLLM(NOTE_REPLY, OPENING), random=FakeRandom(0, drawn)
    )

    walked = await walk(client)

    assert walked.json()["encounter"]["character_id"] == (
        "mano" if drawn < 100 else "kogane"
    )


async def test_the_meeting_opens_a_new_conversation_where_they_already_have_one(
    make_client: ClientFactory
):
    llm = FakeLLM(REPLY, NOTE_REPLY, OPENING)
    client = make_client(llm, random=FakeRandom(0, 0))
    talking = await start_conversation(client)  # her current one, with a turn in it
    await send_turn(client, talking, "我去海边散步了")

    walked = await walk(client)

    conversation = walked.json()["encounter"]["conversation_id"]
    listed = (await client.get("/api/conversations", params={"character_id": "mano"})).json()
    assert [each["id"] for each in listed] == [conversation, talking]


def test_the_notes_are_read_as_paragraphs():
    assert parse_walk_notes("") == []
    assert parse_walk_notes("  \n\n  ") == []
    assert parse_walk_notes("一段。") == ["一段。"]
    assert parse_walk_notes("一段。\n\n两段。") == ["一段。", "两段。"]
    assert parse_walk_notes("一。\n\n二。\n\n三。") == ["一。", "二。"]


def test_her_chance_of_being_met_goes_by_her_tier_and_hers_no_place_liked():
    assert encounter_weight("cold", False) == 10
    assert encounter_weight("distant", False) == 30
    assert encounter_weight("trust", False) == 50
    assert encounter_weight("close", False) == 75
    assert encounter_weight("intimate", False) == 95
    assert encounter_weight(None, False) == 50  # affinity off: trust for everyone
    assert encounter_weight("trust", True) == 100
    assert encounter_weight("cold", True) == 20


def test_whether_she_likes_the_place_of_a_location():
    seaside = OutingLocation("seaside", "海边", "…", "…", ("seaside",), ())
    assert likes_the_place_of(
        Character(
            "mano", "櫻木真乃", "", "voice", "sheet", None, "#ffbad6", Birthday(4, 25), 16,
            place_likes=("seaside", "cafe"),
        ),
        seaside,
    )
    assert not likes_the_place_of(
        Character(
            "kogane", "月岡恋鐘", "", "voice", "sheet", None, "#f84cad", Birthday(2, 25), 19,
            place_likes=("books",),
        ),
        seaside,
    )
    assert not likes_the_place_of(
        Character("kogane", "月岡恋鐘", "", "voice", "sheet", None, "#f84cad", Birthday(2, 25), 19),
        seaside,
    )


def test_the_draw_picks_whose_chance_it_falls_in():
    assert falls_in([10, 30], 0) == 0
    assert falls_in([10, 30], 9) == 0
    assert falls_in([10, 30], 10) == 1
    assert falls_in([10, 30], 39) == 1
    assert falls_in([100, 50], 99) == 0
    assert falls_in([100, 50], 100) == 1
