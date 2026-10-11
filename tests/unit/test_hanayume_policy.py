from datetime import datetime

import pytest

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.base import SitePolicyError
from screenshot_crawler.site_policies.hanayume import HanayumeSitePolicy

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=JST)


def _source(
    access_mode: str,
    *,
    available: bool = True,
    grant_until: str | None = None,
) -> Source:
    return Source(
        id=1,
        item_id=1,
        site="hanayume",
        external_id="1f9f5b0d4cd52:8c6f15923caa0",
        discovery_key="hanayume-test",
        access_mode=access_mode,
        free_until=None,
        available=available,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at="2026-10-10T12:00:00+09:00" if grant_until else None,
        access_granted_until=grant_until,
        published_at=None,
        created_at="2026-10-10T12:00:00+09:00",
        updated_at="2026-10-10T12:00:00+09:00",
        display_position=4,
    )


def test_hanayume_policy_allows_only_available_free_directly() -> None:
    policy = HanayumeSitePolicy()
    source = _source("free")

    decision = policy.evaluate(source, now=NOW, quota_available=0)

    assert decision.eligible is True
    assert decision.access_strategy == "direct"
    assert decision.reason == "free"
    assert decision.consumes_quota is False
    assert decision.quota_resource is None
    assert source.quota_started_at is None
    assert source.access_granted_until is None
    assert policy.supported_access_resources() == ()
    assert policy.grant_only_supported_access_resources() == ()


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("unknown", "unknown"),
        ("quota", "quota_not_supported"),
        ("paid", "paid"),
        ("owned", "owned_not_verified"),
        ("grant", "grant_not_supported"),
        ("rental", "rental_not_supported"),
    ],
)
def test_hanayume_policy_rejects_nonfree_modes_even_with_active_grants(
    mode: str, reason: str
) -> None:
    policy = HanayumeSitePolicy()
    source = _source(mode, grant_until="2099-10-11T12:00:00+09:00")

    decision = policy.evaluate(source, now=NOW, quota_available=100)

    assert decision.eligible is False
    assert decision.access_strategy is None
    assert decision.reason == reason
    assert decision.consumes_quota is False
    assert source.quota_started_at == "2026-10-10T12:00:00+09:00"
    assert source.access_granted_until == "2099-10-11T12:00:00+09:00"


def test_hanayume_policy_rejects_unavailable_free_and_unknown_resource_paths() -> None:
    policy = HanayumeSitePolicy()
    decision = policy.evaluate(_source("free", available=False), now=NOW, quota_available=None)
    assert (decision.eligible, decision.reason) == (False, "unavailable")

    with pytest.raises(SitePolicyError, match="Unsupported access resource"):
        policy.validate_access_resource("work_ticket")
    with pytest.raises(SitePolicyError, match="Grant-only access resource is not implemented"):
        policy.validate_grant_only_resource("work_ticket")
