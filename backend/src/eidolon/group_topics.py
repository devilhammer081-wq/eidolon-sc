"""The topic scheduler of the 283 office's group chat (GLOSSARY.md「群聊」): who opens a
topic, and who carries it on — the producer out of it, the characters among themselves.

Progress is lazy: nothing runs in the background. Whenever the producer's chat is read
(`GroupChat.shown`, over `catch_up`), the scheduler brings the chat up to now — the topic
underway carried on by as many turns as its spacing says should have come, a new topic
opened where none stands, the day's quota (`topics_per_day`) not spent and the last topic
old enough — each line asked of the deployer's chat model as one speaker among several
(`group_turns.speaker_prompt`), the speaker drawn as the live configuration has the chat
draw: uniformly, or weighted by affinity with the producer and by her relations to whoever
has spoken already; whoever spoke last does not speak again right after herself. A topic
ends at its `max_turns`, closed by a quiet line; a model that fails or writes nothing ends
the catch-up quietly, keeping what was kept, for the next reading to take up again. Days
are Beijing days, as the daily quotas of the rest of the site are."""

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta, timezone

from eidolon.activity import ActivityLog
from eidolon.affinity import Affinities
from eidolon.characters import Character
from eidolon.clock import Clock
from eidolon.live_config import LiveConfig
from eidolon.group_chat import (
    GROUP_SCENE,
    RECENT_LINES,
    GroupChats,
    Message,
    Topic,
    _labelled,
    _spoken_among,
    _when,
)
from eidolon.group_turns import (
    Candidate,
    SceneMaterial,
    speaker_prompt,
    speaker_weight,
)
from eidolon.moments import relations
from eidolon.randomness import Random, falls_in
from eidolon.producer import ProducerProfile, effective_timezone, local_date
from eidolon.store import Store
from eidolon.world import World

log = logging.getLogger(__name__)

BEIJING = timezone(timedelta(hours=8))
"""The zone the daily quotas of the site go by, by its fixed offset."""

TOPIC_GAP = timedelta(hours=4)
"""How long after a topic's opening the next may stand: the day's topics spread out."""
FOLLOW_SPACING = timedelta(minutes=8)
"""How far apart the topic's turns come, left to themselves."""
CATCH_UP_AT_MOST = 4
"""How many turns one reading of the chat brings the topic on by, at the most: the rest
waits for the next reading, that the producer not come back to a flood."""

LOW_TIERS = ("cold", "distant")
"""The tiers a speaker is told she may be short in: not close to the producer, her replies
may be perfunctory."""

OPEN_A_TOPIC = (
    "你在283事务所的群里开一个新话题：从你今天在意的事、最近的日常或正在忙的事里挑一件，"
    "用一两句自然的话起头，像真人发群消息，不要带旁白。"
)
CARRY_ON = (
    "接着群里正在聊的话题说一句：像真人接话，一句话就好，可以回应刚才说话的人，"
    "不要带旁白。"
)
NOT_CLOSE = "你和制作人还不熟：可以简短敷衍地接一句，或者只淡淡回一句。"
WENT_QUIET = "这个话题聊得差不多了，群里安静了下来。"


class GroupTopics:
    """Every user's chat brought up to now, one reading at a time: the chat's own lines and
    state written through `chats`, the speakers drawn by `random` as the live configuration
    has the chat draw, each line asked of the deployer's chat model of `config` over their
    affinities with the producer (`affinities`), every ask recorded in `activity`."""

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

    async def catch_up(self, user_id: str) -> None:
        """The user's chat brought up to now: the topic underway carried on, or a new one
        opened where the day still has room for it. What the model cannot write is left for
        the next reading; nothing is raised to the reader."""
        if not self._config.group_chat.enabled:
            return
        now = self._clock()
        state = await self.chats.state(user_id)
        lines = await self.chats.timeline(user_id, RECENT_LINES)
        if state.topic is not None:
            await self._carry_on(user_id, state.topic, lines, now)
        else:
            await self._maybe_open(user_id, lines, now)

    async def _maybe_open(
        self, user_id: str, lines: Sequence[Message], now: datetime
    ) -> None:
        """A new topic opened where the day has room for it and the last has had its gap;
        nothing where it has not."""
        settings = self._config.group_chat
        if await self.chats.topics_opened(user_id, _day_started(now)) >= settings.topics_per_day:
            return
        last_opened = next(
            (line.created_at for line in reversed(lines) if line.kind == "topic_open"),
            None,
        )
        if last_opened is not None and now - last_opened < TOPIC_GAP:
            return
        candidates = await self._candidates(user_id)
        if not candidates:
            return
        opener = self._drawn(candidates, [])
        line = await self._ask(user_id, opener, candidates, lines, now, OPEN_A_TOPIC)
        if line is not None:
            await self.chats.open_topic(user_id, opener.character.id, line, now)

    async def _carry_on(
        self, user_id: str, topic: Topic, lines: Sequence[Message], now: datetime
    ) -> None:
        """The topic underway carried on by as many turns as its spacing says should have
        come by `now` (`FOLLOW_SPACING` apart), to its `max_turns` at the most, whereupon it
        is closed by a quiet line."""
        settings = self._config.group_chat
        last_at = lines[-1].created_at if lines else now
        turns = min(
            max(int((now - last_at) / FOLLOW_SPACING), 0),
            settings.max_turns - topic.turns,
            CATCH_UP_AT_MOST,
        )
        candidates = await self._candidates(user_id)
        spoken_among = _spoken_among(lines)
        for _ in range(turns):
            # Whoever spoke last does not speak again right after herself.
            eligible = [each for each in candidates if each.character.id != topic.spoken[-1]]
            if not eligible:
                break
            speaker = (
                self._drawn(eligible, spoken_among) if len(eligible) > 1 else eligible[0]
            )
            line = await self._ask(user_id, speaker, candidates, lines, now, CARRY_ON)
            if line is None:
                break
            lines = [*lines, await self.chats.say(
                user_id, line, now, speaker=speaker.character.id
            )]
            topic = Topic(topic.opener, (*topic.spoken, speaker.character.id), topic.turns + 1)
            spoken_among = _spoken_among(lines)
        if topic.turns >= settings.max_turns:
            await self.chats.end_topic(user_id, WENT_QUIET, now)

    async def _candidates(self, user_id: str) -> list[Candidate]:
        """Everyone the configuration has, as the producer's turns have them: their tiers
        of affinity with the producer (trust for everyone while affinity is off), their
        relations read once here, never per turn, for the graph is heavy to walk."""
        party = list(self._characters.values())
        tiers = await self._affinities.tiers(user_id, [each.id for each in party])
        others = {each.id: each for each in party}
        return [
            Candidate(
                character, tier,
                relations(
                    character, {id: each for id, each in others.items() if id != character.id},
                ),
            )
            for character, tier in zip(party, tiers, strict=True)
        ]

    def _drawn(self, candidates: Sequence[Candidate], spoken: Sequence[str]) -> Candidate:
        """One of the `candidates` drawn as the live configuration has the chat draw:
        weighted by affinity and relations (`speaker_weight`), or uniformly."""
        if self._config.group_chat.speaker_mode == "random":
            return candidates[self._random(len(candidates))]
        weights = [speaker_weight(each, spoken) for each in candidates]
        return candidates[falls_in(weights, self._random(sum(weights)))]

    async def _ask(
        self,
        user_id: str,
        speaker: Candidate,
        candidates: Sequence[Candidate],
        lines: Sequence[Message],
        now: datetime,
        directive: str,
    ) -> str | None:
        """The speaker's line asked of the deployer's chat model — one speaker among
        several, told to carry on as `directive` says, short where she is not close to the
        producer — or None, the ask recorded as failed, where the model fails or writes
        nothing."""
        profile = await self._store.get_profile(user_id)
        prompt = speaker_prompt(
            SceneMaterial(
                GROUP_SCENE,
                [each for each in candidates if each is not speaker],
                _labelled(lines, self._characters),
                _when(now, profile),
                (
                    f"{directive}（{NOT_CLOSE}）" if speaker.tier in LOW_TIERS else directive
                ),
            ),
            speaker, profile, self._world_prompt(speaker, profile, now),
        )
        recording = self._activity.begin("group", user_id, "", own_llm=False, exempt=False)
        lease = self._config.lease()
        try:
            with recording.current():
                written = ""
                async for chunk in lease.keys.chat_llm.stream(prompt):
                    if isinstance(chunk, str):
                        written += chunk
        except Exception:
            log.warning("a topic line of user %s's group chat failed", user_id)
            await recording.finish("failed")
            return None
        finally:
            lease.release()
        await recording.finish("success")
        line = written.strip()
        return line or None


    def _world_prompt(
        self, speaker: Candidate, profile: ProducerProfile, now: datetime
    ) -> str | None:
        """What the speaker's prompt carries of the world setting, if any."""
        if self._world is None:
            return None
        return self._world.prompt(
            speaker.character.name, local_date(now, effective_timezone(profile, None))
        )


def _day_started(now: datetime) -> str:
    """Where the Beijing day `now` falls in began, as the tables keep times: in UTC, that
    the day's quota of topics may be counted from it."""
    beijing = now.astimezone(BEIJING).replace(hour=0, minute=0, second=0, microsecond=0)
    return beijing.astimezone(UTC).isoformat()
