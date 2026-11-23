from datetime import datetime

import pytest

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.herosweb import HeroswebSitePolicy

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=JST)
ACTIVE_GRANT = "2099-11-22T12:00:00+09:00"


def _source(
    access_mode: str,
    *,
    available: bool = True,
    quota_started_at: str | None = "2026-11-21T12:00:00+09:00",
    access_granted_until: str | None = ACTIVE_GRANT,
) -> Source:
    return Source(
        id=1,
        item_id=1,
        site="herosweb",
        external_id="dca88b215773f:4fe9831c6f540",
        discovery_key="herosweb-test",
        access_mode=access_mode,
        free_until=None,
        available=available,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at=quota_started_at,
        access_granted_until=access_granted_until,
        published_at=None,
        created_at="2026-11-21T12:00:00+09:00",
        updated_at="2026-11-21T12:00:00+09:00",
        display_position=1,
    )


def test_policy_allows_only_available_free_as_direct_without_resource_state() -> None:
    policy = HeroswebSitePolicy()
    source = _source("free")
    prior_state = (source.quota_started_at, source.access_granted_until)

    decision = policy.evaluate(source, now=NOW, quota_available=0)

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        True,
        "direct",
        "free",
    )
    assert not decision.consumes_quota
    assert decision.quota_resource is None
    assert decision.quota_scope == "site"
    assert decision.quota_limit is None
    assert policy.batch_ordering() == "catalog"
    assert policy.supported_access_resources() == ()
    assert policy.ordered_access_resource_passes() == ()
    assert policy.grant_only_supported_access_resources() == ()
    assert policy.additional_access_resource_passes() == ()
    assert policy.defer_quota_access_to_grant_phase() is False
    assert (source.quota_started_at, source.access_granted_until) == prior_state


@pytest.mark.parametrize(
    ("access_mode", "reason"),
    [
        ("quota", "quota_not_supported"),
        ("paid", "paid_not_supported"),
        ("unknown", "unknown"),
        ("owned", "owned_not_supported"),
        ("rental", "rental_not_supported"),
        ("grant", "grant_not_supported"),
        ("future_mode", "unsupported_access_mode"),
    ],
)
def test_policy_rejects_every_nonfree_mode_even_with_stock_or_active_grant(
    access_mode: str, reason: str
) -> None:
    source = _source(access_mode)
    prior_state = (source.quota_started_at, source.access_granted_until)

    decision = HeroswebSitePolicy().evaluate(
        source,
        now=NOW,
        quota_available=100,
    )

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        False,
        None,
        reason,
    )
    assert not decision.consumes_quota
    assert decision.quota_resource is None
    assert (source.quota_started_at, source.access_granted_until) == prior_state


def test_policy_rejects_unavailable_free_without_mutating_grants() -> None:
    source = _source("free", available=False)
    prior_state = (source.quota_started_at, source.access_granted_until)

    decision = HeroswebSitePolicy().evaluate(source, now=NOW, quota_available=None)

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        False,
        None,
        "unavailable",
    )
    assert (source.quota_started_at, source.access_granted_until) == prior_state
