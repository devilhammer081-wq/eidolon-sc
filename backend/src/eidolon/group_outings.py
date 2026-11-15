"""Outings with company (GLOSSARY.md「外出」): the producer out with one to three
characters, on the multi-character turn engine (`group_turns`), and what such an outing
comes to when it ends.

It opens as the producer brings them somewhere: the model is asked once for the scene of
their arriving and a first line from each of them, as labelled lines, each kept under
whoever's name it carries; from then on the outing is under way. The producer talks or
acts to go on (`turn`): whoever he @-names replies alone, no one else drawn; otherwise
one or two of them are drawn weighted, as the engine draws (`group_turns.pick_speakers`),
and each replies as one speaker among several, seeing the lines so far and whoever spoke
before her, her reply streamed as it is written. A location event may be set off
(`happen`): its scene and the reactions of as many as are drawn are asked of the model
once, as labelled lines again, and kept as an event line carrying the event's identifier
in the catalog — what settling goes by — and the reaction lines under their names.

Ending (`end`) settles with each of them: the model is asked once for how the outing sat
with each — the location's and each event's affinity hints carried to it, whether she
likes the kinds of place it counts as, the lines of the outing — and each answer changes
her affinity as a turn's level does, through the affinity interface as it stands, the
day's limits and cooldowns and all. Whoever came along remembers it: one memory each,
hers by its source, saying who went where and what came of it, that all of the user's
characters share as memories are shared. Where affinity is off, nothing is judged and
nothing changes; the memory is kept all the same. Everything the model is asked is asked
before anything of the outing is kept, that what fails (OutingFailed) leaves nothing
behind — a turn that fails part-way leaves none of its lines either.

The engine, the draws and the speaker's prompt are the group chat's to take over
(`group_turns`); this is the outing's own: where they are, what its events are, and what
it comes to."""

import json
import logging
import sqlite3
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, TypeVar
from zoneinfo import ZoneInfo

from eidolon.activity import ActivityLog
from eidolon.affinity import (
    NO_EFFECT,
    Affinities,
    Change,
    Judged,
    Status,
    Tier,
    affinity_prompt,
)
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
    names_of,
    parse_labelled,
    pick_speakers,
    speaker_prompt,
)
from eidolon.llm import ChatMessage
from eidolon.live_config import LiveConfig
from eidolon.memory import MAX_MEMORY_LENGTH, Memory, Memories
from eidolon.moments import relations, written_whole
from eidolon.outing_catalog import OutingEvent, OutingLocation
from eidolon.outings import Message, Outing, OutingGone, Outings
from eidolon.producer import ProducerProfile, effective_timezone, local_date, producer_prompt
from eidolon.randomness import Random
from eidolon.solo_outings import NoLocation, likes_the_place_of
from eidolon.store import Store
from eidolon.today import her_birthday
from eidolon.world import World

log = logging.getLogger(__name__)

Asked = TypeVar("Asked")
"""What an ask of the model is read into, whatever kind of ask it was."""

RECENT_LINES = 16
"""How many of the outing's lines a prompt carries: the latest, that a prompt opens alike
from turn to turn."""

SPOKEN_LINES = 10
"""Over how many of the latest lines who has spoken already is read, for drawing who
replies."""

OPEN_FAILED = "这次外出没有成行，请稍后再试"
EVENT_FAILED = "这个事件没有触发成，请稍后再试"
SETTLE_FAILED = "这次外出没能结算，请稍后再试"
"""What the user reads when the model fails: nothing was kept, the outing stands as it
was, he may go on."""

GONE = "这次外出已经结束了"
"""What the user reads when the outing is not theirs to go on with: never was, not theirs,
or over."""

WENT_HOME = "大家一起回去了。"
"""The ending line where nothing is asked of the model, affinity off: the outing is over
all the same."""

TIERS_NAMED: dict[Tier, str] = {
    "cold": "冷淡", "distant": "疏远", "trust": "信任", "close": "亲近", "intimate": "亲密",
}
"""Each tier's everyday name, as the settlement is told of it."""


class NoCharacter(LookupError):
    """The request names a character that is not in the configuration."""

    def __init__(self, character_id: str) -> None:
        super().__init__(f"没有这个角色：{character_id}")


class NoEvent(LookupError):
    """The request names an event the outing's location has not."""

    def __init__(self, event_id: str) -> None:
        super().__init__(f"这个地点没有这个事件：{event_id}")


class BadCompany(ValueError):
    """The producer cannot bring that company: someone twice."""

    def __init__(self) -> None:
        super().__init__("同行的角色里有重复")


class OutingFailed(RuntimeError):
    """What was asked of the model for the outing could not be written; nothing of it was
    kept."""


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
class Started:
    """The outing as it stands once opened: under way, with the lines of its opening."""

    outing: Outing
    location: OutingLocation
    lines: list[Message]


@dataclass(frozen=True)
class Happened:
    """A location event, set off: the event of the catalog, and the lines it left — its
    scene as an event line, then the reactions of whoever was drawn."""

    event: OutingEvent
    outing: Outing
    location: OutingLocation
    lines: list[Message]


@dataclass(frozen=True)
class SettledEach:
    """What ending the outing came to for one of them: how her affinity changed (None for
    not at all), where it stands now, and the memory of it kept hers (None if she has it
    already)."""

    character: Character
    change: Change | None
    status: Status
    memory: Memory | None


@dataclass(frozen=True)
class Ended:
    """The outing over: its lines as they stand, and what it came to for each of them."""

    outing: Outing
    location: OutingLocation
    lines: list[Message]
    settled: list[SettledEach]


ARRIVED = "（制作人和{party}一起来到{name}，大家都到了。）"
"""Where the user's words would be as the opening is written."""

SET_OFF = "（「{trigger}」发生了。）"
"""Where the user's words would be as a location event is written."""

OPENING_RULES = """# 开场
制作人和几位偶像一起来到「这里的场景」写的地方，你替这个场景和她们写开场。
- 先写两三句这里的场景，不带任何人的名字，照着「这里的场景」写他们刚到时的动静。
- 然后为到场的每位偶像各写一句开口的话，一人一行，以「名字：」开头：照各自的人设和对制作人的态度，让她们说的第一句话各不相同，也可以互相搭话。
- 只写她们说的话，不写旁白，不替制作人说话；不发照片，也不提给谁发照片、打电话。"""
"""How the opening is written, in place of a turn's format."""

EVENT_RULES = """# 地点事件
「{trigger}」在「这里的场景」写的地方发生了。你替这一幕写场景，再写被点名的人的反应。
- 先写两三句事情发生的场景，不带任何人的名字，照着这件事的提示来写：{prompt}
- 然后为{reactors}各写一句反应，一人一行，以「名字：」开头，照各自的人设和现在的局面。
- 不替没被点名的人说话，也不替制作人说话；不发照片，也不提给谁发照片、打电话。"""
"""How a location event is written; {prompt} stands for the event's own prompt."""

SETTLE_RULES = """# 外出结算
制作人（就是和偶像们对话的用户）带几位偶像一起外出，现在结束了。你替这次外出结算每位同行偶像的好感变化。
- 站在她自己的立场，按「这次外出」的经过来判断：制作人的言行、她喜不喜欢这个地方、发生的事让她高兴还是不痛快。
- 「这个地方的倾向」和每件事的「好感倾向」是这一处、这件事的底色，照着它们偏。
- 五个档位：0 她明显不高兴或受伤；1 她有点不舒服；2 对她没有影响；3 她有点开心；4 她很开心、觉得被在意。拿不准时就是 2。
只输出 JSON，格式为 {{"characters": [{{"id": "……", "level": 0到4的整数}}]}}，每位同行的偶像都要有一条；再加一个 "ending" 字段，写一句这次外出收尾的旁白，给制作人看。"""
"""How the outing is settled, asked of the deployer's chat model."""


class GroupOutings:
    """The users' outings with company, in `outings`, at the locations of `catalog`, the
    characters of `characters` along, on the deployer's chat model of `config` (their
    affinities settled through `affinities`, what they remember kept in `memories` over
    `database`), each recorded in `activity`, `random` drawing who replies."""

    def __init__(
        self,
        database: Database,
        store: Store,
        outings: Outings,
        catalog: Mapping[str, OutingLocation],
        characters: Mapping[str, Character],
        config: LiveConfig,
        affinities: Affinities,
        memories: Memories,
        activity: ActivityLog,
        clock: Clock,
        random: Random,
        world: World | None = None,
    ) -> None:
        self._database = database
        self._store = store
        self._outings = outings
        self._catalog = catalog
        self._characters = characters
        self._config = config
        self._affinities = affinities
        self._memories = memories
        self._activity = activity
        self._clock = clock
        self._random = random
        self._world = world

    async def open(
        self, user_id: str, character_ids: Sequence[str], location_id: str
    ) -> Started:
        """The producer's outing with whoever `character_ids` name at `location_id`,
        opened: the scene of their arriving and each of their first lines kept, under way.
        The model is asked before anything is kept, that an outing that fails
        (OutingFailed) leaves nothing behind. NoLocation, NoCharacter or BadCompany if the
        request names none such."""
        location = self._at(location_id)
        if len(set(character_ids)) < len(character_ids):
            raise BadCompany()
        for character_id in character_ids:
            if character_id not in self._characters:
                raise NoCharacter(character_id)
        party = await self._candidates(user_id, character_ids)
        by_name = {
            name: each.character.id for each in party for name in names_of(each.character)
        }

        narration, said = await self._ask(
            user_id,
            opening_prompt(
                location, party, await self._store.get_profile(user_id)
            ),
            OPEN_FAILED,
            read_labelled(by_name),
        )
        now = self._clock()
        outing = await self._outings.add(
            user_id, "outing", location.id, tuple(each.character.id for each in party), now
        )
        if narration:
            await self._outings.message(
                user_id, outing.id, "opening", "\n".join(narration), now
            )
        for id, text in said:
            await self._outings.message(user_id, outing.id, "opening", text, now, speaker=id)
        begun = await self._outings.begin(user_id, outing.id)
        return Started(begun, location, await self._outings.messages(user_id, outing.id))

    async def turn(
        self, user_id: str, outing_id: int, text: str
    ) -> AsyncIterator[TurnEvent]:
        """One turn of the producer's outing under way: what he `text`ed, kept with the
        replies of whoever he @-names alone, or one or two drawn (`group_turns.
        pick_speakers`), each streamed as she speaks. A turn that fails part-way keeps
        none of its lines (TurnFailed); one whose outing is not theirs to go on with is
        told gone the same way."""
        text = text.strip()
        yield ProducerSaid(text)
        if not text or len(text) > MAX_INPUT_LENGTH:
            yield TurnFailed(TOO_LONG if text else BLANK)
            return
        standing = await self._standing(user_id, outing_id)
        if standing is None:
            yield TurnFailed(GONE)
            return
        outing, location, lines = standing
        profile = await self._store.get_profile(user_id)
        candidates = await self._candidates(user_id, outing.participants)
        if not candidates:
            yield TurnFailed(GONE)
            return
        named = mentioned_in(text, candidates)
        responders = named or self._drawn(candidates, _spoken_among(lines))
        so_far = [*_labelled(lines, self._characters), ("制作人", text)]
        now = self._clock()
        recording = self._activity.begin("outing", user_id, "", own_llm=False, exempt=False)
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
                            f"{location.name}。{location.scene}",
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
                        raise OutingFailed(FAILED)
                    said.append((each.character.id, line))
                    so_far.append((each.character.name, line))
            kept = [
                await self._outings.message(user_id, outing_id, "say", text, now),
                *[
                    await self._outings.message(
                        user_id, outing_id, "say", line, now, speaker=speaker
                    )
                    for speaker, line in said
                ],
            ]
            await recording.finish("success")
        except Exception:
            # Not logged with what was raised: a service's error may repeat what it was asked.
            log.warning("the turn of outing %s of user %s failed", outing_id, user_id)
            await recording.finish("failed")
            yield TurnFailed(FAILED)
            return
        finally:
            lease.release()
        yield TurnDone(kept)

    async def happen(self, user_id: str, outing_id: int, event_id: str) -> Happened:
        """The location's event `event_id` set off in the producer's outing under way: its
        scene and the reactions of as many as are drawn kept, the event line carrying the
        event's identifier. The model is asked before anything is kept (OutingFailed);
        OutingGone if the outing is not theirs to go on with, NoEvent if the location has
        no such event."""
        standing = await self._standing(user_id, outing_id)
        if standing is None:
            raise OutingGone()
        outing, location, lines = standing
        event = location.event(event_id)
        if event is None:
            raise NoEvent(event_id)
        candidates = await self._candidates(user_id, outing.participants)
        if not candidates:
            raise OutingGone()
        reactors = self._drawn(candidates, _spoken_among(lines))
        by_name = {
            name: each.character.id for each in reactors for name in names_of(each.character)
        }

        narration, said = await self._ask(
            user_id,
            event_prompt(
                location,
                event,
                reactors,
                [each for each in candidates if each not in reactors],
                _labelled(lines, self._characters),
                await self._store.get_profile(user_id),
            ),
            EVENT_FAILED,
            read_labelled(by_name),
        )
        now = self._clock()
        kept = [
            await self._outings.message(
                user_id,
                outing_id,
                "event",
                "\n".join(narration) if narration else event.trigger,
                now,
                event=event.id,
            ),
            *[
                await self._outings.message(
                    user_id, outing_id, "say", text, now, speaker=speaker
                )
                for speaker, text in said
            ],
        ]
        return Happened(event, outing, location, kept)

    async def end(self, user_id: str, outing_id: int) -> Ended:
        """The producer's outing over: each of them settled with (her affinity changed as
        the model judged the outing, through the affinity interface as it stands; nothing
        judged where affinity is off), the outing remembered by each who came along as a
        memory of hers, and one ending line. The model is asked before anything is kept
        (OutingFailed); OutingGone if the outing is not theirs to go on with."""
        standing = await self._standing(user_id, outing_id)
        if standing is None:
            raise OutingGone()
        outing, location, lines = standing
        party = [
            self._characters[id] for id in outing.participants if id in self._characters
        ]
        events = [
            event for event in (
                location.event(line.event)
                for line in lines
                if line.kind == "event" and line.event is not None
            ) if event is not None
        ]
        judged: dict[str, int] = {}
        ending = WENT_HOME
        if self._affinities.on and party:
            candidates = await self._candidates(user_id, outing.participants)

            def read(written: str) -> tuple[dict[str, int], str]:
                answer = parse_settlement(written)
                if answer is None:
                    raise ValueError("not the JSON asked for")
                return answer

            judged, ending = await self._ask(
                user_id,
                settle_prompt(location, events, candidates, _labelled(lines, self._characters)),
                SETTLE_FAILED,
                read,
            )
        now = self._clock()
        settled = await self._database.write(
            _settle, self._affinities, self._memories, user_id, party, judged, location,
            events, now, self._affinities.on,
        )
        self._memories.embed_carried(user_id)  # the memories kept, embedded in the background
        await self._outings.message(user_id, outing_id, "ending", ending, now)
        ended = await self._outings.end(user_id, outing_id, now)
        return Ended(ended, location, await self._outings.messages(user_id, outing_id), settled)

    async def _ask(
        self, user_id: str, prompt: list[ChatMessage], failure: str,
        read: Callable[[str], Asked],
    ) -> Asked:
        """What the deployer's chat model writes for `prompt`, as `read` turns it into
        what is kept, recorded as an outing of the user's; OutingFailed(`failure`),
        nothing kept, if the model fails or `read` says it wrote nothing worth keeping."""
        recording = self._activity.begin("outing", user_id, "", own_llm=False, exempt=False)
        lease = self._config.lease()
        try:
            with recording.current():
                written = read(await written_whole(lease.keys.chat_llm.stream(prompt)))
        except Exception:
            # Not logged with what was raised: a service's error may repeat what it was asked.
            log.warning("what the model wrote for an outing of user %s failed", user_id)
            await recording.finish("failed")
            raise OutingFailed(failure) from None
        finally:
            lease.release()
        await recording.finish("success")
        return written

    def _at(self, location_id: str) -> OutingLocation:
        """The location the request names; NoLocation if the catalog has it not."""
        if (location := self._catalog.get(location_id)) is None:
            raise NoLocation(location_id)
        return location

    async def _candidates(self, user_id: str, participants: Sequence[str]) -> list[Candidate]:
        """Whoever of the `participants` the configuration still has, as candidates to
        reply: their tiers of affinity with the producer (trust for everyone while
        affinity is off), and what their facts say of each of the others, read once here —
        never per turn, for the graph is heavy to walk."""
        party = [self._characters[id] for id in participants if id in self._characters]
        tiers: list[Tier] = (
            await self._affinities.tiers(user_id, [each.id for each in party])
            if self._affinities.on else ["trust"] * len(party)
        )
        others = {each.id: each for each in party}
        return [
            Candidate(
                character, tier,
                relations(
                    character,
                    {id: each for id, each in others.items() if id != character.id},
                ),
            )
            for character, tier in zip(party, tiers, strict=True)
        ]

    def _drawn(self, candidates: list[Candidate], spoken: Sequence[str]) -> list[Candidate]:
        """Who replies, drawn: one, or as many as the live configuration allows and there
        are of them, weighted as the engine draws."""
        most = min(self._config.outings.responders_max, len(candidates))
        count = 1 + self._random(most) if most > 1 else 1
        return pick_speakers(candidates, spoken, count, self._random)

    async def _standing(
        self, user_id: str, outing_id: int
    ) -> tuple[Outing, OutingLocation, list[Message]] | None:
        """The user's outing with company, under way, at a location the catalog still has,
        with its lines; None if there is no such outing of theirs to go on with."""
        outing = await self._outings.outing(user_id, outing_id)
        if outing is None or outing.kind != "outing" or outing.status == "ended":
            return None
        location = self._catalog.get(outing.location_id)
        if location is None:
            return None
        return outing, location, await self._outings.messages(user_id, outing_id)

    def _world_prompt(
        self, speaker: Candidate, profile: ProducerProfile, now: datetime
    ) -> str | None:
        """What the speaker's prompt carries of the world setting, if any."""
        if self._world is None:
            return None
        return self._world.prompt(
            speaker.character.name, local_date(now, effective_timezone(profile, None))
        )


def _settle(
    db: sqlite3.Connection,
    affinities: Affinities,
    memories: Memories,
    user_id: str,
    party: Sequence[Character],
    judged: Mapping[str, int],
    location: OutingLocation,
    events: Sequence[OutingEvent],
    now: datetime,
    affinity_on: bool,
) -> list[SettledEach]:
    """What the outing comes to for each of the `party`, in one transaction: her affinity
    changed as she was judged (a level she was not, no effect; nothing settled where
    affinity is off), and the outing remembered as a memory of hers — kept all the same
    whether affinity is on or not."""
    settled = []
    for character in party:
        memory = memories.remember(
            db, user_id, character.id, _memory_text(character, party, location, events), now
        )
        if affinity_on:
            change, status = affinities.change(
                db, user_id, character.id, Judged(level=judged.get(character.id, NO_EFFECT))
            )
            settled.append(SettledEach(character, change, status, memory))
    return settled


def _memory_text(
    character: Character,
    party: Sequence[Character],
    location: OutingLocation,
    events: Sequence[OutingEvent],
) -> str:
    """What the outing is remembered as, by one who came along: who went where, and what
    came of it — her own name first, that the memory is hers."""
    along = [character.name, *(each.name for each in party if each.id != character.id)]
    text = f"制作人和{'、'.join(along)}一起去了{location.name}"
    if events:
        text += f"，碰上了{'、'.join(event.trigger for event in events)}"
    return f"{text}。"[:MAX_MEMORY_LENGTH]


def read_labelled(by_name: Mapping[str, str]) -> Callable[[str], tuple[list[str], list[tuple[str, str]]]]:
    """A reader of what the model wrote as labelled lines by those `by_name` names, and
    that it wrote something worth keeping — a scene or a word of anyone's, else nothing
    is (`_ask` fails the turn on it)."""

    def read(written: str) -> tuple[list[str], list[tuple[str, str]]]:
        labelled = parse_labelled(written, by_name)
        if not any(labelled):
            raise ValueError("nothing worth keeping")
        return labelled

    return read


def _spoken_among(lines: Sequence[Message]) -> list[str]:
    """Who of the characters has spoken already, over the latest lines, each once, latest
    first; what drawing who replies is weighted by."""
    return list(dict.fromkeys(reversed([
        line.speaker for line in lines[-SPOKEN_LINES:] if line.speaker is not None
    ])))


def _labelled(
    lines: Sequence[Message], characters: Mapping[str, Character]
) -> list[tuple[str, str]]:
    """The outing's latest lines as a prompt carries them, oldest first, each labelled
    with who it stands for: 制作人 for his, her name for a character's, an event's for
    itself."""
    labelled = []
    for line in lines[-RECENT_LINES:]:
        if line.kind == "event":
            labelled.append(("（地点事件）", line.text))
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


def parse_settlement(written: str) -> tuple[dict[str, int], str] | None:
    """The settlement in what the model wrote: each character's level and the ending
    line; None if it is not the JSON asked for. A character left out, or judged off the
    levels, is left to no effect; no ending line is the empty one."""
    start, end = written.find("{"), written.rfind("}")
    try:
        answer = json.loads(written[start : end + 1]) if start >= 0 else None
    except ValueError:
        return None
    if not isinstance(answer, dict) or not isinstance(answer.get("characters"), list):
        return None
    levels: dict[str, int] = {}
    for each in answer["characters"]:
        if not isinstance(each, dict):
            continue
        id, level = each.get("id"), each.get("level")
        if isinstance(id, str) and type(level) is int and 0 <= level <= 4:
            levels[id] = level
    ending = answer.get("ending")
    return levels, ending if isinstance(ending, str) and ending.strip() else ""


def opening_prompt(
    location: OutingLocation, party: Sequence[Candidate], profile: ProducerProfile
) -> list[ChatMessage]:
    """The prompt the outing's opening is written with: the sheets of everyone along and
    how each stands with the producer, who he is, the place and who is there, and how the
    opening is written; where the user's words would be, that they have all arrived."""
    return [
        ChatMessage("system", producer_prompt(profile)),
        ChatMessage("system", "\n\n".join([
            "\n".join([
                f"## {each.character.name}",
                each.character.sheet,
                her_birthday(each.character),
                *(f"她对制作人的态度：{line}" for line in affinity_prompt(each.tier, None)),
            ])
            for each in party
        ])),
        ChatMessage(
            "system",
            "\n\n".join([
                f"# 这里的场景\n{location.name}。{location.scene}",
                "\n".join([
                    "# 在场的人",
                    *[
                        f"- {each.character.name}（{each.character.intro}）" for each in party
                    ],
                ]),
                OPENING_RULES,
            ]),
        ),
        ChatMessage(
            "user",
            ARRIVED.format(
                party="、".join(each.character.name for each in party), name=location.name
            ),
        ),
    ]


def event_prompt(
    location: OutingLocation,
    event: OutingEvent,
    reactors: Sequence[Candidate],
    watching: Sequence[Candidate],
    lines: Sequence[tuple[str, str]],
    profile: ProducerProfile,
) -> list[ChatMessage]:
    """The prompt a location event is written with: the sheets of whoever reacts, who he
    is, the place, who is there and what has been said, and how the event is written;
    where the user's words would be, that it has happened. `watching` are along but not
    reacting, told to the scene as such."""
    return [
        ChatMessage("system", producer_prompt(profile)),
        ChatMessage("system", "\n\n".join([
            "\n".join([
                f"## {each.character.name}",
                each.character.sheet,
                her_birthday(each.character),
                *(f"她对制作人的态度：{line}" for line in affinity_prompt(each.tier, None)),
            ])
            for each in reactors
        ])),
        ChatMessage(
            "system",
            "\n\n".join([
                f"# 这里的场景\n{location.name}。{location.scene}",
                "\n".join([
                    "# 在场的人",
                    *[
                        f"- {each.character.name}（{each.character.intro}）"
                        + ("（这次不说话）" if each in watching else "")
                        for each in [*reactors, *watching]
                    ],
                ]),
                "\n".join(["# 到现在为止", *[f"{who}：{text}" for who, text in lines]]),
                EVENT_RULES.format(
                    trigger=event.trigger,
                    prompt=event.prompt,
                    reactors="、".join(each.character.name for each in reactors),
                ),
            ]),
        ),
        ChatMessage("user", SET_OFF.format(trigger=event.trigger)),
    ]


def settle_prompt(
    location: OutingLocation,
    events: Sequence[OutingEvent],
    party: Sequence[Candidate],
    lines: Sequence[tuple[str, str]],
) -> list[ChatMessage]:
    """The prompt the outing is settled with: the rules, then the outing itself — its
    location and where it leans affinity, what happened at it and what was said — and
    each of the party by her id, her liking of the place and her tier."""
    happened = (
        "\n".join(f"- {event.trigger}：{event.affinity}" for event in events)
        if events else "（没有触发过地点事件）"
    )
    return [
        ChatMessage("system", SETTLE_RULES),
        ChatMessage(
            "user",
            "\n".join([
                "# 这次外出",
                f"地点：{location.name}。这个地方的倾向：{location.affinity}",
                f"发生的事件：\n{happened}",
                "\n".join(["经过：", *[f"{who}：{text}" for who, text in lines]]),
                "# 同行的偶像",
                *[
                    f"- {each.character.id}（{each.character.name}）："
                    + (
                        "这个地点算她喜欢的那类地方"
                        if likes_the_place_of(each.character, location)
                        else "不是她特别喜欢的那类地方"
                    )
                    + f"；与制作人现在的关系：{TIERS_NAMED[each.tier]}"
                    for each in party
                ],
            ]),
        ),
    ]
