from datetime import datetime, timedelta
from pathlib import Path

import pytest

from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies import SitePolicyRegistry
from screenshot_crawler.site_policies.comicdays import ComicDaysSitePolicy
from screenshot_crawler.site_policies.hanayume import HanayumeSitePolicy
from tests.helpers.acquisition_scope import synchronized_legacy_watchlist

NOW = datetime(2026, 10, 4, 12, tzinfo=JST)


def _registry(site: str, policy) -> SitePolicyRegistry:
    registry = SitePolicyRegistry()
    registry.register(site, policy)
    return registry


def _plan(catalog: CatalogService, site: str, policy, *, now: datetime):
    watchlist = synchronized_legacy_watchlist(catalog)
    return BatchPlanner(catalog, _registry(site, policy), watchlist=watchlist).plan(
        site=site, now=now
    )


def _episode(
    catalog: CatalogService,
    *,
    work,
    external_id: str,
    order: str,
    access_mode: str,
    access_granted_until: str | None = None,
    site: str = "comicdays",
):
    item = catalog.create_item(
        ItemInput(item_title=f"Episode {order}", order_key=order), work_id=work.id
    )
    source = catalog.create_source(
        SourceInput(
            site=site,
            external_id=external_id,
            access_mode=access_mode,
            access_granted_until=access_granted_until,
        ),
        item_id=item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(
            backend="web",
            locator=(
                f"https://hanayume.com/episodes/{external_id}"
                if site == "hanayume"
                else f"https://comic-days.com/episode/{external_id}"
            ),
        ),
        source_id=source.id,
    )
    return item, source


@pytest.mark.parametrize(
    ("site", "policy"),
    [
        ("comicdays", ComicDaysSitePolicy),
        ("hanayume", HanayumeSitePolicy),
    ],
)
def test_comicdays_planner_keeps_one_quota_candidate_per_work_in_catalog_order(
    tmp_path: Path, site: str, policy
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    first_work = catalog.create_work(
        WorkInput(work_key=f"{site}:series:100", title="First")
    )
    second_work = catalog.create_work(
        WorkInput(work_key=f"{site}:series:200", title="Second")
    )
    _episode(catalog, work=first_work, external_id="1003", order="03", access_mode="quota", site=site)
    _episode(catalog, work=first_work, external_id="1001", order="01", access_mode="quota", site=site)
    _episode(catalog, work=first_work, external_id="1002", order="02", access_mode="quota", site=site)
    _episode(catalog, work=second_work, external_id="2002", order="02", access_mode="quota", site=site)
    _episode(catalog, work=second_work, external_id="2001", order="01", access_mode="quota", site=site)

    plan = _plan(catalog, site, policy, now=NOW)

    assert [candidate.external_id for candidate in plan.candidates] == ["1001", "2001"]
    assert all(candidate.quota_scope == "work" for candidate in plan.candidates)
    assert all(candidate.quota_limit == 1 for candidate in plan.candidates)


@pytest.mark.parametrize(
    ("site", "policy"),
    [
        ("comicdays", ComicDaysSitePolicy),
        ("hanayume", HanayumeSitePolicy),
    ],
)
def test_comicdays_planner_direct_and_skip_classifications(
    tmp_path: Path, site: str, policy
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key=f"{site}:series:300", title="States"))
    _episode(catalog, work=work, external_id="free", order="01", access_mode="free", site=site)
    _episode(
        catalog,
        work=work,
        external_id="active",
        order="02",
        access_mode="quota",
        access_granted_until=(NOW + timedelta(hours=72)).isoformat(),
        site=site,
    )
    _episode(catalog, work=work, external_id="pending", order="03", access_mode="quota", site=site)
    _episode(catalog, work=work, external_id="paid", order="04", access_mode="paid", site=site)
    _episode(catalog, work=work, external_id="unknown", order="05", access_mode="unknown", site=site)

    plan = _plan(catalog, site, policy, now=NOW)

    assert [(candidate.external_id, candidate.access_strategy) for candidate in plan.candidates] == [
        ("free", "direct"),
        ("active", "direct"),
        ("pending", "quota"),
    ]
    assert plan.candidates[1].consumes_quota is False
    assert plan.candidates[2].consumes_quota is True
    assert plan.candidates[2].quota_resource == "work_ticket"
    assert plan.candidates[2].quota_scope == "work"
    assert plan.candidates[2].quota_limit == 1
    assert {skipped.reason for skipped in plan.skipped} >= {"paid", "unknown"}

    expires_at = NOW + timedelta(hours=72)
    before_expiry = _plan(catalog, site, policy, now=expires_at - timedelta(seconds=1))
    assert next(candidate for candidate in before_expiry.candidates if candidate.external_id == "active").access_strategy == "direct"

    at_expiry = _plan(catalog, site, policy, now=expires_at)
    expired_grant = next(
        candidate for candidate in at_expiry.candidates if candidate.external_id == "active"
    )
    assert expired_grant.access_strategy == "quota"
    assert expired_grant.consumes_quota is True
    assert expired_grant.quota_resource == "work_ticket"
