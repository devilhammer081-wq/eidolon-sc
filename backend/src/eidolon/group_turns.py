"""The multi-character turn engine: who of several characters replies, and the prompt each
one's reply is written from (GLOSSARY.md「外出」).

A conversation with several characters is not several conversations had at once: whoever
speaks, the others are there, and who replies next is drawn — the producer's words answered
by one or two of them, whoever he @-names alone. The engine is a seam (the group chat of
the 283 office is to take it over as it stands): it knows how to pick who replies, how to
read an @-mention, and how to lay out the prompt of one speaker among several. It knows
nothing of where they are or why: whoever uses it brings the scene (an outing's location,
a chat's setting), the lines so far, and the candidates, each with her tier of affinity
with the producer and what her facts say of the other characters there — a snapshot read
once beforehand (`moments.relations`), never per turn, for the graph is heavy to walk.

Who replies is drawn weighted: her tier of affinity with the producer (the tier's start,
as the encounter's draw has it) plus everyone's base, so that no one is impossible however
cold, plus a step for each character already in the exchange her facts say she knows —
those two are likelier to get talking. Each drawn speaker joins the spoken, the next drawn
against her: two who know each other are likelier both to reply. Whoever the producer
@-names is not drawn at all: they alone reply, the mention read from his words by her name
or short name (`mentioned_in`).

Each reply is asked of the model as one speaker, not as all of them at once: her sheet and
the world setting as every prompt of hers has them, who the producer is, then where they
are and who is there — the others by name and intro, and what her facts say of each — the
lines so far labelled by who said them, and how she speaks to the producer in her tier.
The model writes plain Chinese, no subtitles and no voice: an outing's lines are not read
aloud, and are kept as text. What several speakers are asked to write together at once —
a scene, everyone's first words — they write as labelled lines instead
(`parse_labelled`), each kept under whoever's name it carries."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from eidolon.affinity import TIERS, Tier, affinity_prompt
from eidolon.characters import Character
from eidolon.llm import ChatMessage
from eidolon.producer import ProducerProfile, producer_prompt
from eidolon.randomness import Random, falls_in
from eidolon.today import always_known

AFFINITY_BASE = 10
"""How much of a chance to reply is everyone's before affinity: no one left out of the
conversation, however cold."""
RELATION_STEP = 20
"""How much more of a chance to reply one has for each character already in the exchange
her facts say she knows: friends of the speaker are likelier to get talking."""
LABEL = "："
"""What separates a speaker's name from her words in a labelled line."""


@dataclass(frozen=True)
class Candidate:
    """One who may reply: her character, her tier of affinity with the producer (trust
    where affinity is off, as the turn pipeline has it), and what her facts say of each of
    the other characters by id (`moments.relations`), read beforehand."""

    character: Character
    tier: Tier
    related: Mapping[str, str]


def pick_speakers(
    candidates: Sequence[Candidate], spoken: Sequence[str], count: int, random: Random
) -> list[Candidate]:
    """`count` of the `candidates`, drawn one at a time without replacement, each weighted
    by her affinity with the producer and by her relations to whoever has spoken already —
    `spoken`, grown by each one drawn. Fewer, should there be no more to draw; none leaves
    them as they came, in their order."""
    remaining = list(candidates)
    picked: list[Candidate] = []
    while remaining and len(picked) < count:
        weights = [speaker_weight(each, spoken) for each in remaining]
        drawn = falls_in(weights, random(sum(weights)))
        picked.append(remaining.pop(drawn))
        spoken = (*spoken, picked[-1].character.id)
    return picked


def speaker_weight(candidate: Candidate, spoken: Sequence[str]) -> int:
    """How many chances of being drawn to reply `candidate` has: her tier's start and
    everyone's base, and a relation step for each character in `spoken` her facts say she
    knows."""
    start = int(dict(TIERS)[candidate.tier])
    known = sum(1 for id in spoken if id in candidate.related)
    return start + AFFINITY_BASE + known * RELATION_STEP


def mentioned_in(text: str, candidates: Sequence[Candidate]) -> list[Candidate]:
    """Those of the `candidates` the producer @-names in `text`, in the order their
    mentions stand there, by her name or short name: @真乃 as @櫻木真乃. None named, none;
    whoever is named replies alone (`pick_speakers` is not asked)."""
    named: list[tuple[int, Candidate]] = []
    for each in candidates:
        where = [
            at for name in names_of(each.character) if (at := text.find(f"@{name}")) >= 0
        ]
        if where:
            named.append((min(where), each))
    return [each for _, each in sorted(named, key=lambda named: named[0])]


def names_of(character: Character) -> tuple[str, ...]:
    """The names an @-mention may call her by."""
    return (character.short_name, character.name) if character.short_name else (character.name,)


def parse_labelled(
    written: str, by_name: Mapping[str, str]
) -> tuple[list[str], list[tuple[str, str]]]:
    """The labelled lines of what the model wrote for several at once: the narration —
    lines no name carries — and each character's lines as (character id, text), in the
    order written, however many lines she has joined into one. `by_name` maps every name a
    line may be labelled with to who said it. Blank space goes nowhere; so does a name no
    one there carries."""
    narration: list[str] = []
    said: dict[str, list[str]] = {}
    for line in written.splitlines():
        line = line.strip()
        if not line:
            continue
        who, sep, words = line.partition(LABEL)
        if sep and (id := by_name.get(who.strip())):
            said.setdefault(id, []).append(words.strip())
        else:
            narration.append(line)
    return narration, [(id, " ".join(lines)) for id, lines in said.items()]


@dataclass(frozen=True)
class SceneMaterial:
    """What the prompt of one speaker among several is written from, read beforehand:
    where they are, who else is there (each a `Candidate`, herself left out), the lines so
    far, when and where the producer is, and her occasion — how she comes to be speaking,
    standing where the user's words would."""

    scene: str
    """Where they are, written out: an outing location's name and its scene."""
    others: Sequence[Candidate]
    lines: Sequence[tuple[str, str]]
    """The lines so far, oldest first, each labelled with who it stands for in the prompt:
    制作人 for his, her name for a character's, something of its own for an event's."""
    now: str
    """When and where the producer is, written out, e.g. 11月13日 18:32（Asia/Tokyo）."""
    occasion: str
    """How she comes to be speaking, where the user's words would be, without the time:
    e.g. 制作人对大家说：「……」，你也接一句."""


SPEAKING_RULES = """# 怎么接话
在场的不止你一个人，但这条只写你一个人说的话。
- 用中文写一两句当场开口那么长的话，别把话说满，给别人留接话的空。
- 可以接制作人的话，也可以接之前说话的人的话，点名找她说话也行。
- 只写你自己说的话，不替制作人、也不替其他在场的谁说话；不写旁白和场景描写。
- 不发照片，也不提给谁发照片、打电话。"""
"""How one of several speaks, told her last."""


def speaker_prompt(
    material: SceneMaterial, speaker: Candidate, profile: ProducerProfile, world_prompt: str | None
) -> list[ChatMessage]:
    """The prompt `speaker`'s reply is written from, from `material`: her sheet and the
    world setting as every prompt of hers has them, who the producer is, then where they
    are and who is there, the lines so far, how she speaks to the producer in her tier, and
    how she is to speak among several (`SPEAKING_RULES`); where the user's words would be,
    her occasion, after the time."""
    told = [f"# 这里的场景\n{material.scene}"]
    if material.others:
        told.append("\n".join(["# 在场的其他人", *[
            f"- {each.character.name}（{each.character.intro}）"
            + (f"：{fact}" if (fact := speaker.related.get(each.character.id)) else "")
            for each in material.others
        ]]))
    told.append("\n".join(["# 到现在为止", *[
        f"{who}{LABEL}{text}" for who, text in material.lines
    ]]))
    shared = [*always_known(speaker.character, world_prompt)]
    return [
        ChatMessage("system", "\n\n".join(shared), cache_breakpoint=True),
        ChatMessage("system", producer_prompt(profile)),
        ChatMessage(
            "system",
            "\n\n".join([*told, *affinity_prompt(speaker.tier, None), SPEAKING_RULES]),
        ),
        ChatMessage("user", f"（{material.now}）{material.occasion}"),
    ]
