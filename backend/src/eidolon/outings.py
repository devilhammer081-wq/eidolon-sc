"""Outings (GLOSSARY.md「外出」): the producer out at one of the outing catalog's locations,
on his own or with one to three characters, and what was said and what happened in each.

Each outing is a row: whose, on his own (`solo`) or with company (`outing`), at which
location, who came along (their character ids; no one on a solo), where it stands — its
opening being written (`opening`), under way (`ongoing`), or over (`ended`, with when) —
and when it began. A solo outing is opened, its walk written into it, and ended at once;
one with company goes on until the producer ends it. What was said and what happened is a
row a line: who said it (a character id, or no one: the producer — and, for a line no one
says, an event), which kind of line it is (something said, a location event, the opening,
the ending), what it says, and, for an event, which of the location's events it was, by
its identifier in the outing catalog — what settling it at the end goes by, with the
location and its participants, the rest of what settling needs. The messages of a group
chat are meant to be kept the same way: the same speaker no one saying it is the producer,
so the table is shaped for it as well.

The rows are the user's (`database.USER_DATA`), deleted with them, not with a
conversation, and in no data package. Settling affinity at the end, and the turns that
lead to it, are elsewhere; this is what they are kept in."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from eidolon.data_access import Database

Kind = Literal["solo", "outing"]
"""On his own, or with company."""

Status = Literal["opening", "ongoing", "ended"]
"""The opening being written, under way, over."""

MessageKind = Literal["say", "event", "opening", "ending"]
"""Something said, a location event, the opening, the ending."""

MAX_PARTICIPANTS = 3
"""The most characters that may come along; one at the least, and no one twice."""

_SCHEMA = """
-- One row per outing (GLOSSARY.md「外出」): whose, on his own (solo) or with company
-- (outing), at which location (its identifier in the outing catalog), who came along (a
-- JSON array of character ids, empty on a solo), where it stands (the opening being
-- written, under way, over), when it began and, once over, when.
CREATE TABLE IF NOT EXISTS outings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('solo', 'outing')),
    location_id TEXT NOT NULL,
    participants TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('opening', 'ongoing', 'ended')),
    created_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE INDEX IF NOT EXISTS outings_by_user ON outings(user_id, id);
-- One row per line of an outing, in the order said: who said it (a character id; NULL for
-- no one, which a character's lines never are — the producer's, and, for an event, the
-- event itself), which kind of line it is (something said, a location event, the opening,
-- the ending), what it says, and, for an event, which of the location's events it was (its
-- identifier in the outing catalog; NULL for every other kind). A group chat's lines are
-- meant to be kept here as well, the same speaker saying whose line it is.
CREATE TABLE IF NOT EXISTS outing_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outing_id INTEGER NOT NULL REFERENCES outings(id),
    speaker TEXT,
    text TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('say', 'event', 'opening', 'ending')),
    event TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS outing_messages_by_outing ON outing_messages(outing_id, id);
"""


class OutingGone(Exception):
    """There is no such outing of the user's to go on with: never was, not theirs, or
    over."""

    def __init__(self) -> None:
        super().__init__("这次外出已经结束了")


@dataclass(frozen=True)
class Outing:
    """An outing as it stands: whose, on his own or with company (who came along), at which
    location, where it stands, when it began and, once over, when."""

    id: int
    user_id: str
    kind: Kind
    location_id: str
    participants: tuple[str, ...]
    """The character ids of who came along; empty on a solo."""
    status: Status
    created_at: datetime
    ended_at: datetime | None
    """None while it stands."""


@dataclass(frozen=True)
class Message:
    """One line of an outing: who said it, which kind of line it is, what it says, and,
    for an event, which of the location's events it was."""

    id: int
    outing_id: int
    speaker: str | None
    """The character id of whoever said it; None for no one, which a character's lines
    never are: the producer's, and, for an event, the event itself."""
    kind: MessageKind
    text: str
    event: str | None
    """The event's identifier in the outing catalog; None for every other kind."""
    created_at: datetime


class Outings:
    """The users' outings in `db`, and the lines of them."""

    def __init__(self, db: Database) -> None:
        self._db = db
        db.prepare(_open)

    async def add(
        self,
        user_id: str,
        kind: Kind,
        location_id: str,
        participants: tuple[str, ...],
        now: datetime,
    ) -> Outing:
        """The user's new outing at `location_id`, its opening to be written, kept with
        `now` as when it began. On a solo no one comes along; with company, one to
        `MAX_PARTICIPANTS`, no one twice."""
        if kind == "solo" and participants:
            raise ValueError("独自外出不带同行角色")
        if kind == "outing" and not participants:
            raise ValueError("同行外出至少要一位角色")
        if len(participants) > MAX_PARTICIPANTS:
            raise ValueError(f"同行最多 {MAX_PARTICIPANTS} 位角色")
        if len(set(participants)) < len(participants):
            raise ValueError("同行的角色里有重复")
        return await self._db.write(_add, user_id, kind, location_id, participants, _utc(now))

    async def begin(self, user_id: str, outing_id: int) -> Outing:
        """The user's outing, its opening written, under way. Raises OutingGone if there is
        no such outing of theirs, or it does not stand at its opening."""
        return await self._db.write(_begin, user_id, outing_id)

    async def end(self, user_id: str, outing_id: int, now: datetime) -> Outing:
        """The user's outing over, `now` when it ended, from its opening (a solo's walk
        written) or under way. Raises OutingGone if there is no such outing of theirs, or
        it is over already."""
        return await self._db.write(_end, user_id, outing_id, _utc(now))

    async def message(
        self,
        user_id: str,
        outing_id: int,
        kind: MessageKind,
        text: str,
        now: datetime,
        speaker: str | None = None,
        event: str | None = None,
    ) -> Message:
        """A line kept in the user's outing `now`: `speaker` whoever said it (None for the
        producer, and for an event, which no one says); `event` which of the location's
        events it was, for a location event only. Raises OutingGone if there is no such
        outing of theirs, or it is over."""
        if (event is not None) != (kind == "event"):
            raise ValueError("只有地点事件能带事件标识，也只有它必须带")
        return await self._db.write(
            _message, user_id, outing_id, kind, text, speaker, event, _utc(now)
        )

    async def outing(self, user_id: str, outing_id: int) -> Outing | None:
        """The user's outing; None if it is not theirs, or there is none."""
        return await self._db.read(_outing, user_id, outing_id)

    async def listed(self, user_id: str) -> list[Outing]:
        """The user's outings, the latest first."""
        return await self._db.read(_listed, user_id)

    async def messages(self, user_id: str, outing_id: int) -> list[Message]:
        """The lines of the user's outing, in the order said; empty if it is not theirs, or
        there is none."""
        return await self._db.read(_messages, user_id, outing_id)


def _open(db: sqlite3.Connection) -> None:
    db.executescript(_SCHEMA)


def _utc(at: datetime) -> str:
    """`at` as the tables keep times: in UTC, so that they compare as text."""
    return at.astimezone(UTC).isoformat()


def _read(row: tuple) -> Outing:
    """The outing a row of `outings` is, `participants` read back as kept."""
    (
        id, user_id, kind, location_id, participants, status, created_at, ended_at,
    ) = row
    return Outing(
        id, user_id, kind, location_id, tuple(json.loads(participants)), status,
        datetime.fromisoformat(created_at), None if ended_at is None else
        datetime.fromisoformat(ended_at),
    )


_OUTING = (
    "SELECT id, user_id, kind, location_id, participants, status, created_at, ended_at"
    " FROM outings WHERE user_id = ? AND id = ?"
)


def _standing(db: sqlite3.Connection, user_id: str, outing_id: int) -> Outing:
    """The user's outing, raising OutingGone unless there is one and it stands; for the
    writes that go on in one."""
    row = db.execute(_OUTING, (user_id, outing_id)).fetchone()
    if row is None or row[5] == "ended":
        raise OutingGone()
    return _read(row)


def _add(
    db: sqlite3.Connection, user_id: str, kind: Kind, location_id: str,
    participants: tuple[str, ...], created_at: str,
) -> Outing:
    cursor = db.execute(
        "INSERT INTO outings (user_id, kind, location_id, participants, status, created_at)"
        " VALUES (?, ?, ?, ?, 'opening', ?)",
        (user_id, kind, location_id, json.dumps(list(participants)), created_at),
    )
    assert cursor.lastrowid is not None
    return _read(db.execute(_OUTING, (user_id, cursor.lastrowid)).fetchone())


def _begin(db: sqlite3.Connection, user_id: str, outing_id: int) -> Outing:
    changed = db.execute(
        "UPDATE outings SET status = 'ongoing' WHERE user_id = ? AND id = ?"
        " AND status = 'opening'",
        (user_id, outing_id),
    ).rowcount
    if not changed:
        raise OutingGone()
    return _read(db.execute(_OUTING, (user_id, outing_id)).fetchone())


def _end(db: sqlite3.Connection, user_id: str, outing_id: int, ended_at: str) -> Outing:
    changed = db.execute(
        "UPDATE outings SET status = 'ended', ended_at = ? WHERE user_id = ? AND id = ?"
        " AND status IN ('opening', 'ongoing')",
        (ended_at, user_id, outing_id),
    ).rowcount
    if not changed:
        raise OutingGone()
    return _read(db.execute(_OUTING, (user_id, outing_id)).fetchone())


def _message(
    db: sqlite3.Connection, user_id: str, outing_id: int, kind: MessageKind, text: str,
    speaker: str | None, event: str | None, created_at: str,
) -> Message:
    _standing(db, user_id, outing_id)
    cursor = db.execute(
        "INSERT INTO outing_messages (outing_id, speaker, text, kind, event, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (outing_id, speaker, text, kind, event, created_at),
    )
    assert cursor.lastrowid is not None
    return Message(
        cursor.lastrowid, outing_id, speaker, kind, text, event,
        datetime.fromisoformat(created_at),
    )


def _outing(db: sqlite3.Connection, user_id: str, outing_id: int) -> Outing | None:
    row = db.execute(_OUTING, (user_id, outing_id)).fetchone()
    return None if row is None else _read(row)


def _listed(db: sqlite3.Connection, user_id: str) -> list[Outing]:
    return [
        _read(row) for row in db.execute(
            "SELECT id, user_id, kind, location_id, participants, status, created_at,"
            " ended_at FROM outings WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
    ]


def _messages(db: sqlite3.Connection, user_id: str, outing_id: int) -> list[Message]:
    if db.execute(_OUTING, (user_id, outing_id)).fetchone() is None:
        return []
    return [
        Message(id, outing, speaker, kind, text, event, datetime.fromisoformat(created_at))
        for id, outing, speaker, kind, text, event, created_at in db.execute(
            "SELECT id, outing_id, speaker, kind, text, event, created_at"
            " FROM outing_messages WHERE outing_id = ? ORDER BY id",
            (outing_id,),
        )
    ]
