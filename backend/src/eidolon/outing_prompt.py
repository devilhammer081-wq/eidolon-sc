"""What a solo outing is written from (GLOSSARY.md「独自外出」「偶遇」), and what is read of
what the model writes: from material put together beforehand, reading nothing, so that the
solo pipeline and the tests take the same prompt and the same parser.

The producer's walk notes are asked of the chat model with no character at all: the
location's scene from the outing catalog, who the producer is, and how to write one or two
paragraphs of what he sees and hears, in Chinese, for him alone to read. The model is told
nothing of the characters, and may not put anyone in his way — whom he meets is not the
writer's to say, but the encounter's to draw (`solo_outings`). What it writes is read as
paragraphs split on blank lines (`parse_walk_notes`): the first two, none if it wrote
nothing, and a paragraph's own line breaks are its, not new paragraphs.

Whom the producer met opens the encounter as she would reply (`encounter_prompt`): her
character sheet and the world setting as every turn has them, word for word, the turn's
format as an unvoiced reply's; who the producer is; then, in a system message of its own,
the place they met at and its scene, what his walk came to (his notes, as they will be
shown to him), what time it is where he is, how she speaks to him in her tier
(`affinity.affinity_prompt`), and how to open (`ENCOUNTER_RULES`); and where the user's
words would be, that they have run into each other and she means to speak first
(`MET_HIM`). No history — they have not spoken here yet — and nothing else retrieved: what
follows is the conversation's own turn pipeline."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from eidolon.affinity import Tier, affinity_prompt
from eidolon.characters import Character
from eidolon.llm import ChatMessage
from eidolon.outing_catalog import OutingLocation
from eidolon.producer import ProducerProfile, producer_prompt
from eidolon.reply_format import format_instructions
from eidolon.today import always_known

MAX_WALK_PARAGRAPHS = 2
"""The most paragraphs the walk notes are: one or two, whatever the model wrote."""

WALK_RULES = """# 散步见闻
制作人一个人到「这里的场景」写的地方散步，你替他把这一路看到、听到的写成记录，给他自己看。
- 用中文写一到两段，每段两三句，两段加起来一百二十字以内。
- 只写这个地方当天会有的动静，照着「这里的场景」来写；可以有一两句周围来来往往的人的群像，但不安排具体的人和制作人说话。
- 不写制作人的心情和想法，也不替他决定接下来去哪、买什么；只写见闻。
- 段与段之间空一行。除了这两段见闻，不要输出任何别的文字。"""
"""How the walk notes are written, in place of a turn's format."""

WALKING = "（制作人走进这个地方，一个人慢慢走。）"
"""Where the user's words would be as the walk is written."""

SCENE = "# 这里的场景"
HIS_WALK = "# 他这一路"
WHAT_TIME = "# 现在的时间"
MET_HIM = "（制作人一个人在这里散步，和你撞了个照面。你想先跟他说话。）"
"""Where the user's words would be as she opens the encounter."""

ENCOUNTER_RULES = """# 偶遇开场
制作人一个人出来散步，正好走到你也在的地方，你们撞了个照面，由你先开口。
- 顺着「他这一路」里写的见闻打招呼：他刚走过什么，你就着什么开口。
- 想想你为什么会在这里，照你的人设和日程来（下班路过、买东西、散步都行），第一句话里自然带出来，不用专门解释。
- 写一到两段，别把话说满，给他留接话的空。
- 不发照片，也不说要给他发照片、要给他打电话。"""
"""How she is to open the encounter, told her last."""


@dataclass(frozen=True)
class EncounterMaterial:
    """What her opening is written from, read beforehand: where they met and its scene, his
    walk notes as he will see them, when and where he is, and her tier."""

    location: OutingLocation
    notes: Sequence[str]
    now: datetime
    zone: ZoneInfo
    tier: Tier
    """Her tier where affinity is off: trust, as the turn pipeline has it."""


def walk_notes_prompt(location: OutingLocation, profile: ProducerProfile) -> list[ChatMessage]:
    """The prompt the producer's walk notes at `location` are written with, from who he is
    in `profile`."""
    return [
        ChatMessage(
            "system",
            "\n\n".join([f"{SCENE}\n{location.scene}", producer_prompt(profile), WALK_RULES]),
        ),
        ChatMessage("user", WALKING),
    ]


def parse_walk_notes(written: str) -> list[str]:
    """The paragraphs of what the model wrote for the walk: each split from the next by a
    blank line, its own line breaks kept inside it; the first `MAX_WALK_PARAGRAPHS`, none if
    it wrote nothing but white space."""
    paragraphs = [
        paragraph.strip() for paragraph in written.split("\n\n") if paragraph.strip()
    ]
    return paragraphs[:MAX_WALK_PARAGRAPHS]


def encounter_prompt(
    material: EncounterMaterial, character: Character, profile: ProducerProfile,
    world_prompt: str | None,
) -> list[ChatMessage]:
    """The prompt the character the producer met opens with, from `material`: her sheet in
    `character`, who he is in `profile`."""
    local = material.now.astimezone(material.zone)
    told = [
        f"{SCENE}\n{material.location.name}。{material.location.scene}",
        "\n".join([HIS_WALK, *(f"- {note}" for note in material.notes)]),
        f"{WHAT_TIME}\n{local:%m月%d日 %H:%M}（{material.zone}）",
        *affinity_prompt(material.tier, None),
        ENCOUNTER_RULES,
    ]
    shared = [*always_known(character, world_prompt), format_instructions(None)]
    return [
        ChatMessage("system", "\n\n".join(shared), cache_breakpoint=True),
        ChatMessage("system", producer_prompt(profile)),
        ChatMessage("system", "\n\n".join(told)),
        ChatMessage("user", MET_HIM),
    ]
