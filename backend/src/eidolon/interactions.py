"""Interaction actions (GLOSSARY.md「互动动作」): what the user does to her with a tap
rather than a sentence — a pat on the head, a hug, a snack handed over — each sent as a
turn of its own, she answering by her character as the action's scene says.

Every number and word of the catalog is here and only here. Each action names the tier
(`affinity.Tier`) it is meant for (`recommended_tier`): any action is offered at any tier,
but taken below its recommended one she takes it badly — she refuses, is embarrassed or
humours the producer — and it raises her affinity none, where at or above it she takes it
well. What an action would raise it by (`affinity_delta`) wears out as it is repeated:
each time the same action is taken among the conversation's latest turns, it raises by
half as much again less (`decay`), and she is told she has had enough of it for one day,
whatever her tier. These override what the judge model would make of the action's
narration alone, the judging of everything else about the turn unchanged: the step the
turn changes her affinity by is the action's own, worn out as it is; what would lower it
— out of line above all — is judged as ever.

What the chat model is told comes together in `turn_lines`: the action's scene, then how
she is to take it by her tier against its recommended one, then, worn out, that she has
had it too often today. The user's message is recorded marked with the action's id
(`Message.interaction_id`), its text the action's `acted` line, so the history can show
it as it happened; the action itself is never said to the judge model, retrieval or
memory beyond that line.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from eidolon.affinity import TIERS, Judged, Tier
from eidolon.store import Message

TIER_AT: dict[Tier, int] = {tier: at for at, (tier, _) in enumerate(TIERS)}
"""Where each tier stands, lowest first, that actions may be taken or not by it."""

WEARINESS_TURNS = 8
"""How many of the conversation's latest user messages the same action is counted over,
the turn being taken among them: long enough to wear it out for a while, short enough
that coming back another day starts it fresh."""

WEARINESS_DECAY = 0.5
"""How much of its `affinity_delta` an action raises by for each time it has been taken
already among the latest turns: half as much each time again."""

BELOW_STEP = 0.0
"""How much an action taken below its recommended tier raises her affinity: none, however
it would otherwise be judged; what would lower it is judged as ever."""


@dataclass(frozen=True)
class Interaction:
    """One action the user may take with her: its id, as turns and messages carry it; its
    Chinese name, as the menu shows it; the line that plays the action as the user's
    message (`acted`); the tier it is meant for; what it raises her affinity by, worn out
    as it is repeated; and the scene told the chat model."""

    id: str
    name: str
    emoji: str
    acted: str
    recommended_tier: Tier
    affinity_delta: float
    scene: str


CATALOG: tuple[Interaction, ...] = (
    Interaction(
        "pat_head", "摸摸头", "🤚", "（轻轻摸了摸她的头。）", "close", 0.3,
        "制作人轻轻摸了摸你的头。",
    ),
    Interaction(
        "hug", "拥抱", "🫂", "（轻轻抱了她一下。）", "close", 0.5,
        "制作人轻轻抱住了你。",
    ),
    Interaction(
        "kiss", "亲吻", "💋", "（在她额头上轻轻亲了一下。）", "intimate", 1.0,
        "制作人凑近你，轻轻亲了你一下。",
    ),
    Interaction(
        "hold_hands", "牵手", "🤝", "（轻轻牵起了她的手。）", "intimate", 0.6,
        "制作人轻轻牵起了你的手。",
    ),
    Interaction(
        "high_five", "击掌", "🙌", "（和她击了个掌。）", "trust", 0.2,
        "制作人笑着朝你伸出手，和你击了个掌。",
    ),
    Interaction(
        "poke_cheek", "戳脸颊", "👉", "（轻轻戳了戳她的脸颊。）", "close", 0.3,
        "制作人伸出手指，轻轻戳了戳你的脸颊。",
    ),
    Interaction(
        "snack", "递零食", "🍪", "（递给她一份小零食。）", "trust", 0.4,
        "制作人递给你一份小零食。",
    ),
    Interaction(
        "tidy_hair", "整理头发", "✨", "（伸手替她理了理头发。）", "intimate", 0.5,
        "制作人伸手替你理了理有些乱的头发。",
    ),
    Interaction(
        "tidy_collar", "整理衣领", "👔", "（替她整理了一下衣领。）", "intimate", 0.5,
        "制作人靠近你，替你整理了一下有些歪的衣领。",
    ),
)
"""Every action the user may take, in the order the menu shows them."""

BY_ID: dict[str, Interaction] = {i.id: i for i in CATALOG}


def reaches(interaction: Interaction, tier: Tier | None) -> Literal["below", "at", "above"]:
    """Where `tier` stands against the action's recommended one: below it, at it or above.
    Without a tier (affinity off), taken to be at it: she takes it as she is."""
    if tier is None:
        return "at"
    return (
        "below" if TIER_AT[tier] < TIER_AT[interaction.recommended_tier]
        else "above" if TIER_AT[tier] > TIER_AT[interaction.recommended_tier]
        else "at"
    )


_BELOW = (
    "你们现在还没有亲近到这一步：你不喜欢这样，会抗拒、躲开、尴尬或者敷衍地应付过去，"
    "按你自己的性格和口吻表现出来，不要因此变得讨好或说教。"
)
_AT_OR_ABOVE = (
    "你们已经亲近到可以做这样的事：你接受它，反应良好，按你自己的性格和口吻表现出来。"
)

_WORN_OUT = "这个动作今天你已经领过好几次了，你再这样就有点腻了：反应打折扣，可以小小的抱怨。"


def reaction_lines(interaction: Interaction, tier: Tier | None) -> list[str]:
    """How she is told to take the action, by where her `tier` stands against its
    recommended one."""
    return [_BELOW if reaches(interaction, tier) == "below" else _AT_OR_ABOVE]


def taken_before(interaction: Interaction, messages: Sequence[Message]) -> int:
    """How many times the same action has been taken among the conversation's latest user
    messages (`WEARINESS_TURNS` of them), the one being taken not among them yet."""
    said = [m for m in messages if m.role == "user"][-WEARINESS_TURNS:]
    return sum(m.interaction_id == interaction.id for m in said)


def weariness_lines(count: int) -> list[str]:
    """That she has had the action too often today, told her from the second time it
    repeats (`count` before this one)."""
    return [_WORN_OUT] if count >= 2 else []


def decay(count: int) -> float:
    """How much of an action's `affinity_delta` it raises by, taken `count` times already
    among the latest turns."""
    return WEARINESS_DECAY**count


def affinity_step(
    interaction: Interaction, tier: Tier | None, judged: Judged | None, count: int
) -> float | None:
    """How much the turn taking `interaction` changes her affinity by her `tier`, the same
    action taken `count` times already among the latest turns: in place of what the judge
    model made of the action's line alone (`judged`, None if it was not judged) — but only
    where the action would raise it; what would lower it, out of line above all, is judged
    as ever, and None leaves the judge's own step."""
    if judged is None or judged.out_of_line or judged.step + judged.considerate_step < 0:
        return None
    if reaches(interaction, tier) == "below":
        return BELOW_STEP
    return interaction.affinity_delta * decay(count)


def turn_lines(
    interaction: Interaction, tier: Tier | None, messages: Sequence[Message]
) -> list[str]:
    """What the chat model is told of the action the user takes, as the turn begins in
    `tier` (None with affinity off): its scene, how she takes it by her tier against its
    recommended one, and, worn out, that she has had it too often today. How many times
    it was taken before is counted over `messages` (`taken_before`)."""
    count = taken_before(interaction, messages)
    return [
        interaction.scene,
        *reaction_lines(interaction, tier),
        *weariness_lines(count),
    ]


def shown() -> list[dict]:
    """The catalog as the browser is told it, in the order the menu shows it: what each
    action is and the tier it is meant for, that the menu may say it too."""
    return [
        {
            "id": i.id,
            "name": i.name,
            "emoji": i.emoji,
            "recommended_tier": i.recommended_tier,
        }
        for i in CATALOG
    ]
