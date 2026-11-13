"""The outings in the store (GLOSSARY.md「外出」): made at their opening, gone on with and
ended, their lines kept in the order said — the producer's with no speaker, a character's
with hers, an event with the event of the location's pool it was, which settling at the end
goes by. Another's outing is no one else's, and the rows are the user's, deleted with
them."""

import sqlite3
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from eidolon.data_access import Database
from eidolon.outings import Message, Outing, OutingGone, Outings
from eidolon.store import Store
from tests.fakes import START

A_WHILE_LATER = START + timedelta(hours=2)


@pytest.fixture
async def opened(tmp_path: Path) -> AsyncIterator[tuple[Store, Outings]]:
    """A store and the outings of one database: the store for the users the outings are
    kept by."""
    db = Database(tmp_path / "eidolon.db")
    try:
        yield Store(db), Outings(db)
    finally:
        await db.close()


async def a_user(store: Store, name: str = "producer") -> str:
    return (await store.create_user(name)).id


async def test_an_outing_with_company_is_kept_at_its_opening_and_read_back(
    opened: tuple[Store, Outings],
):
    store, outings = opened
    user = await a_user(store)

    made = await outings.add(user, "outing", "seaside", ("mano", "kogane"), START)

    assert made == Outing(
        1, user, "outing", "seaside", ("mano", "kogane"), "opening", START, None
    )
    assert await outings.outing(user, made.id) == made


async def test_a_solo_outing_is_kept_with_no_one_along(opened: tuple[Store, Outings]):
    store, outings = opened
    user = await a_user(store)

    made = await outings.add(user, "solo", "mall", (), START)

    assert made.participants == ()
    assert made.kind == "solo"


@pytest.mark.parametrize(
    ("kind", "along", "named"),
    [
        ("solo", ("mano",), "不带同行"),
        ("outing", (), "至少要一位"),
        ("outing", ("mano", "kogane", "megumi", "kiriko"), "最多 3 位"),
        ("outing", ("mano", "mano"), "重复"),
    ],
)
async def test_who_comes_along_is_as_it_must_be(
    opened: tuple[Store, Outings], kind: str, along: tuple[str, ...], named: str
):
    store, outings = opened
    user = await a_user(store)

    with pytest.raises(ValueError, match=named):
        await outings.add(user, kind, "seaside", along, START)  # type: ignore[arg-type]


async def test_an_outing_goes_on_and_ends(opened: tuple[Store, Outings]):
    store, outings = opened
    user = await a_user(store)
    made = await outings.add(user, "outing", "amusement-park", ("mano",), START)

    under_way = await outings.begin(user, made.id)

    assert under_way.status == "ongoing"
    assert under_way.ended_at is None
    with pytest.raises(OutingGone):  # it does not stand at its opening any more
        await outings.begin(user, made.id)
    over = await outings.end(user, made.id, A_WHILE_LATER)

    assert over.status == "ended"
    assert over.ended_at == A_WHILE_LATER
    assert (await outings.outing(user, made.id)) == over
    with pytest.raises(OutingGone):  # over is over, for ending again and going on with
        await outings.end(user, made.id, A_WHILE_LATER)
    with pytest.raises(OutingGone):
        await outings.begin(user, made.id)


async def test_a_solo_outing_ends_from_its_opening(opened: tuple[Store, Outings]):
    """A solo's walk is its opening, written all at once: no going on with, straight to
    over."""
    store, outings = opened
    user = await a_user(store)
    made = await outings.add(user, "solo", "seaside", (), START)

    over = await outings.end(user, made.id, A_WHILE_LATER)

    assert (over.status, over.ended_at) == ("ended", A_WHILE_LATER)


async def test_lines_are_kept_in_the_order_said(opened: tuple[Store, Outings]):
    store, outings = opened
    user = await a_user(store)
    made = await outings.add(user, "outing", "seaside", ("mano", "kogane"), START)
    await outings.begin(user, made.id)
    opening = await outings.message(
        user, made.id, "opening", "海风把头发吹乱，浪一遍遍推上沙滩。", START,
    )
    producer = await outings.message(user, made.id, "say", "我们去踩水吧", START)
    mano = await outings.message(
        user, made.id, "say", "ほわっ、裙子会湿掉的……", START, speaker="mano",
    )
    event = await outings.message(
        user, made.id, "event", "浪打过来", START, event="wave-incoming",
    )
    ending = await outings.message(
        user, made.id, "ending", "日落把天压成了蓝紫色。", A_WHILE_LATER,
    )

    assert (opening.speaker, opening.event) == (None, None)
    assert mano.speaker == "mano"
    assert (event.speaker, event.event) == (None, "wave-incoming")
    kept = await outings.messages(user, made.id)
    assert kept == [opening, producer, mano, event, ending]
    assert kept[0] == Message(
        1, made.id, None, "opening", "海风把头发吹乱，浪一遍遍推上沙滩。", None, START,
    )


@pytest.mark.parametrize(
    ("kind", "speaker", "event", "named"),
    [
        ("event", None, None, "只有地点事件"),
        ("say", None, "wave-incoming", "只有地点事件"),
    ],
)
async def test_an_event_line_carries_its_event_and_no_other_line_does(
    opened: tuple[Store, Outings],
    kind: str,
    speaker: str | None,
    event: str | None,
    named: str,
):
    store, outings = opened
    user = await a_user(store)
    made = await outings.add(user, "outing", "seaside", ("mano",), START)

    with pytest.raises(ValueError, match=named):
        await outings.message(
            user, made.id, kind, "浪打过来", START, speaker=speaker, event=event,  # type: ignore[arg-type]
        )


async def test_lines_are_kept_only_while_an_outing_stands(opened: tuple[Store, Outings]):
    store, outings = opened
    user = await a_user(store)
    made = await outings.add(user, "outing", "seaside", ("mano",), START)
    await outings.end(user, made.id, A_WHILE_LATER)

    with pytest.raises(OutingGone):
        await outings.message(user, made.id, "say", "还有一件事", A_WHILE_LATER)


async def test_no_ones_outing_is_anothers(opened: tuple[Store, Outings]):
    store, outings = opened
    user = await a_user(store, "producer")
    other = await a_user(store, "other")
    made = await outings.add(other, "outing", "seaside", ("mano",), START)
    await outings.message(other, made.id, "opening", "到了海边。", START)

    assert await outings.outing(user, made.id) is None
    assert await outings.messages(user, made.id) == []
    with pytest.raises(OutingGone):
        await outings.begin(user, made.id)
    with pytest.raises(OutingGone):
        await outings.end(user, made.id, A_WHILE_LATER)
    with pytest.raises(OutingGone):
        await outings.message(user, made.id, "say", "我也在", A_WHILE_LATER)


async def test_outings_list_latest_first(opened: tuple[Store, Outings]):
    store, outings = opened
    user = await a_user(store)
    seaside = await outings.add(user, "solo", "seaside", (), START)
    mall = await outings.add(user, "outing", "mall", ("mano",), A_WHILE_LATER)
    cinema = await outings.add(user, "outing", "cinema", ("kogane",), A_WHILE_LATER)

    assert [each.id for each in await outings.listed(user)] == [
        cinema.id, mall.id, seaside.id,
    ]
    other = await a_user(store, "other")
    assert await outings.listed(other) == []


async def test_deleting_the_user_deletes_their_outings(
    opened: tuple[Store, Outings], tmp_path: Path
):
    store, outings = opened
    user = await a_user(store)
    made = await outings.add(user, "outing", "seaside", ("mano",), START)
    await outings.message(user, made.id, "opening", "到了海边。", START)

    await store.delete_user(user)

    assert await outings.listed(user) == []
    with sqlite3.connect(tmp_path / "eidolon.db") as db:  # and the rows with them
        assert db.execute("SELECT COUNT(*) FROM outings").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM outing_messages").fetchone() == (0,)
