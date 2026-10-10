from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from screenshot_crawler.batch import (
    BatchExecutionError,
    BatchExecutor,
    BatchPlanner,
    CandidateExecutionError,
)
from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.runtime_settings import SiteRuntimeSettings
from screenshot_crawler.site_adapters.hanayume import HanayumeAdapter, HanayumeDiscoveryAdapter
from screenshot_crawler.site_adapters.hanayume import adapter as hanayume_adapter
from screenshot_crawler.site_adapters.hanayume import discovery as hanayume_discovery
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import SitePolicyRegistry
from screenshot_crawler.site_policies.hanayume import HanayumeSitePolicy
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(autouse=True)
def _short_hanayume_test_timeouts(monkeypatch) -> None:
    monkeypatch.setattr(hanayume_discovery, "NAVIGATION_TIMEOUT_MS", 3_000)
    monkeypatch.setattr(hanayume_discovery, "DOM_TIMEOUT_MS", 3_000)
    monkeypatch.setattr(hanayume_discovery, "RANGE_PACING_MS", 10)
    monkeypatch.setattr(hanayume_adapter, "NAVIGATION_TIMEOUT_MS", 3_000)
    monkeypatch.setattr(hanayume_adapter, "DOM_TIMEOUT_MS", 3_000)
    monkeypatch.setattr(hanayume_adapter, "RANGE_PACING_MS", 0)
    monkeypatch.setattr(HanayumeAdapter, "page_change_timeout_ms", 1_000)

BASE = "https://hanayume.com"
SEED_ID = f"{1:013x}"
WORK_ID = f"{900:013x}"
TOTAL = 32


def _episode_id(position: int) -> str:
    return f"{position:013x}"


def _title(position: int) -> str:
    if position in (4, 5):
        return f"第4話{'①' if position == 4 else '②'}"
    return f"第{position}話"


def _row(position: int, label: str) -> str:
    episode_id = _episode_id(position)
    return f"""<div class="series-eplist-item" data-e2e="eli">
      <a class="series-eplist-item-link" href="/episodes/{episode_id}">
        <h2 class="series-eplist-item-h">
          <span class="series-eplist-item-h-text" data-e2e="eliTitle">{_title(position)}</span>
        </h2>
        <span class="series-eplist-item-access-text" data-e2e="eliFreeBadge">{label}</span>
      </a>
    </div>"""


def _page_html(
    *,
    page_number: int | None,
    drift_last_range: bool = False,
    first_badge: str = "無料",
    foreign_work: bool = False,
    duplicate_boundary_row: bool = False,
    omit_last_row: bool = False,
) -> str:
    final_end = 33 if drift_last_range else TOTAL
    ranges = [(1, 30), (31, final_end)]
    range_links = [
        (
            f'<a class="series-sort-link{" mode-current" if page_number is None else ""}" '
            f'href="/episodes/{SEED_ID}/old">最新話から</a>'
        )
    ]
    for index, (start, end) in enumerate(ranges, start=1):
        label = f"{start}-{end}"
        path = f"/episodes/{SEED_ID}/{index}"
        is_current = page_number == index
        href = f"/episodes/{SEED_ID}" if is_current else path
        range_links.append(
            f'<a class="series-sort-link{" mode-current" if is_current else ""}" '
            f'href="{href}">{label}</a>'
        )
    range_links.append(
        f'<a class="series-sort-link" href="/episodes/{SEED_ID}/1">...</a>'
    )

    if page_number is None:
        positions = range(TOTAL - 9, TOTAL + 1)
    elif page_number == 1:
        positions = range(1, 31)
    else:
        positions = range(31, TOTAL + 1)
    if page_number == 2 and omit_last_row:
        positions = range(31, TOTAL)
    rows = []
    for position in positions:
        row_position = 30 if page_number == 2 and duplicate_boundary_row and position == 31 else position
        if position == 1:
            label = first_badge
        elif position <= 3:
            label = "無料"
        else:
            label = "今なら無料"
        rows.append(_row(row_position, label))
    work_id = f"{901:013x}" if foreign_work and page_number == 2 else WORK_ID
    return f"""<!doctype html><html><head><title>Fixture Work</title></head>
      <body><div class="base">
        <header id="xHeader">
          <a class="ep-h-main-h-series" href="/series/{work_id}">Fixture Work</a>
        </header>
        <div class="ep-main series-safe-filter-target">
          <div class="series mode-ep">
            <div class="series-eplist-wrap">
              <nav>{''.join(range_links)}</nav>
              <div class="series-eplist">{''.join(rows)}</div>
            </div>
          </div>
        </div>
      </div></body></html>"""


def _target(
    *,
    key: str = "hanayume-fixture",
    discovery_scope: DiscoveryScope | None = None,
) -> WatchlistTarget:
    return WatchlistTarget(
        key=key,
        work_key="hanayume-fixture-work",
        site="hanayume",
        url=f"{BASE}/episodes/{SEED_ID}",
        label="Fixture Work",
        discovery_scope=discovery_scope,
    )


def _registry() -> DiscoveryAdapterRegistry:
    registry = DiscoveryAdapterRegistry()
    registry.register("hanayume", HanayumeDiscoveryAdapter)
    return registry


async def _install_pages(
    browser_page,
    *,
    drift_last_range: bool = False,
    base_status: int = 200,
    first_badge: str = "無料",
    base_headers: dict[str, str] | None = None,
    foreign_work: bool = False,
    duplicate_boundary_row: bool = False,
    omit_last_row: bool = False,
) -> list[str]:
    requested_paths: list[str] = []

    async def fulfill(route) -> None:
        parsed = urlsplit(route.request.url)
        requested_paths.append(parsed.path)
        if parsed.path == f"/episodes/{SEED_ID}" and base_status != 200:
            await route.fulfill(status=base_status, body="", headers=base_headers or {})
            return
        if parsed.path == f"/episodes/{SEED_ID}":
            page_number = None
        elif parsed.path == f"/episodes/{SEED_ID}/1":
            page_number = 1
        elif parsed.path == f"/episodes/{SEED_ID}/2":
            page_number = 2
        else:
            await route.fulfill(status=404, body="")
            return
        await route.fulfill(
            status=200,
            body=_page_html(
                page_number=page_number,
                drift_last_range=drift_last_range,
                first_badge=first_badge,
                foreign_work=foreign_work,
                duplicate_boundary_row=duplicate_boundary_row,
                omit_last_row=omit_last_row,
            ),
            content_type="text/html; charset=utf-8",
        )

    await browser_page.route("https://hanayume.com/**", fulfill)
    return requested_paths


async def test_hanayume_full_incremental_and_bounded_discovery(
    browser_page, tmp_path: Path
) -> None:
    requested = await _install_pages(browser_page)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    service = DiscoveryService(catalog, _registry())

    full = await service.discover(browser_page, _target(), "full")

    assert full.complete is True
    assert full.observed_count == TOTAL
    sources = catalog.list_sources(site="hanayume")
    assert len(sources) == TOTAL
    assert {source.access_mode for source in sources} == {"free", "unknown"}
    assert sum(source.access_mode == "free" for source in sources) == 3
    assert {source.display_position for source in sources} == set(range(1, TOTAL + 1))
    assert {source.external_id.split(":", 1)[0] for source in sources} == {WORK_ID}
    seed_source = next(source for source in sources if source.external_id.endswith(f":{SEED_ID}"))
    assert seed_source.display_position == 1
    assert next(
        item for item in catalog.list_items() if item.id == seed_source.item_id
    ).status == "pending"
    catalog.mark_item_completed(seed_source.item_id)

    requested.clear()
    incremental = await service.discover(browser_page, _target(), "incremental")
    assert incremental.complete is None
    assert incremental.stopped_reason == "known_streak"
    assert incremental.observed_count == 5
    assert requested.count(f"/episodes/{SEED_ID}/1") == 1
    assert requested.count(f"/episodes/{SEED_ID}/2") == 1
    assert catalog.get_item(seed_source.item_id).status == "completed"

    bounded_catalog = CatalogService(tmp_path / "bounded.sqlite")
    bounded = await DiscoveryService(bounded_catalog, _registry()).discover(
        browser_page,
        _target(
            key="hanayume-bounded",
            discovery_scope=DiscoveryScope(
                from_url=f"{BASE}/episodes/{_episode_id(30)}",
                through_url=f"{BASE}/episodes/{_episode_id(28)}",
            ),
        ),
        "full",
    )
    bounded_sources = bounded_catalog.list_sources(site="hanayume")
    assert bounded.complete is True
    assert bounded.observed_count == 3
    assert [source.display_position for source in bounded_sources] == [30, 29, 28]


@pytest.mark.parametrize(
    "page_options",
    [
        pytest.param({"drift_last_range": True}, id="range-set-drift"),
        pytest.param({"foreign_work": True}, id="foreign-work-context"),
        pytest.param({"duplicate_boundary_row": True}, id="duplicate-episode-id"),
        pytest.param({"omit_last_row": True}, id="incomplete-declared-range"),
    ],
)
async def test_hanayume_incomplete_or_foreign_ranges_fail_before_catalog_sources_are_written(
    browser_page,
    tmp_path: Path,
    page_options: dict[str, object],
) -> None:
    await _install_pages(browser_page, **page_options)
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is False
    assert result.stopped_reason == "incomplete"
    assert result.observed_count == 0
    assert catalog.list_sources(site="hanayume") == []


async def test_hanayume_http_429_stops_discovery_without_retry_or_catalog_source(
    browser_page, tmp_path: Path
) -> None:
    requested = await _install_pages(browser_page, base_status=429)
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="hanayume") == []
    assert requested == [f"/episodes/{SEED_ID}"]


async def test_hanayume_http_403_stops_discovery_without_retry_or_catalog_source(
    browser_page, tmp_path: Path
) -> None:
    requested = await _install_pages(browser_page, base_status=403)
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="hanayume") == []
    assert requested == [f"/episodes/{SEED_ID}"]


async def test_hanayume_cf_challenge_header_stops_without_catalog_source(browser_page, tmp_path: Path) -> None:
    requested = await _install_pages(
        browser_page,
        base_status=503,
        base_headers={"cf-mitigated": "challenge"},
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="hanayume") == []
    assert requested == [f"/episodes/{SEED_ID}"]


async def test_hanayume_unknown_badge_and_completed_item_are_preserved(
    browser_page, tmp_path: Path
) -> None:
    await _install_pages(browser_page)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    service = DiscoveryService(catalog, _registry())
    initial = await service.discover(browser_page, _target(), "full")
    assert initial.complete is True
    seed = next(
        source
        for source in catalog.list_sources(site="hanayume")
        if source.external_id.endswith(f":{SEED_ID}")
    )
    catalog.mark_item_completed(seed.item_id)

    await browser_page.unroute_all()
    await _install_pages(browser_page, first_badge="今なら無料")
    refreshed = await service.discover(browser_page, _target(), "full")

    refreshed_seed = catalog.find_source("hanayume", seed.external_id)
    assert refreshed.complete is True
    assert refreshed_seed is not None
    assert refreshed_seed.access_mode == "unknown"
    assert catalog.get_item(seed.item_id).status == "completed"


TARGET_POSITION = 2
TARGET_EPISODE_ID = _episode_id(TARGET_POSITION)
SERIES_URL = f"{BASE}/series/{WORK_ID}"
BATCH_NOW = datetime(2026, 10, 10, 12, 0, tzinfo=JST)


def _series_batch_html(
    *, page_number: int | None, target_badge: str = "無料"
) -> str:
    ranges = ((1, 1, 30), (2, 31, TOTAL))
    links = []
    for number, start, end in ranges:
        selected = page_number == number
        href = SERIES_URL if selected else f"{SERIES_URL}/{number}"
        current_class = " mode-current" if selected else ""
        links.append(
            f'<a class="series-sort-link{current_class}" href="{href}">{start}-{end}</a>'
        )
    if page_number is None:
        positions = range(TOTAL - 9, TOTAL + 1)
    elif page_number == 1:
        positions = range(1, 31)
    else:
        positions = range(31, TOTAL + 1)
    rows = [
        _row(position, target_badge if position == TARGET_POSITION else (
            "無料" if position <= 3 else "今なら無料"
        ))
        for position in positions
    ]
    return f"""<!doctype html><html><body>
      <div class="series-eplist-wrap"><nav>{''.join(links)}</nav>{''.join(rows)}</div>
    </body></html>"""


def _batch_viewer_html(
    *,
    episode_id: str,
    work_id: str = WORK_ID,
    target_badge: str = "無料",
    mutation: str = "none",
) -> str:
    target_row = _row(TARGET_POSITION, target_badge)
    return f"""<!doctype html><html><head><style>
      body {{ margin:0 }} #comici-viewer {{ position:relative;width:200px;height:100px }}
      #xCVPages {{ position:absolute;inset:0 }} .-cv-page {{ position:absolute;top:0;width:100px;height:100px }}
    </style></head><body>
      <header id="xHeader"><a class="ep-h-main-h-series" href="{BASE}/series/{work_id}">work</a></header>
      <div class="series-eplist-wrap">{target_row}</div>
      <div id="comici-viewer" class="-cv mode-spread">
        <div class="-cv-f-page-current"></div><div class="-cv-f-page-total">9</div>
        <input id="xCVSeekBar" type="range" min="1" max="9" step="2" value="9">
        <div id="xCVPages"></div>
      </div>
      <script>
        (() => {{
          const total=9, bodyTotal=4, mutation={json.dumps(mutation)};
          const root=document.querySelector('#comici-viewer');
          const pageRoot=document.querySelector('#xCVPages');
          const seek=document.querySelector('#xCVSeekBar');
          const counter=document.querySelector('.-cv-f-page-current');
          const wrappers=[];
          for(let i=0;i<=total;i++){{
            const node=document.createElement('div');node.className='-cv-page';
            node.style.left='-3000px';pageRoot.append(node);wrappers.push(node);
          }}
          const tails={{
            0:'-cv-page mode-empty mode-pr mode-top-pr',
            [total-4]:'-cv-page mode-ci',
            [total-3]:'-cv-page mode-empty mode-pr',
            [total-2]:'-cv-page mode-empty mode-pr',
            [total-1]:'-cv-page mode-good',
            [total]:'-cv-page mode-last'
          }};
          function render(current,terminal=false){{
            counter.textContent=String(current);
            seek.value=String(total-(current-1));
            const early=mutation==='early-terminal' && current>1;
            root.classList.toggle('mode-last-page',terminal||early);
            const visible=current===1?[0,1]:[current-1,current];
            for(let i=0;i<=total;i++){{
              const node=wrappers[i];node.replaceChildren();node.className=tails[i]||'-cv-page';
              node.style.left='-3000px';
            }}
            if(current===1)wrappers[0].style.left='0px';
            visible.forEach((index,side)=>{{
              const node=wrappers[index];node.style.left=`${{side*100}}px`;
              if(index<1||index>bodyTotal)return;
              if(mutation==='unknown-after-advance' && current>1 && index===current-1){{
                node.className='-cv-page mode-sponsored';return;
              }}
              const canvas=document.createElement('canvas');canvas.width=5;canvas.height=7;
              canvas.style.cssText='width:5px;height:7px';
              const context=canvas.getContext('2d');context.fillStyle=`rgb(${{index*30}},40,60)`;
              context.fillRect(0,0,5,7);
              const holder=document.createElement('div');holder.className='-cv-page-canvas';
              holder.append(canvas);node.append(holder);node.classList.add('mode-loaded','mode-rendered');
            }});
          }}
          seek.addEventListener('input',()=>render(total-Number(seek.value)+1));
          seek.addEventListener('change',()=>render(total-Number(seek.value)+1));
          seek.addEventListener('keydown',event=>{{
            if(event.key==='End'){{event.preventDefault();render(1)}}
            if(event.key==='Home'){{event.preventDefault();render(total,true)}}
          }});
          render(1);
        }})();
      </script>
    </body></html>"""


async def _install_batch_routes(
    browser_page,
    *,
    target_badge: str = "無料",
    work_id: str = WORK_ID,
    mutation: str = "none",
) -> list[str]:
    requested: list[str] = []
    target_path = f"/episodes/{TARGET_EPISODE_ID}"

    async def fulfill(route) -> None:
        path = urlsplit(route.request.url).path
        requested.append(path)
        if path == target_path:
            body = _batch_viewer_html(
                episode_id=TARGET_EPISODE_ID,
                work_id=work_id,
                target_badge=target_badge,
                mutation=mutation,
            )
        elif path == f"/series/{WORK_ID}":
            body = _series_batch_html(page_number=None, target_badge=target_badge)
        elif path == f"/series/{WORK_ID}/1":
            body = _series_batch_html(page_number=1, target_badge=target_badge)
        elif path == f"/series/{WORK_ID}/2":
            body = _series_batch_html(page_number=2, target_badge=target_badge)
        else:
            await route.fulfill(status=404, body="")
            return
        await route.fulfill(
            status=200,
            body=body,
            content_type="text/html; charset=utf-8",
        )

    await browser_page.route("https://hanayume.com/**", fulfill)
    return requested


async def _batch_fixture(
    browser_page,
    tmp_path: Path,
    *,
    target_badge: str = "無料",
    viewer_work_id: str = WORK_ID,
    mutation: str = "none",
):
    await _install_pages(browser_page)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    discovery = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )
    assert discovery.complete is True and discovery.observed_count == TOTAL
    external_id = f"{WORK_ID}:{TARGET_EPISODE_ID}"
    source = catalog.find_source("hanayume", external_id)
    assert source is not None and source.access_mode == "free"

    policies = SitePolicyRegistry()
    policies.register("hanayume", HanayumeSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("hanayume", HanayumeAdapter)
    plan = BatchPlanner(catalog, policies).plan(site="hanayume", now=BATCH_NOW)
    assert {candidate.access_mode for candidate in plan.candidates} == {"free"}
    candidate = next(item for item in plan.candidates if item.external_id == external_id)

    await browser_page.unroute_all()
    requested = await _install_batch_routes(
        browser_page,
        target_badge=target_badge,
        work_id=viewer_work_id,
        mutation=mutation,
    )
    executor = BatchExecutor(
        catalog,
        policies,
        adapters,
        runtime_settings=SiteRuntimeSettings(page_turn_delay_ms=0),
    )
    return catalog, source, candidate, plan, executor, requested


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_discovery_to_batch_zip_completes_only_free_candidate(
    browser_page, tmp_path: Path
) -> None:
    catalog, source, candidate, plan, executor, requested = await _batch_fixture(
        browser_page, tmp_path
    )
    manifest_snapshots: list[dict[str, object]] = []

    def package_with_manifest_copy(output_dir, metadata, **kwargs):
        manifest_snapshots.append(
            json.loads((Path(output_dir) / "manifest.json").read_text(encoding="utf-8"))
        )
        return package_crawl_output(output_dir, metadata, **kwargs)

    executor.package_function = package_with_manifest_copy
    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch-output",
        library_dir=tmp_path / "library",
        max_pages=10,
        now=BATCH_NOW,
    )

    item = catalog.get_item(candidate.item_id)
    saved_source = catalog.get_source(source.id)
    run = catalog.get_crawl_run(result.crawl_run_id)
    artifacts = catalog.list_artifacts(item_id=item.id)
    assert result.stop_reason == "end" and result.page_count == 4
    assert item.status == "completed"
    assert run.status == "succeeded" and run.stop_reason == "end" and run.page_count == 4
    assert len(artifacts) == 1 and artifacts[0].format == "zip"
    assert saved_source.access_mode == "free"
    assert saved_source.quota_started_at is None and saved_source.access_granted_until is None
    assert candidate.access_strategy == "direct"
    assert candidate.consumes_quota is False and candidate.quota_resource is None
    assert catalog.get_quota_resource_state(
        catalog.get_work(item.work_id).id, site="hanayume", resource="work_ticket"
    ) is None
    assert len(plan.candidates) == 3
    assert {entry.access_mode for entry in plan.candidates} == {"free"}
    assert len(manifest_snapshots) == 1
    manifest = manifest_snapshots[0]
    manifest_pages = manifest["pages"]
    assert [entry["identity"]["page_id"] for entry in manifest_pages] == ["1", "2,3", "2,3", "4"]
    assert all(entry["file"].endswith(".png") for entry in manifest_pages)
    assert result.archive_path.name.startswith(candidate.artifact_prefix or "")
    with zipfile.ZipFile(result.archive_path) as archive:
        members = archive.namelist()
        assert len(members) == 4
        assert all(name.endswith(".png") for name in members)
    second_plan = BatchPlanner(catalog, executor.policies).plan(site="hanayume", now=BATCH_NOW)
    assert all(item.item_id != candidate.item_id for item in second_plan.candidates)
    assert any(
        skipped.item_id == candidate.item_id and skipped.reason == "completed"
        for skipped in second_plan.skipped
    )
    assert f"/episodes/{TARGET_EPISODE_ID}" in requested


@pytest.mark.parametrize(
    ("variant", "target_badge", "viewer_work_id", "max_pages"),
    [
        ("now-free", "今なら無料", WORK_ID, 10),
        ("wrong-work", "無料", f"{901:013x}", 10),
        ("unknown-slot", "無料", WORK_ID, 10),
        ("premature-end", "無料", WORK_ID, 10),
        ("max-pages", "無料", WORK_ID, 2),
    ],
)
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_batch_failures_never_complete_or_create_artifacts(
    browser_page,
    tmp_path: Path,
    variant: str,
    target_badge: str,
    viewer_work_id: str,
    max_pages: int,
) -> None:
    mutation = {
        "unknown-slot": "unknown-after-advance",
        "premature-end": "early-terminal",
    }.get(variant, "none")
    catalog, _source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page,
        tmp_path,
        target_badge=target_badge,
        viewer_work_id=viewer_work_id,
        mutation=mutation,
    )

    with pytest.raises(BatchExecutionError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=max_pages,
            now=BATCH_NOW,
        )

    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    assert list((tmp_path / "library").rglob("*.zip")) == []
    if variant == "now-free":
        runs = catalog.list_crawl_runs(item_id=candidate.item_id)
        assert len(runs) == 1 and runs[0].status == "failed"
        assert runs[0].page_count is None
        assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_package_failure_keeps_item_pending_without_artifact(
    browser_page, tmp_path: Path
) -> None:
    catalog, _source, candidate, _plan, executor, _requested = await _batch_fixture(
        browser_page, tmp_path
    )

    def fail_package(*_args, **_kwargs):
        raise OSError("synthetic package failure")

    executor.package_function = fail_package
    with pytest.raises(CandidateExecutionError, match="synthetic package failure"):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    assert list((tmp_path / "library").rglob("*.zip")) == []
