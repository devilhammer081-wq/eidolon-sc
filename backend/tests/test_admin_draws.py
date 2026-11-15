"""Draw chances an admin may give one user (GLOSSARY.md「抽奖」): a compensation that comes
on top of what the day has already brought, over the most kept each day, recorded as a
reward so the user sees new chances as they do any other. Gifts are to be open; the admin
console still shows no one's balance, backpack or affinity."""

from dataclasses import replace

import httpx
import pytest

from eidolon.config import Settings
from tests.conftest import ClientFactory
from tests.fakes import FAKE_JUDGE, START, FakeClock, FakeIdentityProvider, FakeLLM
from tests.test_admin_users import ADMIN, admin_client, find


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With an admin, the judge model, and affinity and gifts on in `.env`."""
    return replace(
        settings,
        admins=frozenset({ADMIN}),
        judge=FAKE_JUDGE,
        affinity_and_gifts=True,
    )


async def state(client: httpx.AsyncClient) -> dict:
    res = await client.get("/api/gifts")
    assert res.status_code == 200, res.text
    return res.json()


async def grant(admin: httpx.AsyncClient, user_id: str, count: int) -> httpx.Response:
    return await admin.post(f"/api/admin/users/{user_id}/draws", json={"count": count})


async def test_an_admin_gives_one_user_draws_and_the_user_sees_new_chances(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    clock = FakeClock()
    admin = await admin_client(make_client, github, clock=clock)
    producer = make_client(FakeLLM(), clock=clock)
    assert (await state(producer))["draws"] == 2
    producer_id = (await find(admin, "producer"))["id"]

    res = await grant(admin, producer_id, 3)

    assert res.status_code == 200, res.text
    assert res.json() == {"granted_at": START.isoformat(), "count": 3}
    seen = await state(producer)
    assert seen["draws"] == 5
    assert seen["rewarded_at"] == START.isoformat()


async def test_a_grant_comes_on_top_of_the_day_the_user_has_not_read_yet(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    admin = await admin_client(make_client, github)
    producer = make_client(FakeLLM(), clock=FakeClock())
    producer_id = (await find(admin, "producer"))["id"]

    assert (await grant(admin, producer_id, 3)).status_code == 200

    assert (await state(producer))["draws"] == 5  # the day's two, and the three given


async def test_draws_may_go_over_the_most_kept_each_day(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    admin = await admin_client(make_client, github)
    producer = make_client(FakeLLM(), clock=FakeClock())
    producer_id = (await find(admin, "producer"))["id"]

    assert (await grant(admin, producer_id, 10)).status_code == 200

    seen = await state(producer)
    assert (seen["draws"], seen["max_draws"]) == (12, 7)


async def test_giving_draws_is_refused_while_gifts_are_closed(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    admin = await admin_client(make_client, github)
    make_client(FakeLLM(), clock=FakeClock())
    producer_id = (await find(admin, "producer"))["id"]
    assert (await admin.put("/api/admin/config/affinity", json={"enabled": False})).status_code == 200

    refused = await grant(admin, producer_id, 1)

    assert refused.status_code == 409
    assert "礼物暂时没有开放" in refused.json()["detail"]


async def test_only_admins_may_give_draws(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    admin = await admin_client(make_client, github)
    producer = make_client(FakeLLM(), clock=FakeClock())
    producer_id = (await find(admin, "producer"))["id"]

    assert (await producer.post(f"/api/admin/users/{producer_id}/draws", json={"count": 1})).status_code == 404


async def test_the_count_is_bounded_and_the_user_must_exist(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    admin = await admin_client(make_client, github)
    make_client(FakeLLM(), clock=FakeClock())
    producer_id = (await find(admin, "producer"))["id"]

    assert (await grant(admin, producer_id, 0)).status_code == 422
    assert (await grant(admin, producer_id, 1001)).status_code == 422
    assert (await grant(admin, "nobody", 1)).status_code == 404
