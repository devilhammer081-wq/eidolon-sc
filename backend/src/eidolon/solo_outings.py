"""The producer's walks on his own (GLOSSARY.md「独自外出」) and the chance meetings they
end in (GLOSSARY.md「偶遇」): one walk at a time, each its own request.

A walk is at a location of the outing catalog — the one the request names, or one drawn
evenly from the catalog — and written on the deployer's chat model as text turns use it,
whoever's LLM the user brings, held only while it is (`LiveConfig.lease`): nothing counts
towards the user's limits. Its notes, one or two paragraphs in Chinese, are asked of the
model with no character at all, from the location's scene and who the producer is
(`outing_prompt.walk_notes_prompt`); what it writes is kept as the notes (`parse_walk_notes`),
nothing written at all failing the walk.

Whether the walk ends in a meeting is drawn before anything is asked of the model (the
draws: the location, unless the request names one; then the chance; then who is met), at the
chance the live configuration has (`LiveConfig.outings`): drawn evenly, 0 never meeting, 1
always. Who is met is drawn weighted: her tier of affinity with the producer, a place of
the location's kinds one she likes (`Character.place_likes` against its `place_categories`)
twice the chance, and a base everyone keeps so that no one is impossible — trust for
everyone while affinity is off, as the turn pipeline has it. Whoever it is, all of them may
be met, in a cooldown too: how likely she is already says it.

Her opening of the meeting is asked of the model as she would reply, from the scene and his
notes and her tier (`outing_prompt.encounter_prompt`), in her current conversation with him
— one opened for the meeting, in the conversation list from then on — and kept as her
reaching out is (`Store.add_reach_out`): seen from the conversation list, read aloud as her
words, and from there on the conversation is his and hers to go on with as any other, the
turn pipeline unchanged.

What the walk came to is kept by `outings.Outings`: the outing added at its opening, each
paragraph of its notes a line of it, and, a meeting drawn, one ending line with her as its
speaker — who was met — before it is ended at once. Every LLM the walk asked is asked
before any of that is written, so that a walk that fails leaves nothing behind; its record
(`outing`) says how it turned out, and names her as a turn's names the character, none for a
walk that met no one. The walk alone writes no memory and settles no affinity: the notes are
the producer's own, and the meeting is the conversation's, thereafter as any other."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from eidolon.activity import ActivityLog
from eidolon.affinity import Affinities, TIERS, Tier
from eidolon.characters import Character
from eidolon.clock import Clock
from eidolon.live_config import LiveConfig
from eidolon.moments import written_whole
from eidolon.outing_catalog import OutingLocation
from eidolon.outing_prompt import (
    EncounterMaterial,
    encounter_prompt,
    parse_walk_notes,
    walk_notes_prompt,
)
from eidolon.outings import Outing, Outings
from eidolon.producer import ProducerProfile, effective_timezone, local_date
from eidolon.randomness import Random
from eidolon.group_turns import AFFINITY_BASE
from eidolon.randomness import falls_in
from eidolon.reply_format import ReplyParser, Segment
from eidolon.store import Conversation, ReachOut, ReachOutRefused, Store
from eidolon.world import World

log = logging.getLogger(__name__)

LIKED_PLACE = 2
"""How many times the chance of her who likes a kind of place the location counts as, over
her who likes none of them."""
CHANCE_AT = 1_000_000
"""At how many places in [0, 1) the chance of a meeting is drawn."""


class NoLocation(LookupError):
    """The request names a location that is not in the outing catalog."""

    def __init__(self, location_id: str) -> None:
        super().__init__(f"没有这个外出地点：{location_id}")


class OutingFailed(RuntimeError):
    """The walk could not be written, the model failing or saying nothing; nothing was
    kept."""

    def __init__(self) -> None:
        super().__init__("这次外出没有成行，请稍后再试")


@dataclass(frozen=True)
class Met:
    """A meeting the walk ended in: who was met, the conversation her opening stands in,
    and that opening itself."""

    character: Character
    conversation: Conversation
    opening: ReachOut


@dataclass(frozen=True)
class SoloOuting:
    """The walk as it stands: the outing and its lines, where it was, its notes, and the
    meeting it ended in, None if none."""

    outing: Outing
    location: OutingLocation
    notes: tuple[str, ...]
    met: Met | None


class SoloOutings:
    """The users' walks on their own, in `outings`, at the locations of `catalog`, the
    characters of `characters` there to be met, on the deployer's chat model of `config`,
    each recorded in `activity`, `random` drawing where the walk is and whether and whom it
    meets."""

    def __init__(
        self,
        store: Store,
        outings: Outings,
        catalog: Mapping[str, OutingLocation],
        characters: Mapping[str, Character],
        config: LiveConfig,
        affinities: Affinities,
        activity: ActivityLog,
        clock: Clock,
        random: Random,
        world: World | None = None,
    ) -> None:
        self._store = store
        self._outings = outings
        self._catalog = catalog
        self._characters = characters
        self._config = config
        self._affinities = affinities
        self._activity = activity
        self._clock = clock
        self._random = random
        self._world = world

    async def walk(self, user_id: str, location_id: str | None = None) -> SoloOuting:
        """The producer's walk at `location_id`, or one drawn; None names no location. Every
        model asked of before anything is kept, so that a walk that fails (OutingFailed)
        leaves nothing behind; NoLocation if the catalog has no location `location_id`."""
        location = self._where(location_id)
        meeting = await self._meeting(user_id, location)
        now = self._clock()
        profile = await self._store.get_profile(user_id)
        recording = self._activity.begin(
            "outing", user_id, meeting[0].id if meeting else "", own_llm=False, exempt=False,
        )
        lease = self._config.lease()
        try:
            with recording.current():
                notes = parse_walk_notes(
                    await written_whole(
                        lease.keys.chat_llm.stream(walk_notes_prompt(location, profile))
                    )
                )
                opening: list[Segment] | None = None
                if not notes:
                    raise OutingFailed()
                if meeting is not None:
                    character, tier = meeting
                    opening = self._opening(await written_whole(
                        lease.keys.chat_llm.stream(encounter_prompt(
                            EncounterMaterial(
                                location, notes, now,
                                ZoneInfo(effective_timezone(profile, None)), tier,
                            ),
                            character, profile, self._world_prompt(character, profile, now),
                        ))
                    ))
                    if not opening:
                        raise OutingFailed()
        except Exception:
            # Not logged with what was raised: a service's error may repeat what it was asked.
            log.warning("the walk of user %s failed", user_id)
            await recording.finish("failed")
            raise OutingFailed() from None
        finally:
            lease.release()

        # The meeting is opened before anything of the walk is kept, that a walk it fails
        # to open (OutingFailed, the meeting refused) leaves nothing behind either — but
        # for the empty conversation it stands in, as any they began talking in instead.
        met: Met | None = None
        if meeting is not None and opening is not None:  # the try raised unless both or neither
            character, _ = meeting
            conversation = await self._store.create_conversation(user_id, character.id)
            try:
                said = await self._store.add_reach_out(conversation.id, opening, None, False)
            except ReachOutRefused:  # they began talking in another conversation meanwhile
                log.warning("the meeting of user %s could not be opened", user_id)
                await recording.finish("rejected")
                raise OutingFailed() from None
            met = Met(character, conversation, said)
        outing = await self._outings.add(user_id, "solo", location.id, (), now)
        for note in notes:
            await self._outings.message(user_id, outing.id, "opening", note, now)
        if met is not None:
            await self._outings.message(
                user_id, outing.id, "ending", f"在{location.name}偶遇了{met.character.name}。",
                now, speaker=met.character.id,
            )
        ended = await self._outings.end(user_id, outing.id, now)
        await recording.finish("success")
        if met is not None:
            await self._store.reach_out_recorded_as(met.opening.id, recording.row_id)
        return SoloOuting(ended, location, tuple(notes), met)

    def _where(self, location_id: str | None) -> OutingLocation:
        """The location the walk is at: the one named, or one drawn evenly from the
        catalog."""
        if location_id is not None:
            if (location := self._catalog.get(location_id)) is None:
                raise NoLocation(location_id)
            return location
        listed = list(self._catalog.values())
        return listed[self._random(len(listed))]

    async def _meeting(
        self, user_id: str, location: OutingLocation
    ) -> tuple[Character, Tier] | None:
        """Who the producer meets at `location`, with her tier of affinity with him, if
        anyone: the chance drawn first, then who, weighted by affinity and place likes;
        None if the chance is missed. The catalog is never empty, nor the roster, or the
        backend would not be."""
        chance = self._config.outings.encounter_chance
        if self._random(CHANCE_AT) >= chance * CHANCE_AT:
            return None
        listed = list(self._characters.values())
        if self._affinities.on:
            tiers = await self._affinities.tiers(user_id, [c.id for c in listed])
        else:
            tiers = [None] * len(listed)
        weights = [
            encounter_weight(tier, likes_the_place_of(character, location))
            for character, tier in zip(listed, tiers, strict=True)
        ]
        drawn = falls_in(weights, self._random(sum(weights)))
        return listed[drawn], tiers[drawn] or "trust"

    def _world_prompt(
        self, character: Character, profile: ProducerProfile, now: datetime
    ) -> str | None:
        """What every prompt of hers that day carries of the world setting, if any."""
        return (
            self._world.prompt(
                character.name, local_date(now, effective_timezone(profile, None))
            )
            if self._world else None
        )

    def _opening(self, written: str) -> list[Segment]:
        """Her opening from what the model wrote, its segments as it wrote them; empty if it
        said nothing she could."""
        parser = ReplyParser()
        parser.feed(written)
        parser.finish()
        return parser.complete


def encounter_weight(tier: Tier | None, likes: bool) -> int:
    """How many chances of being met a character has: her tier's start and everyone's base,
    doubled at a location that counts as a kind of place she likes (`likes`)."""
    start = int(dict(TIERS)[tier or "trust"])
    return (start + AFFINITY_BASE) * (LIKED_PLACE if likes else 1)


def likes_the_place_of(character: Character, location: OutingLocation) -> bool:
    """Whether one of the kinds of place the location counts as is one the character likes;
    false where she likes none configured."""
    return bool(
        character.place_likes and set(character.place_likes) & set(location.place_categories)
    )


