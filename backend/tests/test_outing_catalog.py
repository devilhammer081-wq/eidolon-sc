"""The outing catalog (GLOSSARY.md「外出」) comes from configuration beside the characters':
the four locations of the first round with their scene, their affinity hint, the kinds of
place of the place pool they count as, and their pool of events; anything wrong in it is
caught as it is loaded."""

from pathlib import Path

import pytest

from eidolon.outing_catalog import (
    OUTINGS_FILE,
    OutingCatalogError,
    load_outing_catalog,
    outings_path,
)
from eidolon.place_pool import CATEGORIES
from tests.conftest import REPO_OUTINGS, CharacterConfig, ClientFactory
from tests.fakes import FakeLLM

FOUR = {"cinema": "电影院", "mall": "商场", "amusement-park": "游乐场", "seaside": "海边"}


def event(id: str = "an-event") -> str:
    return (
        f'[[locations.events]]\nid = "{id}"\ntrigger = "一句触发语"\n'
        'prompt = "LLM 场景提示"\naffinity = "好感倾向提示"\n'
    )


def location(
    id: str = "cinema",
    name: str = "电影院",
    scene: str = "灯暗下来后的余光和爆米花的甜味",
    affinity: str = "好感容易往上走",
    categories: str = '["mall"]',
    events: str = event(),
) -> str:
    entry = (
        f'[[locations]]\nid = "{id}"\nname = "{name}"\nscene = "{scene}"\n'
        f'affinity = "{affinity}"\nplace_categories = {categories}\n'
    )
    return entry + events


def written(tmp_path: Path, catalog: str) -> Path:
    path = tmp_path / OUTINGS_FILE
    path.write_text(catalog, encoding="utf-8")
    return path


def test_the_catalog_is_loaded_from_beside_the_character_configuration():
    assert outings_path(Path("characters/characters.toml")) == Path(
        f"characters/{OUTINGS_FILE}"
    )


def test_the_repository_catalog_holds_the_four_locations_of_the_first_round():
    catalog = load_outing_catalog(REPO_OUTINGS)

    assert {id: each.name for id, each in catalog.items()} == FOUR
    assert all(each.scene.strip() and each.affinity.strip() for each in catalog.values())


def test_every_location_holds_three_to_four_events():
    """The first round's pools, as the spec has them: enough to set off, not so many that
    the event cards run away with the page."""
    catalog = load_outing_catalog(REPO_OUTINGS)

    for each in catalog.values():
        assert 3 <= len(each.events) <= 4, each.id
        assert len({e.id for e in each.events}) == len(each.events)
        assert all(
            e.trigger.strip() and e.prompt.strip() and e.affinity.strip()
            for e in each.events
        )
        assert each.event(each.events[0].id) == each.events[0]
        assert each.event("no-such-event") is None


def test_the_locations_count_as_kinds_of_place_the_place_pool_names():
    """Who likes one of the kinds a location counts as (`place_likes`) is the more likely
    to be met there; a kind the place pool does not name would weigh no one."""
    catalog = load_outing_catalog(REPO_OUTINGS)

    for each in catalog.values():
        assert each.place_categories
        assert set(each.place_categories) <= set(CATEGORIES)
    assert catalog["seaside"].place_categories == ("seaside",)
    assert catalog["amusement-park"].place_categories == ("amusement",)


@pytest.mark.parametrize(
    ("catalog", "named"),
    [
        (location() + location(), "重复"),
        (location(id="Cinema"), "Cinema"),
        ('[[locations]]\nid = "cinema"\nname = "电影院"\naffinity = "好"'
         '\nplace_categories = ["mall"]\n' + event(), "scene"),
        (location(scene="  "), "scene"),
        (location(categories="[]"), "place_categories"),
        (location(categories='"mall"'), "place_categories"),
        (location(categories='["spa"]'), "spa"),
        (location(events='events = "no"\n'), "事件"),
        (location(events=""), "事件池"),
        ('locations = ["cinema"]\n', "locations"),
        ("[[locations]\n", OUTINGS_FILE),
    ],
)
def test_a_broken_catalog_is_not_loaded(catalog: str, named: str, tmp_path: Path):
    with pytest.raises(OutingCatalogError, match=named):
        load_outing_catalog(written(tmp_path, catalog))


@pytest.mark.parametrize(
    ("listed", "named"),
    [
        (event("An Event"), "An Event"),
        (event() + event(), "重复"),
        ('[[locations.events]]\nid = "an-event"\ntrigger = "触发语"\nprompt = "提示"\n', "缺少"),
        ('[[locations.events]]\nid = "an-event"\ntrigger = "  "\nprompt = "提示"\n'
         'affinity = "好"\n', "trigger"),
    ],
)
def test_a_broken_event_pool_is_not_loaded(listed: str, named: str, tmp_path: Path):
    with pytest.raises(OutingCatalogError, match=named):
        load_outing_catalog(written(tmp_path, location(events=listed)))


def test_a_missing_catalog_is_not_loaded(tmp_path: Path):
    with pytest.raises(OutingCatalogError, match=OUTINGS_FILE):
        load_outing_catalog(tmp_path / OUTINGS_FILE)


async def test_a_broken_catalog_keeps_the_backend_from_starting(
    make_client: ClientFactory, characters: CharacterConfig
):
    characters.write(OUTINGS_FILE, location() + location())

    with pytest.raises(RuntimeError, match="重复"):
        make_client(FakeLLM())


async def test_a_missing_catalog_keeps_the_backend_from_starting(
    make_client: ClientFactory, characters: CharacterConfig
):
    (characters.directory / OUTINGS_FILE).unlink()

    with pytest.raises(RuntimeError, match=OUTINGS_FILE):
        make_client(FakeLLM())
