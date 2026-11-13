"""The outing catalog (GLOSSARY.md「外出」), loaded from the configuration beside the
characters'.

It is configuration, not data, as the gift catalog is: the maintainer keeps it in the
repository as they keep the characters, and neither `.env` nor the admin console changes it.
Each location has its identifier (also its header picture's file name in the frontend's
static files), its name, the scene it is written from (what the opening and the events are
written against, and what the characters arriving are told of where they are), the hint of
where it leans affinity, and which kinds of place of the place pool it counts as, so that a
character who likes those kinds is the more likely to be met there and the better for having
gone. Each location has its pool of events: what sets each off as the event card says it,
what the scene it makes is to be written from, and where it leans affinity.

Anything wrong in it keeps the backend from starting (`OutingCatalogError`)."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from eidolon.place_pool import CATEGORIES

OUTINGS_FILE = "outings.toml"
"""The file's name, in the directory of the character configuration."""

MIN_EVENTS = 1
"""The fewest events a location's pool may hold: an empty one would leave nothing to set
off."""

_VALID_ID = re.compile(r"[a-z0-9_-]+")


class OutingCatalogError(RuntimeError):
    """The outing catalog is missing or broken."""


@dataclass(frozen=True)
class OutingEvent:
    """One event of a location's pool (GLOSSARY.md「外出」): what sets it off, the scene it
    makes written from, and where it leans affinity."""

    id: str
    """Its identifier, unique in its location; what an outing's event messages keep."""
    trigger: str
    """What sets it off, one line, as the event card says it."""
    prompt: str
    """What the scene it makes is written from."""
    affinity: str
    """Where it leans affinity, one line, read when an outing that had it is settled."""


@dataclass(frozen=True)
class OutingLocation:
    """One place an outing is at (GLOSSARY.md「外出」): the scene it is written from, its pool
    of events, and where it leans affinity."""

    id: str
    name: str
    """Its everyday name, in Chinese."""
    scene: str
    """The place's setting, as the characters arriving and every scene written of it are
    told it."""
    affinity: str
    """Where it leans affinity, one line, read when an outing at it is settled."""
    place_categories: tuple[str, ...]
    """The kinds of place of the place pool (`place_pool.Category`) it counts as: who likes
    one of them (`Character.place_likes`) is the more likely to be met there."""
    events: tuple[OutingEvent, ...]
    """Its pool of events, in file order."""

    def event(self, id: str) -> OutingEvent | None:
        """The event `id` of its pool; None if there is none."""
        return next((e for e in self.events if e.id == id), None)


def outings_path(characters_path: Path) -> Path:
    """Where the outing catalog is: beside the character configuration."""
    return characters_path.parent / OUTINGS_FILE


def load_outing_catalog(path: Path) -> dict[str, OutingLocation]:
    """The locations in the catalog at `path`, keyed by identifier in file order. Raises
    OutingCatalogError if it is missing or broken."""
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise OutingCatalogError(f"找不到外出地点目录 {path}") from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise OutingCatalogError(f"外出地点目录 {path} 格式有误：{e}") from None
    entries = config.get("locations", [])
    if not isinstance(entries, list):
        raise OutingCatalogError(f"外出地点目录 {path} 里的 locations 应当是 [[locations]] 段")

    catalog: dict[str, OutingLocation] = {}
    for entry in entries:
        location = _parse_location(entry)
        if location.id in catalog:
            raise OutingCatalogError(f"外出地点标识 {location.id} 重复")
        catalog[location.id] = location
    return catalog


def _parse_location(entry: object) -> OutingLocation:
    if not isinstance(entry, dict):
        raise OutingCatalogError(f"外出地点目录里的 {entry!r} 应当是一个 [[locations]] 段")
    label = entry.get("id", "（没有标识）")
    if missing := [f for f in ("id", "name", "scene", "affinity") if f not in entry]:
        raise OutingCatalogError(f"外出地点 {label} 缺少 {'、'.join(missing)}")
    id = entry["id"]
    if not isinstance(id, str) or not _VALID_ID.fullmatch(id):
        raise OutingCatalogError(f"外出地点标识 {id} 只能用小写字母、数字、- 和 _")
    for field in ("name", "scene", "affinity"):
        value = entry[field]
        if not isinstance(value, str) or not value.strip():
            raise OutingCatalogError(f"外出地点 {id} 的 {field} 应当是一段文字")
    categories = entry.get("place_categories")
    if (
        not isinstance(categories, list) or not categories
        or not all(isinstance(c, str) for c in categories)
    ):
        raise OutingCatalogError(
            f"外出地点 {id} 的 place_categories 应当是地点池类别的列表，至少一个"
        )
    if unknown := [c for c in categories if c not in CATEGORIES]:
        raise OutingCatalogError(
            f"外出地点 {id} 的 place_categories 里的 {'、'.join(unknown)}"
            f" 不在地点池的 {'、'.join(CATEGORIES)} 之中"
        )
    listed = entry.get("events", [])
    if not isinstance(listed, list):
        raise OutingCatalogError(f"外出地点 {id} 的事件应当是 [[locations.events]] 段")
    events: dict[str, OutingEvent] = {}
    for item in listed:
        event = _parse_event(id, item)
        if event.id in events:
            raise OutingCatalogError(f"外出地点 {id} 的事件标识 {event.id} 重复")
        events[event.id] = event
    if len(events) < MIN_EVENTS:
        raise OutingCatalogError(
            f"外出地点 {id} 的事件池是空的，至少要有 {MIN_EVENTS} 件"
        )
    return OutingLocation(
        id, entry["name"], entry["scene"], entry["affinity"], tuple(categories),
        tuple(events.values()),
    )


def _parse_event(location: str, entry: object) -> OutingEvent:
    if not isinstance(entry, dict):
        raise OutingCatalogError(
            f"外出地点 {location} 的事件里的 {entry!r} 应当是一个 [[locations.events]] 段"
        )
    label = entry.get("id", "（没有标识）")
    if missing := [f for f in ("id", "trigger", "prompt", "affinity") if f not in entry]:
        raise OutingCatalogError(f"外出地点 {location} 的事件 {label} 缺少 {'、'.join(missing)}")
    id = entry["id"]
    if not isinstance(id, str) or not _VALID_ID.fullmatch(id):
        raise OutingCatalogError(
            f"外出地点 {location} 的事件标识 {id} 只能用小写字母、数字、- 和 _"
        )
    for field in ("trigger", "prompt", "affinity"):
        value = entry[field]
        if not isinstance(value, str) or not value.strip():
            raise OutingCatalogError(
                f"外出地点 {location} 的事件 {id} 的 {field} 应当是一段文字"
            )
    return OutingEvent(id, entry["trigger"], entry["prompt"], entry["affinity"])
