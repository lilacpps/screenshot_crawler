from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from screenshot_crawler.batch import BatchPlanner, BatchPlanningError
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.management.inventory import _access
from screenshot_crawler.site_policies import PiccomaSitePolicy, SitePolicyError, SitePolicyRegistry
from tests.helpers.acquisition_scope import synchronized_legacy_planner

NOW = datetime(2026, 10, 9, 12, tzinfo=JST)


def _source(
    access_mode: str = "free",
    *,
    available: bool = True,
    access_granted_until: str | None = None,
) -> Source:
    return Source(
        id=1,
        item_id=1,
        site="piccoma",
        external_id="900:101",
        discovery_key="900",
        access_mode=access_mode,
        free_until=None,
        available=available,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at=None,
        access_granted_until=access_granted_until,
        published_at=None,
        created_at="2026-10-09T00:00:00+09:00",
        updated_at="2026-10-09T00:00:00+09:00",
        display_position=432,
    )


def _registry() -> SitePolicyRegistry:
    registry = SitePolicyRegistry()
    registry.register("piccoma", PiccomaSitePolicy)
    return registry


def test_piccoma_policy_allows_only_available_free_as_direct() -> None:
    decision = PiccomaSitePolicy().evaluate(
        _source(), now=NOW, quota_available=0
    )

    assert decision.eligible is True
    assert decision.access_strategy == "direct"
    assert decision.reason == "free"
    assert decision.consumes_quota is False
    assert decision.quota_resource is None
    assert decision.pending_quota is False


@pytest.mark.parametrize(
    ("mode", "grant_until"),
    [
        ("quota", None),
        ("quota", NOW.isoformat()),
        ("quota", (NOW - timedelta(hours=1)).isoformat()),
        ("paid", (NOW + timedelta(hours=1)).isoformat()),
        ("owned", None),
        ("grant", (NOW + timedelta(hours=1)).isoformat()),
        ("rental", (NOW + timedelta(hours=1)).isoformat()),
        ("unknown", None),
        ("unrecognized", None),
    ],
)
@pytest.mark.parametrize("available", [True, False])
def test_piccoma_policy_rejects_unsupported_modes_and_inactive_grants(
    mode: str, grant_until: str | None, available: bool
) -> None:
    decision = PiccomaSitePolicy().evaluate(
        _source(mode, available=available, access_granted_until=grant_until),
        now=NOW,
        quota_available=10,
    )

    if available and mode == "quota":
        assert decision.eligible is True
        assert decision.access_strategy == "quota"
        assert decision.consumes_quota is True
        assert decision.quota_resource == PiccomaSitePolicy.TICKET_RESOURCE
    else:
        assert decision.eligible is False
        assert decision.access_strategy is None
        assert decision.consumes_quota is False
        assert decision.quota_resource is None
    assert decision.pending_quota is False
    classification = _access(
        PiccomaSitePolicy(),
        _source(mode, available=available, access_granted_until=grant_until), NOW,
    )
    assert classification.category == (
        "unavailable" if not available else
        "quota" if mode == "quota" else "paid" if mode == "paid" else "unknown"
    )
    assert classification.resources == (
        (
            PiccomaSitePolicy.TICKET_RESOURCE,
            PiccomaSitePolicy.WORK_TICKET_RESOURCE,
            PiccomaSitePolicy.BINGE_TICKET_RESOURCE,
        )
        if classification.category == "quota"
        else ()
    )


@pytest.mark.parametrize("available", [True, False])
def test_piccoma_policy_allows_only_available_active_manual_grant(available: bool) -> None:
    decision = PiccomaSitePolicy().evaluate(
        _source("quota", available=available,
                access_granted_until=(NOW + timedelta(hours=1)).isoformat()),
        now=NOW, quota_available=0,
    )
    assert decision.eligible is available
    assert decision.access_strategy == ("direct" if available else None)
    assert decision.consumes_quota is False
    assert decision.quota_resource is None
    assert decision.pending_quota is False
    assert _access(
        PiccomaSitePolicy(),
        _source("quota", available=available,
                access_granted_until=(NOW + timedelta(hours=1)).isoformat()), NOW,
    ).category == ("direct" if available else "unavailable")


@pytest.mark.parametrize("value", ["bad", "2026-10-10T12:00:00"])
def test_piccoma_policy_rejects_invalid_grant_timestamp(value: str) -> None:
    with pytest.raises(SitePolicyError):
        PiccomaSitePolicy().evaluate(
            _source("quota", access_granted_until=value), now=NOW, quota_available=0
        )


def test_piccoma_policy_rejects_unavailable_free_and_exposes_distinct_resources() -> None:
    policy = PiccomaSitePolicy()
    decision = policy.evaluate(_source(available=False), now=NOW, quota_available=1)
    assert decision.eligible is False
    assert decision.reason == "unavailable"
    assert policy.supported_access_resources() == (
        policy.TICKET_RESOURCE,
        policy.WORK_TICKET_RESOURCE,
        policy.BINGE_TICKET_RESOURCE,
    )
    assert policy.ordered_access_resource_passes() == (policy.TICKET_RESOURCE,)
    assert policy.additional_access_resource_passes() == ()
    assert policy.grant_only_supported_access_resources() == (
        policy.WORK_TICKET_RESOURCE,
        policy.BINGE_TICKET_RESOURCE,
    )
    assert policy.resolve_grant_only_per_work() is True
    for resource in policy.grant_only_supported_access_resources():
        assert policy.resolve_grant_only_per_work(resource) is True
    assert policy.resolve_batch_quota_per_work("piccoma_ticket_auto") is True
    assert policy.resource_state_scope(policy.TICKET_RESOURCE) is None
    policy.validate_access_resource(policy.TICKET_RESOURCE)
    policy.validate_access_resource(policy.WORK_TICKET_RESOURCE)
    policy.validate_access_resource(policy.BINGE_TICKET_RESOURCE)
    policy.validate_grant_only_resource(policy.WORK_TICKET_RESOURCE)
    policy.validate_grant_only_resource(policy.BINGE_TICKET_RESOURCE)
    with pytest.raises(SitePolicyError, match="Unsupported access resource"):
        policy.validate_access_resource("piccoma_ticket_grant")
    with pytest.raises(SitePolicyError, match="Grant-only access resource is not implemented"):
        policy.validate_grant_only_resource("piccoma_ticket_grant")


def test_piccoma_planner_keeps_free_and_active_grants_with_catalog_positions(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(
            work_key="caller-owned-opaque-work-key",
            title="Piccoma Series",
            author="Artist",
            genre="Manga",
        )
    )
    rows = [
        ("900:101", "free", True, 432, None),
        ("900:102", "free", True, 431, None),
        ("900:103", "free", False, 430, None),
        ("900:104", "quota", True, 429, (NOW + timedelta(hours=1)).isoformat()),
        ("900:105", "paid", True, 428, None),
        ("900:106", "owned", True, 427, None),
        ("900:107", "unknown", True, 426, None),
        ("900:108", "quota", True, 425, NOW.isoformat()),
        ("900:109", "quota", True, 424, None),
    ]
    for index, (external_id, mode, available, position, grant_until) in enumerate(rows):
        item = catalog.create_item(
            ItemInput(order_label=f"Episode {index + 1}"), work_id=work.id
        )
        source = catalog.create_source(
            SourceInput(
                site="piccoma",
                external_id=external_id,
                discovery_key="900",
                access_mode=mode,
                available=available,
                access_granted_until=grant_until,
                display_position=position,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web",
                locator=f"https://piccoma.com/web/viewer/900/{external_id.split(':')[1]}",
            ),
            source_id=source.id,
        )

    plan = synchronized_legacy_planner(catalog, _registry()).plan(
        site="piccoma", now=NOW
    )

    assert [candidate.external_id for candidate in plan.candidates] == [
        "900:101",
        "900:102",
        "900:104",
        "900:108",
        "900:109",
    ]
    assert [candidate.artifact_prefix for candidate in plan.candidates] == [
        "432", "431", "429", "425", "424"
    ]
    assert [candidate.access_strategy for candidate in plan.candidates] == [
        "direct",
        "direct",
        "direct",
        "quota",
        "quota",
    ]
    assert [candidate.reason for candidate in plan.candidates] == [
        "free", "free", "active_manual_grant", "ticket_auto", "ticket_auto"
    ]
    assert [candidate.consumes_quota for candidate in plan.candidates] == [
        False, False, False, True, True
    ]
    assert [candidate.quota_resource for candidate in plan.candidates] == [
        None, None, None, PiccomaSitePolicy.TICKET_RESOURCE,
        PiccomaSitePolicy.TICKET_RESOURCE,
    ]
    assert all(candidate.metadata == {
        "title": "Piccoma Series",
        "author": "Artist",
        "order": catalog.get_item(candidate.item_id).order_label,
        "genre": "Manga",
    } for candidate in plan.candidates)
    assert {skip.reason for skip in plan.skipped} >= {
        "unavailable",
        "unsupported_access_mode",
        "unknown",
        "paid",
    }


def test_piccoma_planner_rejects_explicit_quota_resource(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    with pytest.raises(BatchPlanningError, match="Unsupported access resource"):
        BatchPlanner(catalog, _registry()).plan(
            site="piccoma", now=NOW, quota_resource="piccoma_ticket_grant"
        )


@pytest.mark.parametrize("allow", [False, True])
def test_piccoma_quota_is_default_and_legacy_flag_is_a_noop(
    allow: bool,
) -> None:
    policy = PiccomaSitePolicy()
    quota = _source("quota")
    decision = policy.evaluate_with_quota_access(
        quota, now=NOW, quota_available=None, allow_quota_access=allow
    )
    assert decision.eligible is True
    assert decision.access_strategy == "quota"
    assert decision.reason == "ticket_auto"
    assert decision.consumes_quota is True
    assert decision.quota_resource == policy.TICKET_RESOURCE
    assert decision.quota_scope == "site"
    assert decision.quota_limit is None
    assert decision.quota_commit_mode == "after_observed_consumption"

    active = policy.evaluate_with_quota_access(
        _source("quota", access_granted_until=(NOW + timedelta(hours=1)).isoformat()),
        now=NOW,
        quota_available=None,
        allow_quota_access=allow,
    )
    assert active.eligible is True
    assert active.access_strategy == "direct"
    assert active.consumes_quota is False
    assert active.reason == "active_manual_grant"


@pytest.mark.parametrize(
    ("resource", "reason"),
    [
        (PiccomaSitePolicy.WORK_TICKET_RESOURCE, "work_ticket"),
        (PiccomaSitePolicy.BINGE_TICKET_RESOURCE, "binge_ticket"),
    ],
)
def test_piccoma_grant_only_uses_explicit_ordered_resource(
    resource: str, reason: str
) -> None:
    policy = PiccomaSitePolicy()
    grant = policy.evaluate_for_quota_resource(
        _source("quota"),
        now=NOW,
        quota_available=None,
        quota_resource=resource,
    )
    assert grant.eligible is True
    assert grant.consumes_quota is True
    assert grant.reason == reason
    assert grant.quota_resource == resource
    assert grant.quota_scope == "site"
    assert grant.quota_limit is None
    assert policy.ordered_access_resource_passes() == (policy.TICKET_RESOURCE,)
    assert policy.grant_only_supported_access_resources() == (
        policy.WORK_TICKET_RESOURCE,
        policy.BINGE_TICKET_RESOURCE,
    )


@pytest.mark.parametrize("invalid", [1, "true", None])
def test_piccoma_quota_opt_in_must_be_exact_bool(invalid: object) -> None:
    with pytest.raises(SitePolicyError, match="boolean"):
        PiccomaSitePolicy().evaluate_with_quota_access(
            _source("quota"),
            now=NOW,
            quota_available=None,
            allow_quota_access=invalid,  # type: ignore[arg-type]
        )


def test_piccoma_unknown_prior_quota_runs_block_but_exact_no_action_does_not() -> None:
    policy = PiccomaSitePolicy()
    finished = NOW.isoformat()
    runs = [
        SimpleNamespace(
            site_snapshot="piccoma", source_id=1, access_strategy="quota",
            status="running", error_type=None, finished_at=None,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=2, access_strategy="quota",
            status="failed", error_type="UnknownPageStateError", finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot=None, source_id=6, access_strategy="quota",
            status="future_status", error_type=None, finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=7, access_strategy=None,
            status="failed", error_type=None, finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=3, access_strategy="quota",
            status="failed", error_type=policy.NO_ACTION_ERROR_TYPE,
            error_message=policy.NO_ACTION_REASON,
            stop_reason=policy.NO_ACTION_REASON, page_count=None, finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=8, access_strategy="quota",
            status="succeeded", error_type="UnexpectedError", finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=4, access_strategy="direct",
            status="failed", error_type="UnknownPageStateError", finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="other", source_id=5, access_strategy="quota",
            status="failed", error_type="UnknownPageStateError", finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="other", source_id=9, access_strategy="quota",
            status="succeeded", error_type=None, error_message=None, page_count=1,
            finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=10, access_strategy="quota",
            status="failed", error_type=policy.NO_ACTION_ERROR_TYPE,
            error_message=policy.NO_ACTION_REASON, stop_reason=policy.NO_ACTION_REASON,
            page_count=None, finished_at=None,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=11, access_strategy="quota",
            status="failed", error_type=policy.NO_ACTION_ERROR_TYPE,
            error_message=policy.NO_ACTION_REASON, stop_reason=policy.NO_ACTION_REASON,
            page_count=None, finished_at="not-a-timestamp",
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=12, access_strategy="quota",
            status="failed", error_type=policy.NO_ACTION_ERROR_TYPE,
            error_message=policy.NO_ACTION_REASON, stop_reason="different_reason",
            page_count=None, finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=13, access_strategy="quota",
            status="succeeded", error_type="UnexpectedError", error_message=None,
            page_count=1, finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=14, access_strategy="quota",
            status="succeeded", error_type=None, error_message="stale error",
            page_count=1, finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=15, access_strategy="quota",
            status="succeeded", error_type=None, error_message=None,
            page_count=0, finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=16, access_strategy="quota",
            status="succeeded", error_type=None, error_message=None,
            page_count=1, finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=17, access_strategy="quota",
            status="succeeded", error_type=None, error_message=None, page_count=1,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=18, access_strategy="quota",
            status="succeeded", error_type=None, error_message=None, page_count=0,
            stop_reason="entry_confirmed", finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=19, access_strategy="quota",
            status="succeeded", error_type=None, error_message=None, page_count=False,
            stop_reason="entry_confirmed", finished_at=finished,
        ),
        SimpleNamespace(
            site_snapshot="piccoma", source_id=20, access_strategy="quota",
            status="succeeded", error_type=None, error_message=None, page_count=0,
            stop_reason="wrong_terminal", finished_at=finished,
        ),
    ]
    assert policy.unresolved_quota_attempt_source_ids(runs) == frozenset(
        {1, 2, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 19, 20}
    )


def _make_ticket_planner(
    tmp_path: Path,
    rows: list[tuple[str, str, int, str | None]],
    *,
    order_keys: tuple[str | None, ...] | None = None,
    discovery_keys: tuple[str | None, ...] | None = None,
) -> tuple[CatalogService, BatchPlanner, dict[str, int]]:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="ticket-policy-work", title="Ticket Series", genre="Manga")
    )
    source_ids: dict[str, int] = {}
    for index, (external_id, access_mode, display_position, grant_until) in enumerate(rows):
        item = catalog.create_item(
            ItemInput(
                order_key=(order_keys[index] if order_keys is not None else None),
                order_label=f"episode-{index + 1:02d}",
            ),
            work_id=work.id,
        )
        source = catalog.create_source(
            SourceInput(
                site="piccoma", external_id=external_id,
                discovery_key=(
                    discovery_keys[index] if discovery_keys is not None else "ticket-work"
                ),
                access_mode=access_mode, available=True, display_position=display_position,
                access_granted_until=grant_until,
            ),
            item_id=item.id,
        )
        source_ids[external_id] = source.id
        catalog.create_source_target(
            SourceTargetInput(
                backend="web",
                locator=f"https://piccoma.com/web/viewer/{external_id.replace(':', '/')}",
            ),
            source_id=source.id,
        )
    return catalog, synchronized_legacy_planner(catalog, _registry()), source_ids


def test_piccoma_default_tickets_preserve_mixed_selected_candidate_sequence(
    tmp_path: Path,
) -> None:
    catalog, planner, _source_ids = _make_ticket_planner(
        tmp_path,
        [
            ("900:101", "quota", 3, None),
            ("900:102", "free", 2, None),
            ("900:103", "quota", 1, None),
        ],
        order_keys=("02", "03", "01"),
        discovery_keys=("ticket-a", "ticket-b", "ticket-a"),
    )

    plan = planner.plan(
        site="piccoma",
        now=NOW,
        selected_keys=("ticket-b", "ticket-a"),
    )

    assert [candidate.external_id for candidate in plan.candidates] == [
        "900:101", "900:102", "900:103"
    ]
    assert [candidate.access_strategy for candidate in plan.candidates] == [
        "quota", "direct", "quota"
    ]
    assert all(
        candidate.quota_limit is None
        for candidate in plan.candidates
        if candidate.consumes_quota
    )

    class UnpreservedPiccomaPolicy(PiccomaSitePolicy):
        def preserve_candidate_sequence(self, *, allow_quota_access: bool) -> bool:
            del allow_quota_access
            return False

    legacy_registry = SitePolicyRegistry()
    legacy_registry.register("piccoma", UnpreservedPiccomaPolicy)
    legacy_planner = BatchPlanner(
        catalog, legacy_registry, watchlist=planner.watchlist
    )
    unpreserved_plan = legacy_planner.plan(
        site="piccoma",
        now=NOW,
        selected_keys=("ticket-b", "ticket-a"),
        allow_quota_access=True,
    )
    assert [candidate.external_id for candidate in unpreserved_plan.candidates] == [
        "900:103", "900:102", "900:101"
    ]


@pytest.mark.parametrize(
    ("run_status", "error_type", "blocked"),
    [
        ("running", None, True),
        ("failed", "UnknownPageStateError", True),
        ("failed", PiccomaSitePolicy.NO_ACTION_ERROR_TYPE, False),
    ],
)
def test_piccoma_planner_uses_every_prior_quota_run_for_retry_hold(
    tmp_path: Path,
    run_status: str,
    error_type: str | None,
    blocked: bool,
) -> None:
    catalog, planner, source_ids = _make_ticket_planner(
        tmp_path, [("900:101", "quota", 1, None)]
    )
    item = catalog.get_source(source_ids["900:101"]).item_id
    run = catalog.create_crawl_run(
        item_id=item,
        source_id=source_ids["900:101"],
        target_id=catalog.list_source_targets(source_id=source_ids["900:101"])[0].id,
        access_strategy="quota",
        started_at=NOW,
    )
    if run_status == "failed":
        if error_type == PiccomaSitePolicy.NO_ACTION_ERROR_TYPE:
            catalog.mark_crawl_run_failed(
                run.id,
                error_type=error_type,
                error_message=PiccomaSitePolicy.NO_ACTION_REASON,
                stop_reason=PiccomaSitePolicy.NO_ACTION_REASON,
                finished_at=NOW,
            )
        else:
            catalog.mark_crawl_run_failed(run.id, error_type=error_type or "UnknownError")

    plan = planner.plan(site="piccoma", now=NOW)

    if blocked:
        assert plan.candidates == []
        assert any(item.reason == "prior_quota_attempt_unresolved" for item in plan.skipped)
    else:
        assert [candidate.external_id for candidate in plan.candidates] == ["900:101"]


def test_piccoma_planner_uses_fresh_grant_after_prior_unknown_quota_run(
    tmp_path: Path,
) -> None:
    catalog, planner, source_ids = _make_ticket_planner(
        tmp_path, [("900:101", "quota", 1, None)]
    )
    source_id = source_ids["900:101"]
    item_id = catalog.get_source(source_id).item_id
    target_id = catalog.list_source_targets(source_id=source_id)[0].id
    catalog.create_crawl_run(
        item_id=item_id,
        source_id=source_id,
        target_id=target_id,
        access_strategy="quota",
        started_at=NOW,
    )
    catalog.record_quota_access(
        source_id,
        quota_started_at=NOW,
        access_granted_until=NOW + timedelta(hours=71),
    )

    plan = planner.plan(site="piccoma", now=NOW)

    assert len(plan.candidates) == 1
    assert plan.candidates[0].external_id == "900:101"
    assert plan.candidates[0].access_strategy == "direct"
    assert plan.candidates[0].consumes_quota is False
