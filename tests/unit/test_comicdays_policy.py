from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.comicdays import ComicDaysSitePolicy


def _source(mode: str, available: bool = True) -> Source:
    return Source(1, 1, "comicdays", "1", None, mode, None, available, None, None, None, None, None, "", "", None)


@pytest.mark.parametrize("mode", ["paid", "owned", "rental", "grant", "unknown"])
def test_comicdays_policy_rejects_non_free_modes(mode: str) -> None:
    result = ComicDaysSitePolicy().evaluate(_source(mode), now=datetime.now(JST), quota_available=10)
    assert not result.eligible
    assert result.access_strategy is None


def test_comicdays_policy_allows_only_current_free_source() -> None:
    result = ComicDaysSitePolicy().evaluate(_source("free"), now=datetime.now(JST), quota_available=None)
    assert result.eligible and result.access_strategy == "direct" and not result.consumes_quota
    assert not ComicDaysSitePolicy().evaluate(_source("free", False), now=datetime.now(JST), quota_available=None).eligible


def test_comicdays_policy_selects_work_ticket_and_active_grant_direct() -> None:
    policy = ComicDaysSitePolicy()
    now = datetime(2026, 10, 3, 12, tzinfo=JST)
    candidate = policy.evaluate(_source("quota"), now=now, quota_available=None)
    assert candidate.eligible and candidate.access_strategy == "quota"
    assert candidate.consumes_quota and candidate.quota_resource == "work_ticket"
    assert candidate.quota_scope == "work" and candidate.quota_limit is None
    assert candidate.quota_commit_mode == "after_observed_consumption"
    active = replace(_source("quota"), access_granted_until=now + timedelta(hours=1))
    direct = policy.evaluate(active, now=now, quota_available=None)
    assert direct.eligible and direct.access_strategy == "direct" and not direct.consumes_quota


def test_comicdays_policy_resource_contract_and_cooldown_boundaries() -> None:
    policy = ComicDaysSitePolicy()
    assert policy.supported_access_resources() == ("work_ticket",)
    assert policy.ordered_access_resource_passes() == ("work_ticket",)
    assert policy.grant_only_supported_access_resources() == ("work_ticket",)
    assert policy.resource_state_scope("work_ticket") == "work"
    assert policy.defer_quota_access_to_grant_phase() is True
    consumed = datetime(2026, 10, 3, 0, tzinfo=JST)
    assert policy.grant_only_skip_reason(resource="work_ticket", last_consumed_at=consumed, now=consumed + timedelta(hours=23) - timedelta(seconds=1), cooldown_hours=None) == "work_ticket_cooldown"
    assert policy.grant_only_skip_reason(resource="work_ticket", last_consumed_at=consumed, now=consumed + timedelta(hours=23), cooldown_hours=None) is None
    assert policy.access_grant_until(consumed) == consumed + timedelta(hours=71)
