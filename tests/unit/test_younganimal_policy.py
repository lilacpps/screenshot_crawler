from datetime import datetime

import pytest

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.base import SitePolicyError
from screenshot_crawler.site_policies.younganimal import YounganimalSitePolicy

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=JST)


def _source(
    access_mode: str,
    *,
    available: bool = True,
    quota_started_at: str | None = None,
    access_granted_until: str | None = None,
) -> Source:
    return Source(
        id=1,
        item_id=1,
        site="younganimal",
        external_id="aee4fa742b0fe:55889b8a851cb",
        discovery_key="younganimal-test",
        access_mode=access_mode,
        free_until=None,
        available=available,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at=quota_started_at,
        access_granted_until=access_granted_until,
        published_at=None,
        created_at="2026-10-10T12:00:00+09:00",
        updated_at="2026-10-10T12:00:00+09:00",
        display_position=4,
    )


def test_younganimal_policy_allows_only_available_free_directly() -> None:
    policy = YounganimalSitePolicy()
    source = _source("free")

    decision = policy.evaluate(source, now=NOW, quota_available=0)

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        True,
        "direct",
        "free",
    )
    assert decision.consumes_quota is False
    assert decision.quota_resource is None
    assert source.quota_started_at is None
    assert source.access_granted_until is None
    assert policy.available_quota((source,), NOW) is None
    assert policy.supported_access_resources() == ()
    assert policy.grant_only_supported_access_resources() == ()


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("unknown", "unknown"),
        ("paid", "paid"),
        ("owned", "owned_not_verified"),
        ("grant", "grant_not_supported"),
        ("rental", "rental_not_supported"),
        ("quota", "quota_not_supported"),
    ],
)
def test_younganimal_policy_rejects_nonfree_modes_without_grant_shortcuts(
    mode: str, reason: str
) -> None:
    policy = YounganimalSitePolicy()
    source = _source(
        mode,
        quota_started_at="2026-10-10T12:00:00+09:00",
        access_granted_until="2099-10-11T12:00:00+09:00",
    )

    decision = policy.evaluate(source, now=NOW, quota_available=100)

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        False,
        None,
        reason,
    )
    assert decision.consumes_quota is False
    assert decision.quota_resource is None
    assert source.quota_started_at == "2026-10-10T12:00:00+09:00"
    assert source.access_granted_until == "2099-10-11T12:00:00+09:00"


def test_younganimal_policy_rejects_unavailable_free_and_has_no_resource_paths() -> None:
    policy = YounganimalSitePolicy()
    decision = policy.evaluate(_source("free", available=False), now=NOW, quota_available=None)

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        False,
        None,
        "unavailable",
    )
    with pytest.raises(SitePolicyError, match="Unsupported access resource"):
        policy.validate_access_resource("work_ticket")
    with pytest.raises(SitePolicyError, match="Grant-only access resource is not implemented"):
        policy.validate_grant_only_resource("work_ticket")
