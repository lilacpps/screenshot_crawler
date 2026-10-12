from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.base import SitePolicyError
from screenshot_crawler.site_policies.kadocomi import KadocomiSitePolicy

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=JST)
WORK_ID = "KC_004915_S"
EPISODE_ID = "KC_0049150000400011_E"


def _source(
    *,
    site: str = "kadocomi",
    access_mode: str = "free",
    available: bool = True,
    external_id: str = f"{WORK_ID}:{EPISODE_ID}",
    free_until: datetime | str | None = None,
) -> Source:
    return Source(
        id=1,
        item_id=1,
        site=site,
        external_id=external_id,
        discovery_key="kadocomi-test",
        access_mode=access_mode,
        free_until=free_until,
        available=available,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at=None,
        access_granted_until=None,
        published_at=None,
        created_at="2026-10-12T12:00:00+09:00",
        updated_at="2026-10-12T12:00:00+09:00",
        display_position=None,
    )


@pytest.mark.parametrize(
    "free_until",
    [None, NOW + timedelta(seconds=1), "2026-10-12T12:00:01+09:00"],
    ids=("no-deadline-observation", "future-datetime", "future-iso-timestamp"),
)
def test_kadocomi_policy_allows_only_valid_available_free_direct_sources(
    free_until: datetime | str | None,
) -> None:
    source = _source(free_until=free_until)

    decision = KadocomiSitePolicy().evaluate(
        source, now=NOW, quota_available=99
    )

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        True,
        "direct",
        "free",
    )
    assert decision.consumes_quota is False
    assert decision.quota_resource is None
    assert KadocomiSitePolicy().supported_access_resources() == ()
    assert KadocomiSitePolicy().grant_only_supported_access_resources() == ()
    assert source.free_until == free_until


@pytest.mark.parametrize(
    "free_until",
    [
        NOW - timedelta(seconds=1),
        NOW,
        "not-a-timestamp",
        "2026-10-12T12:00:01",
        datetime(2026, 10, 12, 12, 0, 1),  # noqa: DTZ001 - exercise naive Catalog value
        "2026-10-12",
    ],
    ids=("past", "equal-now", "malformed", "naive-iso", "naive-datetime", "date-only"),
)
def test_kadocomi_policy_rejects_expired_or_unverifiable_free_until(
    free_until: datetime | str,
) -> None:
    decision = KadocomiSitePolicy().evaluate(
        _source(free_until=free_until), now=NOW, quota_available=None
    )

    assert decision.eligible is False
    assert decision.access_strategy is None
    expected_reason = (
        "expired_free"
        if free_until in {NOW, NOW - timedelta(seconds=1)}
        else "invalid_free_until"
    )
    assert decision.reason == expected_reason


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (_source(available=False), "unavailable"),
        (_source(site="comicdays"), "wrong_site"),
        (_source(access_mode="unknown"), "unknown"),
        (_source(access_mode="quota"), "quota_not_supported"),
        (_source(access_mode="paid"), "paid"),
        (_source(access_mode="owned"), "owned_not_verified"),
        (_source(access_mode="grant"), "grant_not_supported"),
        (_source(access_mode="rental"), "rental_not_supported"),
        (_source(external_id=f"{WORK_ID}:KC_0049160000400011_E"), "invalid_episode_identity"),
        (_source(external_id=f"{WORK_ID}:{EPISODE_ID}:duplicate"), "invalid_episode_identity"),
    ],
)
def test_kadocomi_policy_rejects_unsafe_catalog_states(
    source: Source,
    reason: str,
) -> None:
    decision = KadocomiSitePolicy().evaluate(source, now=NOW, quota_available=None)

    assert decision.eligible is False
    assert decision.access_strategy is None
    assert decision.reason == reason
    assert decision.consumes_quota is False


def test_kadocomi_policy_requires_aware_now_and_rejects_resource_flows() -> None:
    policy = KadocomiSitePolicy()

    with pytest.raises(SitePolicyError, match="now must be timezone-aware"):
        policy.evaluate(
            _source(),
            now=datetime(2026, 10, 12, 12, 0),  # noqa: DTZ001 - exercise rejected naive clock
            quota_available=None,
        )
    with pytest.raises(SitePolicyError, match="Unsupported access resource"):
        policy.validate_access_resource("ticket")
    with pytest.raises(SitePolicyError, match="Grant-only access resource is not implemented"):
        policy.validate_grant_only_resource("ticket")
