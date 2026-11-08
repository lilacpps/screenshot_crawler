import hashlib
from datetime import datetime, timedelta
from pathlib import Path

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
from screenshot_crawler.site_policies import (
    EbookJapanSitePolicy,
    PolicyDecision,
    SitePolicyError,
    SitePolicyRegistry,
)
from screenshot_crawler.watchlist.service import WatchlistService
from tests.helpers.acquisition_scope import synchronized_legacy_planner

NOW = datetime(2026, 11, 7, 12, tzinfo=JST)


def _source(
    access_mode: str = "owned",
    *,
    available: bool = True,
    site: str = "ebookjapan",
    access_granted_until: str | None = None,
    display_position: object = 10,
) -> Source:
    return Source(
        id=1,
        item_id=1,
        site=site,
        external_id="A000083590",
        discovery_key="134336",
        access_mode=access_mode,
        free_until=None,
        available=available,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at=None,
        access_granted_until=access_granted_until,
        published_at=None,
        created_at="2026-11-07T00:00:00+09:00",
        updated_at="2026-11-07T00:00:00+09:00",
        display_position=display_position,  # type: ignore[arg-type]
    )


def _evaluate(source: Source) -> PolicyDecision:
    return EbookJapanSitePolicy().evaluate(
        source,
        now=NOW,
        quota_available=0,
    )


def test_ebookjapan_policy_allows_only_available_catalog_owned_as_direct() -> None:
    decision = _evaluate(_source())

    assert decision == PolicyDecision(
        True,
        "direct",
        "catalog_owned_candidate",
        consumes_quota=False,
    )


def test_ebookjapan_policy_opts_into_display_position_batch_ordering() -> None:
    assert EbookJapanSitePolicy().batch_ordering() == "display_position"


@pytest.mark.parametrize("position", [None, 0, -1, True, False, 1.5, "1"])
def test_ebookjapan_policy_rejects_owned_source_with_invalid_display_position(
    position: object,
) -> None:
    decision = _evaluate(_source(display_position=position))

    assert decision.eligible is False
    assert decision.access_strategy is None
    assert decision.reason == "owned_display_position_invalid"
    assert decision.consumes_quota is False


@pytest.mark.parametrize(
    ("mode", "grant_until", "reason"),
    [
        ("free", None, "free_not_supported"),
        ("quota", (NOW + timedelta(hours=1)).isoformat(), "quota_not_supported"),
        ("paid", (NOW + timedelta(hours=1)).isoformat(), "paid"),
        ("grant", (NOW + timedelta(hours=1)).isoformat(), "grant_not_supported"),
        ("rental", (NOW + timedelta(hours=1)).isoformat(), "rental_not_supported"),
        ("unknown", None, "unknown"),
        ("other", None, "unsupported_access_mode"),
    ],
)
def test_ebookjapan_policy_rejects_every_non_owned_mode(
    mode: str,
    grant_until: str | None,
    reason: str,
) -> None:
    decision = _evaluate(_source(mode, access_granted_until=grant_until))

    assert decision.eligible is False
    assert decision.access_strategy is None
    assert decision.reason == reason
    assert decision.consumes_quota is False
    assert decision.quota_resource is None
    assert decision.pending_quota is False


def test_ebookjapan_policy_rejects_unavailable_owned_and_wrong_site_sources() -> None:
    unavailable = _evaluate(_source(available=False, display_position=None))
    wrong_site = _evaluate(_source(site="comicdays", display_position=None))

    assert (unavailable.eligible, unavailable.access_strategy, unavailable.reason) == (
        False,
        None,
        "unavailable",
    )
    assert (wrong_site.eligible, wrong_site.access_strategy, wrong_site.reason) == (
        False,
        None,
        "wrong_site",
    )
    assert unavailable.consumes_quota is False
    assert wrong_site.consumes_quota is False


def test_ebookjapan_plan_uses_listing_position_not_source_id_and_selected_keys(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="muda16-order", title="Muda 16 order")
    )
    source_ids_by_position: dict[int, int] = {}
    for position in range(16, 0, -1):
        item = catalog.create_item(
            ItemInput(
                item_title=f"Volume {position}",
                order_key=f"{position:02d}",
                order_label=f"{position}巻",
            ),
            work_id=work.id,
        )
        source = catalog.create_source(
            SourceInput(
                site="ebookjapan",
                external_id=f"A{115888000 + position:09d}",
                discovery_key="muda16-order-key",
                access_mode="owned",
                available=True,
                display_position=position,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web",
                locator=f"https://ebookjapan.yahoo.co.jp/books/115888/{source.external_id}/",
            ),
            source_id=source.id,
        )
        source_ids_by_position[position] = source.id

    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    watchlist.add(
        key="muda16-order-key",
        work_key=work.work_key,
        site="ebookjapan",
        url="https://ebookjapan.yahoo.co.jp/books/all/115888/",
        label="Muda 16 order",
    )
    policies = SitePolicyRegistry()
    policies.register("ebookjapan", EbookJapanSitePolicy)
    planner = BatchPlanner(
        catalog,
        policies,
        watchlist=watchlist,
        library_dir=tmp_path / "Books",
    )

    before_plan_sha = hashlib.sha256(catalog.path.read_bytes()).hexdigest()
    plan = planner.plan(site="ebookjapan", now=NOW)
    selected_plan = planner.plan(
        site="ebookjapan", selected_keys=["muda16-order-key"], now=NOW
    )
    after_plan_sha = hashlib.sha256(catalog.path.read_bytes()).hexdigest()

    expected_source_ids = [source_ids_by_position[position] for position in range(1, 17)]
    assert source_ids_by_position[1] > source_ids_by_position[16]
    assert [candidate.source_id for candidate in plan.candidates] == expected_source_ids
    assert [candidate.source_id for candidate in selected_plan.candidates] == expected_source_ids
    assert [candidate.metadata["order"] for candidate in plan.candidates] == [
        f"{position}巻" for position in range(1, 17)
    ]
    assert plan.quota_available is None
    assert plan.quota_remaining is None
    assert all(candidate.access_strategy == "direct" for candidate in plan.candidates)
    assert all(not candidate.consumes_quota for candidate in plan.candidates)
    assert after_plan_sha == before_plan_sha


def test_ebookjapan_policy_exposes_no_quota_or_grant_only_path() -> None:
    policy = EbookJapanSitePolicy()

    assert policy.supported_access_resources() == ()
    assert policy.ordered_access_resource_passes() == ()
    assert policy.additional_access_resource_passes() == ()
    assert policy.available_quota((_source(),), NOW) is None
    assert policy.grant_only_supported_access_resources() == ()
    assert policy.access_grant_until(NOW) is None
    assert policy.resource_state_scope("work_ticket") is None
    assert policy.defer_quota_access_to_grant_phase() is False
    with pytest.raises(SitePolicyError, match="Unsupported access resource"):
        policy.validate_access_resource("work_ticket")
    with pytest.raises(SitePolicyError, match="Grant-only access resource is not implemented"):
        policy.validate_grant_only_resource("work_ticket")


def test_ebookjapan_policy_requires_timezone_aware_now() -> None:
    with pytest.raises(SitePolicyError, match="timezone-aware"):
        EbookJapanSitePolicy().evaluate(
            _source(),
            now=datetime.fromisoformat("2026-11-07T12:00:00"),
            quota_available=None,
        )


def test_batch_planner_selects_only_available_ebookjapan_owned_sources(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="ebookjapan-owned-policy-test", title="Test work")
    )
    rows = (
        ("A000083590", "owned", True, 10),
        ("A000000001", "owned", False, 9),
        ("A000000002", "free", True, 8),
        ("A000000003", "quota", True, 7),
    )
    for index, (external_id, access_mode, available, position) in enumerate(rows, 1):
        item = catalog.create_item(
            ItemInput(order_label=f"Volume {index}"), work_id=work.id
        )
        source = catalog.create_source(
            SourceInput(
                site="ebookjapan",
                external_id=external_id,
                discovery_key="134336",
                access_mode=access_mode,
                available=available,
                display_position=position,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web",
                locator=f"https://ebookjapan.yahoo.co.jp/books/134336/{external_id}/",
            ),
            source_id=source.id,
        )

    policies = SitePolicyRegistry()
    policies.register("ebookjapan", EbookJapanSitePolicy)
    plan = synchronized_legacy_planner(catalog, policies).plan(
        site="ebookjapan", now=NOW
    )

    assert [candidate.external_id for candidate in plan.candidates] == ["A000083590"]
    candidate = plan.candidates[0]
    assert candidate.access_strategy == "direct"
    assert candidate.reason == "catalog_owned_candidate"
    assert candidate.consumes_quota is False
    assert candidate.quota_resource is None
    assert plan.quota_available is None
    assert plan.quota_remaining is None
    skipped_reasons = {entry.reason for entry in plan.skipped}
    assert {"unavailable", "free_not_supported", "quota_not_supported"} <= skipped_reasons
    with pytest.raises(BatchPlanningError, match="Unsupported access resource"):
        BatchPlanner(catalog, policies).plan(
            site="ebookjapan", now=NOW, quota_resource="work_ticket"
        )
