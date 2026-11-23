from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies import (
    ComicFuzSitePolicy,
    SitePolicyError,
    SitePolicyRegistry,
)
from tests.helpers.acquisition_scope import synchronized_legacy_planner

NOW = datetime(2026, 10, 13, 12, tzinfo=JST)


def _source(
    access_mode: str = "free",
    *,
    available: bool = True,
    site: str = "comicfuz",
    free_until: str | None = None,
) -> Source:
    return Source(
        id=1,
        item_id=1,
        site=site,
        external_id="1970:80641",
        discovery_key="comicfuz-test",
        access_mode=access_mode,
        free_until=free_until,
        available=available,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at=None,
        access_granted_until=None,
        published_at=None,
        created_at="2026-10-13T12:00:00+09:00",
        updated_at="2026-10-13T12:00:00+09:00",
        display_position=3,
    )


def test_comicfuz_policy_selects_free_direct_and_quota_through_work_ticket() -> None:
    decision = ComicFuzSitePolicy().evaluate(
        _source(), now=NOW, quota_available=0
    )

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        True,
        "direct",
        "free",
    )
    assert decision.consumes_quota is False
    assert decision.quota_resource is None

    quota = ComicFuzSitePolicy().evaluate(_source("quota"), now=NOW, quota_available=0)
    assert (quota.eligible, quota.access_strategy, quota.reason) == (
        True,
        "quota",
        "work_ticket",
    )
    assert quota.consumes_quota is True
    assert (quota.quota_resource, quota.quota_scope, quota.quota_limit) == (
        "work_ticket",
        "work",
        1,
    )
    assert quota.quota_commit_mode == "after_observed_consumption"


def test_comicfuz_episode_grant_is_direct_only_while_strictly_unexpired() -> None:
    policy = ComicFuzSitePolicy()
    active = replace(
        _source("quota"),
        access_granted_until="2026-10-13T13:00:00+09:00",
    )
    active_decision = policy.evaluate(active, now=NOW, quota_available=0)
    assert (
        active_decision.eligible,
        active_decision.access_strategy,
        active_decision.reason,
        active_decision.consumes_quota,
        active_decision.quota_resource,
    ) == (True, "direct", "active_access_grant", False, None)

    expires_now = replace(active, access_granted_until=NOW.isoformat())
    expired_decision = policy.evaluate(expires_now, now=NOW, quota_available=0)
    assert (expired_decision.access_strategy, expired_decision.reason) == (
        "quota",
        "work_ticket",
    )
    assert expired_decision.consumes_quota is True

    paid_with_grant = replace(
        _source("paid"), access_granted_until="2026-10-13T13:00:00+09:00"
    )
    paid_decision = policy.evaluate(paid_with_grant, now=NOW, quota_available=0)
    assert (paid_decision.eligible, paid_decision.reason) == (False, "paid")

    naive_grant = replace(active, access_granted_until="2026-10-13T13:00:00")
    with pytest.raises(SitePolicyError, match="access_granted_until must be a timezone-aware timestamp"):
        policy.evaluate(naive_grant, now=NOW, quota_available=0)


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (_source(available=False), "unavailable"),
        (_source("unknown"), "unknown"),
        (_source("paid"), "paid"),
        (_source("owned"), "owned_not_verified"),
        (_source("grant"), "grant_not_supported"),
        (_source("rental"), "rental_not_supported"),
        (_source("unexpected"), "unknown"),
        (_source(site="mangaone"), "wrong_site"),
    ],
)
def test_comicfuz_policy_rejects_unsupported_catalog_states(
    source: Source, reason: str
) -> None:
    decision = ComicFuzSitePolicy().evaluate(source, now=NOW, quota_available=100)

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        False,
        None,
        reason,
    )
    assert decision.consumes_quota is False
    assert decision.quota_resource is None


def test_comicfuz_policy_supports_only_work_ticket() -> None:
    policy = ComicFuzSitePolicy()
    assert policy.supported_access_resources() == ("work_ticket",)
    assert policy.ordered_access_resource_passes() == ("work_ticket",)
    assert policy.additional_access_resource_passes() == ()
    assert policy.grant_only_supported_access_resources() == ("work_ticket",)
    assert policy.resource_state_scope("work_ticket") == "work"
    assert policy.defer_quota_access_to_grant_phase() is False

    with pytest.raises(SitePolicyError, match="Unsupported access resource"):
        policy.validate_access_resource("premium_ticket")
    with pytest.raises(SitePolicyError, match="Grant-only access resource is not implemented"):
        policy.validate_grant_only_resource("premium_ticket")


def test_comicfuz_policy_requires_timezone_aware_now() -> None:
    with pytest.raises(SitePolicyError, match="now must be timezone-aware"):
        ComicFuzSitePolicy().evaluate(
            _source(), now=datetime(2026, 10, 13, 12),
            quota_available=None,
        )


@pytest.mark.parametrize(
    ("consumed_at", "now", "expected_retry", "expected_skip"),
    [
        (
            datetime(2026, 11, 23, 9, tzinfo=JST),
            datetime(2026, 11, 23, 23, 59, 59, tzinfo=JST),
            datetime(2026, 11, 24, 0, tzinfo=JST),
            "work_ticket_daily_reset",
        ),
        (
            datetime(2026, 11, 23, 23, 50, tzinfo=JST),
            datetime(2026, 11, 24, 0, tzinfo=JST),
            datetime(2026, 11, 24, 0, tzinfo=JST),
            None,
        ),
        (
            datetime(2026, 11, 24, 0, 1, tzinfo=JST),
            datetime(2026, 11, 24, 23, 59, 59, tzinfo=JST),
            datetime(2026, 11, 25, 0, tzinfo=JST),
            "work_ticket_daily_reset",
        ),
        (
            datetime(2026, 11, 24, 0, 1, tzinfo=UTC),
            datetime(2026, 11, 24, 0, 0, tzinfo=JST),
            datetime(2026, 11, 25, 0, tzinfo=JST),
            "work_ticket_daily_reset",
        ),
    ],
)
def test_comicfuz_ticket_reset_is_next_jst_midnight_not_elapsed_hours(
    consumed_at: datetime,
    now: datetime,
    expected_retry: datetime,
    expected_skip: str | None,
) -> None:
    policy = ComicFuzSitePolicy()
    assert policy.grant_only_retry_at(
        resource="work_ticket", last_consumed_at=consumed_at, cooldown_hours=23
    ) == expected_retry
    assert policy.grant_only_skip_reason(
        resource="work_ticket",
        last_consumed_at=consumed_at,
        now=now,
        cooldown_hours=23,
    ) == expected_skip


def test_comicfuz_ticket_reset_rejects_naive_state_and_future_state_blocks_safely() -> None:
    policy = ComicFuzSitePolicy()
    with pytest.raises(SitePolicyError, match="last_consumed_at must be timezone-aware"):
        policy.grant_only_retry_at(
            resource="work_ticket",
            last_consumed_at=datetime(2026, 11, 23, 9),
            cooldown_hours=None,
        )
    future = datetime(2026, 11, 25, 12, tzinfo=JST)
    retry = policy.grant_only_retry_at(
        resource="work_ticket", last_consumed_at=future, cooldown_hours=1
    )
    assert retry == datetime(2026, 11, 26, 0, tzinfo=JST)
    assert policy.grant_only_skip_reason(
        resource="work_ticket",
        last_consumed_at=future,
        now=datetime(2026, 11, 24, 23, 59, 59, tzinfo=JST),
        cooldown_hours=1,
    ) == "work_ticket_daily_reset"


def test_comicfuz_quota_history_blocks_unknown_and_resolves_confirmed_failure() -> None:
    policy = ComicFuzSitePolicy()
    started = "2026-11-23T23:00:00+09:00"
    finished = "2026-11-23T23:10:00+09:00"
    unknown = SimpleNamespace(
        item_id=10,
        source_id=20,
        target_id=30,
        site_snapshot="comicfuz",
        external_id_snapshot="1970:80641",
        backend_snapshot="web",
        target_key_snapshot="default",
        locator_snapshot="https://comic-fuz.com/manga/viewer/80641",
        access_strategy="quota",
        status="failed",
        started_at=started,
        finished_at=finished,
        stop_reason=None,
        page_count=None,
        error_type="RuntimeError",
        error_message="capture failed",
    )
    confirmed = replace(
        _source("quota"),
        id=20,
        item_id=10,
        quota_started_at="2026-11-23T23:05:00+09:00",
    )
    args = {
        "item_work_ids": {10: 100, 11: 200},
        "sources_by_id": {20: confirmed},
        "targets_by_id": {
            30: SimpleNamespace(
                id=30,
                source_id=20,
                backend="web",
                target_key="default",
                locator="https://comic-fuz.com/manga/viewer/80641",
            )
        },
        "now": datetime(2026, 11, 24, 0, tzinfo=JST),
    }
    assert policy.unresolved_quota_attempt_work_ids([unknown], **args) == frozenset({100})
    confirmed_run = SimpleNamespace(
        **{
            **unknown.__dict__,
            "stop_reason": "access_consumption_confirmed:v1:2026-11-23T23:05:00+09:00|capture",
        }
    )
    assert policy.unresolved_quota_attempt_work_ids([confirmed_run], **args) == frozenset()
    unconfirmed = replace(confirmed, quota_started_at=None)
    assert policy.unresolved_quota_attempt_work_ids(
        [confirmed_run], **{**args, "sources_by_id": {20: unconfirmed}}
    ) == frozenset()
    overwritten = replace(confirmed, quota_started_at="2026-11-24T00:01:00+09:00")
    assert policy.unresolved_quota_attempt_work_ids(
        [confirmed_run], **{**args, "sources_by_id": {20: overwritten}}
    ) == frozenset()
    running = SimpleNamespace(**{**confirmed_run.__dict__, "status": "running", "finished_at": None})
    assert policy.unresolved_quota_attempt_work_ids([running], **args) == frozenset({100})
    drifted = SimpleNamespace(**{**confirmed_run.__dict__, "external_id_snapshot": "9999:9999"})
    assert policy.unresolved_quota_attempt_work_ids([drifted], **args) == frozenset({100})
    target_drift = SimpleNamespace(
        **{**confirmed_run.__dict__, "locator_snapshot": "https://comic-fuz.com/manga/viewer/99999"}
    )
    assert policy.unresolved_quota_attempt_work_ids([target_drift], **args) == frozenset({100})
    other_source = replace(confirmed, id=21, item_id=11, external_id="2000:80641")
    other_run = SimpleNamespace(
        **{
            **confirmed_run.__dict__,
            "item_id": 11,
            "source_id": 21,
            "target_id": 31,
            "external_id_snapshot": "2000:80641",
        }
    )
    other_args = {
        **args,
        "sources_by_id": {20: confirmed, 21: other_source},
        "targets_by_id": {
            **args["targets_by_id"],
            31: SimpleNamespace(
                id=31,
                source_id=21,
                backend="web",
                target_key="default",
                locator="https://comic-fuz.com/manga/viewer/80641",
            ),
        },
    }
    assert policy.unresolved_quota_attempt_work_ids([confirmed_run, other_run], **other_args) == frozenset()


def test_comicfuz_planner_keeps_free_and_one_ticket_candidate_per_work(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="houkago-basket", title="Verified ComicFUZ Work")
    )
    rows = [
        ("80641", "第31話", "free", True, 3),
        ("80640", "第30話", "unknown", True, 2),
        ("80639", "第29話", "free", True, 1),
        ("80638", "第28話", "free", False, 4),
        ("80637", "第27話", "quota", True, 5),
        ("80636", "第26話", "paid", True, 6),
        ("80635", "第25話", "owned", True, 7),
    ]
    for chapter, label, mode, available, position in rows:
        item = catalog.create_item(
            ItemInput(kind="episode", order_label=label), work_id=work.id
        )
        source = catalog.create_source(
            SourceInput(
                site="comicfuz",
                external_id=f"1970:{chapter}",
                discovery_key="comicfuz-test",
                access_mode=mode,
                available=available,
                display_position=position,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web",
                locator=f"https://comic-fuz.com/manga/viewer/{chapter}",
            ),
            source_id=source.id,
        )

    policies = SitePolicyRegistry()
    policies.register("comicfuz", ComicFuzSitePolicy)
    planner = synchronized_legacy_planner(catalog, policies)
    plan = planner.plan(site="comicfuz", now=NOW)

    assert [candidate.external_id for candidate in plan.candidates] == [
        "1970:80641",
        "1970:80639",
        "1970:80637",
    ]
    assert [candidate.access_strategy for candidate in plan.candidates] == [
        "direct",
        "direct",
        "quota",
    ]
    assert [candidate.artifact_prefix for candidate in plan.candidates] == ["003", "001", "005"]
    assert [candidate.metadata for candidate in plan.candidates] == [
        {"title": "Verified ComicFUZ Work", "order": "第31話"},
        {"title": "Verified ComicFUZ Work", "order": "第29話"},
        {"title": "Verified ComicFUZ Work", "order": "第27話"},
    ]
    skipped_reasons = {entry.reason for entry in plan.skipped}
    assert skipped_reasons >= {
        "unknown",
        "unavailable",
        "paid",
        "owned_not_verified",
    }

    quota_candidate = next(candidate for candidate in plan.candidates if candidate.consumes_quota)
    uncertain_run = catalog.create_crawl_run(
        item_id=quota_candidate.item_id,
        source_id=quota_candidate.source_id,
        target_id=quota_candidate.target_id,
        access_strategy="quota",
        started_at=NOW,
    )
    held_plan = planner.plan(site="comicfuz", now=NOW)
    assert all(candidate.item_id != quota_candidate.item_id for candidate in held_plan.candidates)
    assert any(
        skipped.source_id == quota_candidate.source_id
        and skipped.reason == "prior_quota_attempt_unresolved"
        for skipped in held_plan.skipped
    )

    consumed_at = datetime(2026, 10, 13, 12, 5, tzinfo=JST)
    finished_at = datetime(2026, 10, 13, 12, 10, tzinfo=JST)
    catalog.record_quota_access_with_resource_state(
        quota_candidate.source_id,
        work_id=quota_candidate.work_id,
        site="comicfuz",
        resource="work_ticket",
        consumed_at=consumed_at,
        access_granted_until=None,
    )
    catalog.mark_crawl_run_failed(
        uncertain_run.id,
        error_type="CaptureError",
        error_message="capture failed after confirmed consumption",
        stop_reason=f"access_consumption_confirmed:v1:{consumed_at.isoformat()}|capture",
        finished_at=finished_at,
    )
    resolved_plan = planner.plan(
        site="comicfuz", now=datetime(2026, 10, 13, 12, 11, tzinfo=JST)
    )
    assert any(
        candidate.source_id == quota_candidate.source_id
        for candidate in resolved_plan.candidates
    )
