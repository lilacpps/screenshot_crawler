from datetime import datetime, timedelta

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
    assert policy.supported_access_resources() == ("work_ticket",)
    assert policy.ordered_access_resource_passes() == ("work_ticket",)
    assert policy.grant_only_supported_access_resources() == ("work_ticket",)
    assert policy.resource_state_scope("work_ticket") == "work"
    assert policy.defer_quota_access_to_grant_phase() is False


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("unknown", "unknown"),
        ("quota", "work_ticket_candidate"),
        ("owned", "owned_not_verified"),
        ("grant", "grant_not_supported"),
        ("rental", "rental_not_supported"),
    ],
)
def test_hanayume_policy_rejects_nonfree_modes_even_with_active_grants(
    mode: str, reason: str
) -> None:
    policy = HanayumeSitePolicy()
    source = _source(
        mode,
        grant_until=None if mode == "quota" else "2099-10-11T12:00:00+09:00",
    )

    decision = policy.evaluate(source, now=NOW, quota_available=100)

    if mode == "quota":
        assert decision.eligible is True
        assert decision.access_strategy == "quota"
        assert decision.consumes_quota is True
        assert decision.quota_resource == "work_ticket"
        assert decision.quota_scope == "work" and decision.quota_limit == 1
        assert decision.quota_commit_mode == "after_observed_consumption"
    else:
        assert decision.eligible is False
        assert decision.access_strategy is None
        assert decision.reason == reason
        assert decision.consumes_quota is False
    assert source.quota_started_at == (
        None if mode == "quota" else "2026-10-10T12:00:00+09:00"
    )
    assert source.access_granted_until == (
        None if mode == "quota" else "2099-10-11T12:00:00+09:00"
    )


def test_hanayume_policy_active_grant_direct_and_work_ticket_expiry() -> None:
    policy = HanayumeSitePolicy()
    active = _source("quota", grant_until="2026-10-11T13:00:00+09:00")
    decision = policy.evaluate(active, now=NOW, quota_available=0)
    assert decision.eligible and decision.access_strategy == "direct"
    assert decision.reason == "active_work_ticket_grant"
    assert not decision.consumes_quota
    assert policy.access_grant_until(NOW).isoformat() == "2026-10-14T12:00:00+09:00"

    boundary = _source("quota", grant_until=NOW.isoformat())
    expired = policy.evaluate(boundary, now=NOW, quota_available=None)
    assert expired.eligible and expired.access_strategy == "quota"


@pytest.mark.parametrize("remaining_hours", [None, -1, 0, 1, 288])
def test_hanayume_premium_rental_is_direct_only_before_display_expiry(remaining_hours) -> None:
    expiry = NOW + timedelta(hours=remaining_hours) if remaining_hours is not None else None
    decision = HanayumeSitePolicy().evaluate(
        _source("paid", grant_until=expiry.isoformat() if expiry else None),
        now=NOW, quota_available=100,
    )
    active = remaining_hours is not None and remaining_hours > 0
    assert decision.eligible is active
    assert decision.access_strategy == ("direct" if active else None)
    assert not decision.consumes_quota and decision.quota_resource is None
    assert decision.reason == (
        "active_rental" if active else "paid" if remaining_hours is None else "expired_rental"
    )


def test_hanayume_policy_rejects_unavailable_free_and_unknown_resource_paths() -> None:
    policy = HanayumeSitePolicy()
    decision = policy.evaluate(_source("free", available=False), now=NOW, quota_available=None)
    assert (decision.eligible, decision.reason) == (False, "unavailable")

    policy.validate_access_resource("work_ticket")
    policy.validate_grant_only_resource("work_ticket")
    with pytest.raises(SitePolicyError, match="Unsupported access resource"):
        policy.validate_access_resource("premium_ticket")


@pytest.mark.parametrize("cooldown_hours", [None, 1, 22, 23])
def test_hanayume_grant_only_uses_at_least_the_23_hour_work_cooldown(
    cooldown_hours: int | None,
) -> None:
    policy = HanayumeSitePolicy()
    consumed = datetime(2026, 10, 11, 0, 0, tzinfo=JST)
    retry_at = policy.grant_only_retry_at(
        resource="work_ticket",
        last_consumed_at=consumed,
        cooldown_hours=cooldown_hours,
    )
    assert retry_at == consumed.replace(hour=23)
    assert policy.grant_only_skip_reason(
        resource="work_ticket",
        last_consumed_at=consumed,
        now=retry_at - timedelta(seconds=1),
        cooldown_hours=cooldown_hours,
    ) == "work_ticket_cooldown"
    assert policy.grant_only_skip_reason(
        resource="work_ticket",
        last_consumed_at=consumed,
        now=retry_at,
        cooldown_hours=cooldown_hours,
    ) is None


@pytest.mark.parametrize("field", ["now", "last_consumed_at"])
def test_hanayume_grant_only_rejects_naive_timestamps(field: str) -> None:
    policy = HanayumeSitePolicy()
    values = {
        "resource": "work_ticket",
        "last_consumed_at": NOW,
        "now": NOW,
        "cooldown_hours": None,
    }
    values[field] = NOW.replace(tzinfo=None)
    with pytest.raises(SitePolicyError, match="timezone-aware"):
        policy.grant_only_skip_reason(**values)


@pytest.mark.parametrize("cooldown_hours", [-1, True, 1.5])
def test_hanayume_grant_only_rejects_invalid_cooldown(cooldown_hours) -> None:
    with pytest.raises(SitePolicyError, match="non-negative integer"):
        HanayumeSitePolicy().grant_only_retry_at(
            resource="work_ticket",
            last_consumed_at=NOW,
            cooldown_hours=cooldown_hours,
        )
