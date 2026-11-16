"""The 283 office's group chat (GLOSSARY.md「群聊」): the producer and every character of the
configuration in one chat, and the producer's turns in it.

Each user's chat is its own timeline, kept as the outings keep their lines: one row a line,
who said it (a character id, or no one: the producer), which kind of line it is (something
said, a topic's opening, its ending), what it says and when — the same speaker saying whose
line it is, but a table of the chat's own, no outing's. Beside the lines stands the chat's
state, one row per user: where its topic stands — who opened it, who of the characters has
spoken in it and in what order, how many turns it has taken; no topic underway leaves those
empty — and when the producer last read the chat, which is what the unread mark goes by.

The producer speaks whenever he likes (`turn`): whoever he @-names replies alone, no one
else drawn; otherwise one or two of the characters are drawn — weighted by affinity and
relations as the multi-character engine draws (`group_turns.pick_speakers`) or uniformly,
whichever way the live configuration has it — and each replies as one speaker among several,
seeing the lines so far and whoever spoke before her, her reply streamed as it is written.
A turn that fails keeps none of its lines. Reading the chat (`shown`) is what marks it
read; a turn does too, for the producer watched its replies. Who opens a topic, and the
characters carrying it on, is the topic scheduler's (`group_topics`), not the chat's own.
"""

import json
import logging
import sqlite3
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from eidolon.activity import ActivityLog
from eidolon.affinity import Affinities, Tier
from eidolon.characters import Character
from eidolon.clock import Clock
from eidolon.data_access import Database
from eidolon.engine import BLANK, FAILED, MAX_INPUT_LENGTH, TOO_LONG
from eidolon.group_turns import (
    TO_ALL,
    TO_HER,
    Candidate,
    SceneMaterial,
    mentioned_in,
    pick_speakers,
    speaker_prompt,
)
from eidolon.live_config import LiveConfig
from eidolon.moments import relations
from eidolon.producer import ProducerProfile, effective_timezone, local_date
from eidolon.randomness import Random
from eidolon.store import Store
from eidolon.world import World

if TYPE_CHECKING:
    from eidolon.group_topics import GroupTopics

log = logging.getLogger(__name__)

MessageKind = Literal["say", "topic_open", "topic_end"]
"""Something said, a topic's opening, its ending."""

TIMELINE_LINES = 50
"""How many of the chat's latest lines the timeline carries."""

RECENT_LINES = 16
"""How many of the chat's latest lines a prompt carries: the latest, that a prompt opens
alike from turn to turn."""

SPOKEN_LINES = 10
"""Over how many of the latest lines who has spoken already is read, for drawing who
replies."""

GROUP_SCENE = "283事务所的群聊，制作人和事务所的偶像们都在群里。"
"""Where they are, as a speaker's prompt tells it of the chat."""

Schema = """
-- One row per line of a user's group chat (GLOSSARY.md「群聊」), in the order said: who
-- said it (a character id; NULL for no one, which a character's lines never are — the
-- producer's, and, for a topic's ending, the ending itself), which kind of line it is
-- (something said, a topic's opening, its ending), what it says and when.
CREATE TABLE IF NOT EXISTS group_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    speaker TEXT,
    text TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('say', 'topic_open', 'topic_end')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS group_messages_by_user ON group_messages(user_id, id);
-- One row per user's group chat: where its topic stands — who opened it, who of the
-- characters has spoken in it and in what order (a JSON array of character ids), how many
-- turns it has taken; all three NULL while no topic is underway — and when the producer
-- last read the chat, NULL until he first does.
CREATE TABLE IF NOT EXISTS group_state (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    opener TEXT,
    spoken TEXT,
    turns INTEGER,
    read_at TEXT,
    CHECK ((opener IS NULL AND spoken IS NULL AND turns IS NULL)
        OR (opener IS NOT NULL AND spoken IS NOT NULL AND turns IS NOT NULL))
);
"""


class GroupChatOff(Exception):
    """The deployer has the group chat closed; there is nothing to read or say in it."""


@dataclass(frozen=True)
class Message:
    """One line of the chat: who said it, which kind of line it is, what it says, when."""

    id: int
    user_id: str
    speaker: str | None
    """The character id of whoever said it; None for no one, which a character's lines
    never are: the producer's, and, for a topic's ending, the ending itself."""
    kind: MessageKind
    text: str
    created_at: datetime


@dataclass(frozen=True)
class Topic:
    """A topic underway in a user's chat: who opened it, who of the characters has spoken
    in it and in what order (the opener first), and how many turns it has taken — one for
    each character's line in it, the opening one counted."""

    opener: str
    spoken: tuple[str, ...]
    turns: int


@dataclass(frozen=True)
class GroupState:
    """Where a user's chat stands: its topic underway, None while none is, and when the
    producer last read the chat, None until he first does."""

    user_id: str
    topic: Topic | None
    read_at: datetime | None


class GroupChats:
    """Every user's group chat in `db`: the lines of it, and where its topic stands."""

    def __init__(self, db: Database) -> None:
        self._db = db
        db.prepare(_prepare)

    async def say(
        self, user_id: str, text: str, now: datetime, speaker: str | None = None
    ) -> Message:
        """A line of the user's chat kept `now`: `speaker` whoever said it (None for the
        producer). A character's line takes a turn of the topic underway, if one stands;
        with none underway it is kept all the same."""
        return await self._db.write(_say, user_id, text, speaker, _utc(now))

    async def open_topic(
        self, user_id: str, opener: str, text: str, now: datetime
    ) -> Message:
        """The character `opener`'s new topic: its opening line kept `now`, the topic
        underway from it — she the first to have spoken, its first turn taken. Only one
        topic stands at a time: ValueError while one does."""
        return await self._db.write(_open_topic, user_id, opener, text, _utc(now))

    async def end_topic(self, user_id: str, text: str, now: datetime) -> Message:
        """The topic's closing line kept `now` (no one's words: not the producer's), no
        topic underway any more. ValueError if none stands."""
        return await self._db.write(_end_topic, user_id, text, _utc(now))

    async def timeline(self, user_id: str, limit: int = TIMELINE_LINES) -> list[Message]:
        """The latest `limit` lines of the user's chat, oldest first."""
        return await self._db.read(_timeline, user_id, limit)

    async def state(self, user_id: str) -> GroupState:
        """Where the user's chat stands."""
        return await self._db.read(_state, user_id)

    async def mark_read(self, user_id: str, now: datetime) -> None:
        """The producer read the chat `now`; what shows after is unread no longer."""
        await self._db.write(_mark_read, user_id, _utc(now))

    async def unread(self, user_id: str) -> bool:
        """Whether a character has said anything in the chat since the producer last read
        it; whether anyone ever has, if he never has. His own lines are never unread."""
        return await self._db.read(_unread, user_id)

    async def topics_opened(self, user_id: str, since: str) -> int:
        """How many topics have been opened in the user's chat since `since` (as the tables
        keep times): the day's quota counted from it."""
        return await self._db.read(_topics_opened, user_id, since)


@dataclass(frozen=True)
class ProducerSaid:
    """What the producer said, as the turn takes it up; every turn opens with it."""

    text: str
    type: Literal["user"] = field(default="user", init=False)


@dataclass(frozen=True)
class SpeakerUp:
    """Who is about to speak, announced before her first words."""

    character_id: str
    name: str
    color: str
    type: Literal["speaker"] = field(default="speaker", init=False)


@dataclass(frozen=True)
class LineDelta:
    """More of what `speaker` is saying, as the model writes it."""

    speaker: str
    text: str
    type: Literal["delta"] = field(default="delta", init=False)


@dataclass(frozen=True)
class TurnDone:
    """The lines the turn kept: the producer's, then each character's reply in the order
    they came. The turn succeeded."""

    messages: list[Message]
    type: Literal["done"] = field(default="done", init=False)


@dataclass(frozen=True)
class TurnFailed:
    """Why the turn failed, for the user to read; no line of it was kept."""

    message: str
    type: Literal["error"] = field(default="error", init=False)


TurnEvent = ProducerSaid | SpeakerUp | LineDelta | TurnDone | TurnFailed
"""A turn's events: `user`, then for each who replies `speaker` and her `delta`s, then
`done`, or `error` — the producer's words gone nowhere."""


@dataclass(frozen=True)
class ChatShown:
    """The user's chat as the timeline page takes it: its latest lines, its topic
    underway (None while none is), and whether anything was unread before this reading of
    it."""

    messages: list[Message]
    topic: Topic | None
    unread: bool


class GroupChat:
    """The users' group chats: the producer's turns in them, streamed as they are written,
    and the chat as it is read — over the lines and state of `chats`, every character of
    `characters` in the chat, on the deployer's chat model of `config` (their affinities
    read through `affinities`), each turn recorded in `activity`, `random` drawing who
    replies."""

    def __init__(
        self,
        chats: GroupChats,
        store: Store,
        characters: Mapping[str, Character],
        config: LiveConfig,
        affinities: Affinities,
        activity: ActivityLog,
        clock: Clock,
        random: Random,
        world: World | None = None,
        topics: "GroupTopics | None" = None,
    ) -> None:
        self.chats = chats
        self._store = store
        self._characters = characters
        self._config = config
        self._affinities = affinities
        self._activity = activity
        self._clock = clock
        self._random = random
        self._world = world
        self._topics = topics

    def require_on(self) -> None:
        """GroupChatOff unless the deployer has the group chat open."""
        if not self._config.group_chat.enabled:
            raise GroupChatOff()

    async def shown(self, user_id: str) -> ChatShown:
        """The user's chat as the timeline page takes it, the producer counted as reading
        it now; GroupChatOff while the deployer has it closed."""
        self.require_on()
        # What the characters have been saying among themselves is brought up to now
        # before it is read (group_topics), that the timeline the producer opens is the
        # chat as it stands — and what came with it unread.
        if self._topics is not None:
            await self._topics.catch_up(user_id)
        unread = await self.chats.unread(user_id)
        messages = await self.chats.timeline(user_id)
        topic = (await self.chats.state(user_id)).topic
        await self.chats.mark_read(user_id, self._clock())
        return ChatShown(messages, topic, unread)

    async def unread(self, user_id: str) -> bool:
        """Whether a character has said anything in the chat since the producer last read
        it, without reading it now; GroupChatOff while the deployer has it closed."""
        self.require_on()
        return await self.chats.unread(user_id)

    async def turn(self, user_id: str, text: str) -> AsyncIterator[TurnEvent]:
        """One turn of the producer in his chat: what he `text`ed, kept with the replies
        of whoever he @-names alone, or one or two drawn (`group_turns.pick_speakers`
        weighted, or uniformly, as the live configuration draws), each streamed as she
        speaks. A turn that fails part-way keeps none of its lines (TurnFailed); the chat
        counts as read, for the producer watched its replies."""
        self.require_on()
        text = text.strip()
        yield ProducerSaid(text)
        if not text or len(text) > MAX_INPUT_LENGTH:
            yield TurnFailed(TOO_LONG if text else BLANK)
            return
        lines = await self.chats.timeline(user_id, RECENT_LINES)
        profile = await self._store.get_profile(user_id)
        candidates = await self._candidates(user_id)
        if not candidates:
            yield TurnFailed(FAILED)
            return
        named = mentioned_in(text, candidates)
        responders = named or self._drawn(candidates, _spoken_among(lines))
        so_far = [*_labelled(lines, self._characters), ("制作人", text)]
        now = self._clock()
        recording = self._activity.begin("group", user_id, "", own_llm=False, exempt=False)
        lease = self._config.lease()
        said: list[tuple[str, str]] = []
        try:
            with recording.current():
                for each in responders:
                    yield SpeakerUp(
                        each.character.id, each.character.name, each.character.color
                    )
                    chunks: list[str] = []
                    async for chunk in lease.keys.chat_llm.stream(speaker_prompt(
                        SceneMaterial(
                            GROUP_SCENE,
                            [c for c in candidates if c is not each],
                            so_far,
                            _when(now, profile),
                            (
                                TO_HER.format(name=each.character.name, text=text)
                                if each in named else TO_ALL.format(text=text)
                            ),
                        ),
                        each, profile, self._world_prompt(each, profile, now),
                    )):
                        if isinstance(chunk, str):
                            chunks.append(chunk)
                            yield LineDelta(each.character.id, chunk)
                    line = "".join(chunks).strip()
                    if not line:
                        raise RuntimeError("the model wrote nothing")
                    said.append((each.character.id, line))
                    so_far.append((each.character.name, line))
            kept = [
                await self.chats.say(user_id, text, now),
                *[
                    await self.chats.say(user_id, line, now, speaker=speaker)
                    for speaker, line in said
                ],
            ]
            await self.chats.mark_read(user_id, now)
            await recording.finish("success")
        except Exception:
            # Not logged with what was raised: a service's error may repeat what it was asked.
            log.warning("a turn of user %s's group chat failed", user_id)
            await recording.finish("failed")
            yield TurnFailed(FAILED)
            return
        finally:
            lease.release()
        yield TurnDone(kept)

    async def _candidates(self, user_id: str) -> list[Candidate]:
        """Everyone the configuration has, as candidates to reply: their tiers of affinity
        with the producer (trust for everyone while affinity is off), and what their facts
        say of each of the others, read once here — never per turn, for the graph is heavy
        to walk."""
        party = list(self._characters.values())
        tiers: list[Tier] = (
            await self._affinities.tiers(user_id, [each.id for each in party])
            if self._affinities.on else ["trust"] * len(party)
        )
        return [
            Candidate(
                character, tier,
                relations(
                    character,
                    {id: each for id, each in self._characters.items() if id != character.id},
                ),
            )
            for character, tier in zip(party, tiers, strict=True)
        ]

    def _drawn(self, candidates: list[Candidate], spoken: Sequence[str]) -> list[Candidate]:
        """Who replies, drawn: one, or two, weighted as the engine draws or uniformly, as
        the live configuration draws."""
        count = 1 + self._random(2) if len(candidates) > 1 else 1
        if self._config.group_chat.speaker_mode == "relation_weighted":
            return pick_speakers(candidates, spoken, count, self._random)
        return _uniform(candidates, count, self._random)

    def _world_prompt(
        self, speaker: Candidate, profile: ProducerProfile, now: datetime
    ) -> str | None:
        """What the speaker's prompt carries of the world setting, if any."""
        if self._world is None:
            return None
        return self._world.prompt(
            speaker.character.name, local_date(now, effective_timezone(profile, None))
        )


def _prepare(db: sqlite3.Connection) -> None:
    db.executescript(Schema)


def _utc(at: datetime) -> str:
    """`at` as the tables keep times: in UTC, so that they compare as text."""
    return at.astimezone(UTC).isoformat()


def _line_of(
    db: sqlite3.Connection, user_id: str, kind: MessageKind, text: str,
    speaker: str | None, created_at: str,
) -> Message:
    """A line kept in the user's chat, as it comes back."""
    cursor = db.execute(
        "INSERT INTO group_messages (user_id, speaker, text, kind, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (user_id, speaker, text, kind, created_at),
    )
    assert cursor.lastrowid is not None
    return Message(
        cursor.lastrowid, user_id, speaker, kind, text, datetime.fromisoformat(created_at)
    )


def _say(
    db: sqlite3.Connection, user_id: str, text: str, speaker: str | None, created_at: str
) -> Message:
    kept = _line_of(db, user_id, "say", text, speaker, created_at)
    if speaker is not None:  # her line takes a turn of the topic underway, if one stands
        row = db.execute(
            "SELECT spoken FROM group_state WHERE user_id = ? AND opener IS NOT NULL",
            (user_id,),
        ).fetchone()
        if row is not None:
            db.execute(
                "UPDATE group_state SET spoken = ?, turns = turns + 1 WHERE user_id = ?",
                (json.dumps([*json.loads(row[0]), speaker]), user_id),
            )
    return kept


def _open_topic(
    db: sqlite3.Connection, user_id: str, opener: str, text: str, created_at: str
) -> Message:
    row = db.execute(
        "SELECT opener FROM group_state WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is not None and row[0] is not None:
        raise ValueError("上一个话题还没有收掉")
    kept = _line_of(db, user_id, "topic_open", text, opener, created_at)
    if row is None:
        db.execute(
            "INSERT INTO group_state (user_id, opener, spoken, turns) VALUES (?, ?, ?, 1)",
            (user_id, opener, json.dumps([opener])),
        )
    else:
        db.execute(
            "UPDATE group_state SET opener = ?, spoken = ?, turns = 1 WHERE user_id = ?",
            (opener, json.dumps([opener]), user_id),
        )
    return kept


def _end_topic(db: sqlite3.Connection, user_id: str, text: str, created_at: str) -> Message:
    row = db.execute(
        "SELECT opener FROM group_state WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is None or row[0] is None:
        raise ValueError("没有进行中的话题")
    kept = _line_of(db, user_id, "topic_end", text, None, created_at)
    db.execute(
        "UPDATE group_state SET opener = NULL, spoken = NULL, turns = NULL WHERE user_id = ?",
        (user_id,),
    )
    return kept


def _timeline(db: sqlite3.Connection, user_id: str, limit: int) -> list[Message]:
    return [
        Message(id, user, speaker, kind, text, datetime.fromisoformat(created_at))
        for id, user, speaker, kind, text, created_at in db.execute(
            "SELECT id, user_id, speaker, kind, text, created_at FROM group_messages"
            " WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
    ][::-1]


def _state(db: sqlite3.Connection, user_id: str) -> GroupState:
    row = db.execute(
        "SELECT opener, spoken, turns, read_at FROM group_state WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return GroupState(user_id, None, None)
    opener, spoken, turns, read_at = row
    return GroupState(
        user_id,
        None if opener is None else Topic(opener, tuple(json.loads(spoken)), turns),
        None if read_at is None else datetime.fromisoformat(read_at),
    )


def _mark_read(db: sqlite3.Connection, user_id: str, read_at: str) -> None:
    db.execute(
        "INSERT INTO group_state (user_id, read_at) VALUES (?, ?)"
        " ON CONFLICT(user_id) DO UPDATE SET read_at = excluded.read_at",
        (user_id, read_at),
    )


def _unread(db: sqlite3.Connection, user_id: str) -> bool:
    """Whether a character has said anything after the producer last read the chat — after
    the beginning, if he never has; his own lines are never unread, nor a topic's ending."""
    row = db.execute(
        "SELECT read_at FROM group_state WHERE user_id = ?", (user_id,)
    ).fetchone()
    read_at = row[0] if row is not None and row[0] is not None else ""
    return db.execute(
        "SELECT 1 FROM group_messages WHERE user_id = ? AND speaker IS NOT NULL"
        " AND created_at > ? LIMIT 1",
        (user_id, read_at),
    ).fetchone() is not None


def _topics_opened(db: sqlite3.Connection, user_id: str, since: str) -> int:
    [(count,)] = db.execute(
        "SELECT COUNT(*) FROM group_messages WHERE user_id = ? AND kind = 'topic_open'"
        " AND created_at >= ?",
        (user_id, since),
    ).fetchall()
    return count


def _uniform(
    candidates: Sequence[Candidate], count: int, random: Random
) -> list[Candidate]:
    """`count` of the `candidates`, drawn one at a time without replacement, everyone as
    likely as everyone else — the draw the live configuration has where it is not
    weighted."""
    remaining = list(candidates)
    picked: list[Candidate] = []
    while remaining and len(picked) < count:
        picked.append(remaining.pop(random(len(remaining))))
    return picked


def _spoken_among(lines: Sequence[Message]) -> list[str]:
    """Who of the characters has spoken already, over the latest lines, each once, latest
    first; what drawing who replies is weighted by."""
    return list(dict.fromkeys(reversed([
        line.speaker for line in lines[-SPOKEN_LINES:] if line.speaker is not None
    ])))


def _labelled(
    lines: Sequence[Message], characters: Mapping[str, Character]
) -> list[tuple[str, str]]:
    """The chat's latest lines as a prompt carries them, oldest first, each labelled with
    who it stands for: 制作人 for his, her name for a character's, a topic's ending for
    itself."""
    labelled = []
    for line in lines[-RECENT_LINES:]:
        if line.kind == "topic_end":
            labelled.append(("（话题结束）", line.text))
        elif line.speaker is None:
            labelled.append(("制作人", line.text))
        else:
            character = characters.get(line.speaker)
            labelled.append((character.name if character else line.speaker, line.text))
    return labelled


def _when(now: datetime, profile: ProducerProfile) -> str:
    """When and where the producer is, written out for a prompt."""
    zone = ZoneInfo(effective_timezone(profile, None))
    local = now.astimezone(zone)
    return f"{local:%m月%d日 %H:%M}（{zone}）"
