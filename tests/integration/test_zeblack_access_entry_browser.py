from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.async_api import Page

from screenshot_crawler import cli
from screenshot_crawler.batch import (
    BatchExecutionError,
    BatchExecutor,
    BatchPlanner,
    CandidateExecutionError,
)
from screenshot_crawler.batch.metrics import BatchMetricsWriter
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.core.errors import UnsupportedAccessStrategyError
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_adapters.zeblack.adapter import ZeblackAdapter
from screenshot_crawler.site_adapters.zeblack.discovery_protobuf import (
    ConsumptionStatus,
    ZeblackChapterV3,
)
from screenshot_crawler.site_adapters.zeblack.live_access import (
    ZeblackChapterListSnapshot,
    ZeblackLiveAccessState,
)
from screenshot_crawler.site_policies import SitePolicyRegistry, ZeblackSitePolicy
from screenshot_crawler.watchlist.service import WatchlistService

pytestmark = pytest.mark.asyncio(loop_scope="module")

LIST_URL = "https://zebrack-comic.shueisha.co.jp/title/3890/chapter/list"
TARGET_URL = "https://zebrack-comic.shueisha.co.jp/title/3890/chapter/58493/viewer"
MAIN_NAME = "第25話 プロの実力"
HYDRATION_LIST_URL = "https://zebrack-comic.shueisha.co.jp/title/11551/chapter/list"
HYDRATION_TARGET_URL = (
    "https://zebrack-comic.shueisha.co.jp/title/11551/chapter/630652/viewer"
)
HYDRATION_MAIN_NAME = "個人指導3"


def _prepared_catalog(tmp_path: Path):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="prepared-work", title="作品名"))
    for chapter_id in ("58493", "58494"):
        item = catalog.create_item(ItemInput(order_label=MAIN_NAME), work_id=work.id)
        source = catalog.create_source(
            SourceInput(site="zeblack", external_id=chapter_id, access_mode="quota",
                        discovery_key="prepared-target"), item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(backend="web", locator=TARGET_URL.replace("58493", chapter_id)),
            source_id=source.id,
        )
    policies = SitePolicyRegistry()
    policies.register("zeblack", ZeblackSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("zeblack", ZeblackAdapter)
    executor = BatchExecutor(catalog, policies, adapters)
    candidates = BatchPlanner(catalog, policies).plan(site="zeblack").candidates
    return catalog, executor, candidates


async def _install_prepared_observation(
    page: Page, monkeypatch, *, paid: bool = False, free_ticket_ui: bool = False,
):
    navigations: list[str] = []
    observations: list[Page] = []

    async def fulfill(route):
        navigations.append(route.request.url)
        html = _chapter_list_html(
            paid_control="ポイントを使って読む" if paid else None,
            free_ticket_ui=free_ticket_ui,
        )
        html = html.replace(
            "document.body.innerHTML = '<img alt=\"page_1\" src=\"data:image/gif;base64,"
            "R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==\">';",
            "document.body.innerHTML = '<img alt=\"page_1\">';"
            "const bytes = Uint8Array.from(atob('R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=='),"
            "c => c.charCodeAt(0));"
            "document.querySelector('img').src = URL.createObjectURL(new Blob([bytes], {type:'image/gif'}));",
        )
        await route.fulfill(
            status=200, content_type="text/html; charset=utf-8",
            body=html
            + '<script>window.ticketClicks = 0; document.addEventListener("click", e => {'
            + 'if (["チケットを使って読む", "無料チケットを使って読む"].includes(e.target.textContent)) '
            + 'window.ticketClicks++;});</script>',
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)

    async def observe(observed_page: Page, *, title_id: str, **_kwargs):
        observations.append(observed_page)
        assert title_id == "3890"
        await observed_page.goto(LIST_URL, wait_until="domcontentloaded")
        document = await observed_page.locator("html").element_handle()
        return ZeblackChapterListSnapshot("3890", (
            ZeblackChapterV3("58493", "3890", MAIN_NAME, None,
                            int(ConsumptionStatus.TICKET_AVAILABLE), None),
        ), document=document)

    async def forbidden_reload(*_args, **_kwargs):
        pytest.fail("Prepared entry must not reload the chapter list")

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.access_resolver.observe_zeblack_chapter_list", observe
    )
    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access", forbidden_reload
    )
    return navigations, observations


@pytest.mark.parametrize("free_ticket_ui", [False, True], ids=["legacy", "free_ticket"])
@pytest.mark.parametrize("normal_batch,finalization_fails,capture_fails", [
    (False, False, False), (False, True, False),
    (True, False, False), (True, True, False), (True, False, True),
], ids=["grant_only", "grant_only_finalization", "normal_batch", "normal_finalization", "normal_capture"])
async def test_zeblack_cli_single_list_load_then_work_cooldown_without_site_access(
    browser_page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    finalization_fails: bool,
    free_ticket_ui: bool,
    normal_batch: bool,
    capture_fails: bool,
) -> None:
    catalog, _executor, candidates = _prepared_catalog(tmp_path)
    navigations, observations = await _install_prepared_observation(
        browser_page, monkeypatch, free_ticket_ui=free_ticket_ui,
    )
    watchlist_path = tmp_path / "watchlist.yaml"
    WatchlistService(watchlist_path).add(
        key="prepared-target", work_key="prepared-work", site="zeblack",
        url=LIST_URL, label="最新label",
    )
    pages: list[Page] = []
    ticket_clicks: list[int] = []

    class Session:
        @classmethod
        async def connect(cls, _endpoint):
            return cls()

        async def new_page(self):
            page = browser_page if not pages else await browser_page.context.new_page()
            pages.append(page)
            assert len(pages) <= (2 if normal_batch else 1)
            return page

        async def close_page(self, page):
            if page is browser_page:
                ticket_clicks.append(await page.evaluate("window.ticketClicks"))
            await page.close()

        async def close(self):
            pass

    monkeypatch.setattr(cli, "BrowserSession", Session)
    monkeypatch.setattr(cli, "BatchMetricsWriter", lambda *_args, **kwargs: BatchMetricsWriter(
        tmp_path / "metrics", **kwargs
    ))
    async def capture_new_grant(self, page, candidate, **_kwargs):
        # This test exercises the real resolver/entry handoff. Capture itself is
        # covered by viewer integration tests; assert Phase C only sees the grant.
        assert normal_batch and candidate.source_id == candidates[0].source_id
        assert candidate.access_strategy == "direct" and page is not browser_page
        if capture_fails:
            raise CandidateExecutionError("synthetic capture failure")
        catalog.mark_item_completed(candidate.item_id)
        return SimpleNamespace(archive_path=Path("synthetic.zip"), stop_reason="end")

    monkeypatch.setattr(BatchExecutor, "execute_candidate", capture_new_grant)
    args = cli._parser().parse_args([
        "batch", "run", "--site", "zeblack", "--grant-only", "work_ticket",
        "--catalog", str(tmp_path / "catalog.sqlite"), "--watchlist", str(watchlist_path),
        "--env-file", str(tmp_path / "missing.env"),
    ])
    if normal_batch:
        args.grant_only = None
    if finalization_fails:
        def fail_finalization(*_args, **_kwargs):
            raise OSError("synthetic finalization failure")
        monkeypatch.setattr(CatalogService, "mark_crawl_run_succeeded", fail_finalization)
        with pytest.raises(BatchExecutionError, match="synthetic finalization failure"):
            await cli._run_batch_run(args)
    elif capture_fails:
        with pytest.raises(BatchExecutionError, match="synthetic capture failure"):
            await cli._run_batch_run(args)
    else:
        await cli._run_batch_run(args)
    first_output = capsys.readouterr().out
    assert "OK  最新label" in first_output
    heading = "Grant results:" if normal_batch else "Grant-only results:"
    assert first_output.count(heading) == 1
    assert "OK  最新label" in first_output.split(heading)[1]
    if finalization_fails:
        assert "後処理失敗" in first_output
    elif normal_batch:
        assert "post-grant direct" in first_output
    assert navigations == [LIST_URL]
    assert observations == [browser_page]
    assert ticket_clicks == [1]
    state = catalog.get_quota_resource_state(
        candidates[0].work_id, site="zeblack", resource="work_ticket"
    )
    assert state is not None
    consumed_at = datetime.fromisoformat(state.last_consumed_at)
    assert catalog.get_source(candidates[0].source_id).quota_started_at == state.last_consumed_at
    assert catalog.list_artifacts() == []
    assert catalog.get_item(candidates[0].item_id).status == (
        "completed" if normal_batch and not finalization_fails and not capture_fails else "pending"
    )
    assert catalog.get_item(candidates[1].item_id).status == "pending"
    assert _executor.grant_only_skip_reason(candidates[1], now=consumed_at + timedelta(hours=23)) is None
    page_count = len(pages)
    # Test consuming entry's local gate independently of normal Batch's direct
    # retries after a finalization failure, which legitimately remain readable.
    args.grant_only = "work_ticket"
    await cli._run_batch_run(args)
    output = capsys.readouterr().out
    assert "SKIP  最新label" in output
    assert "次回確認可能:" in output
    assert navigations == [LIST_URL] and len(pages) == page_count and ticket_clicks == [1]


@pytest.mark.parametrize("fault", [
    "reload", "wrong_page", "wrong_target", "used", "paid", "guard_stop", "adapter_declines",
])
async def test_zeblack_prepared_entry_rejects_changed_state_without_spending(
    browser_page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    from dataclasses import replace

    catalog, executor, candidates = _prepared_catalog(tmp_path)
    await _install_prepared_observation(browser_page, monkeypatch, paid=fault == "paid")
    events = []
    executor.access_event_sink = events.append
    prepared = None
    with pytest.raises((BatchExecutionError, UnsupportedAccessStrategyError)):
        async with executor.prepare_access_resource_candidates(
            browser_page, candidates, "work_ticket"
        ) as prepared:
            candidate = candidates[0]
            page = browser_page
            if fault == "reload":
                await page.reload()
            elif fault == "wrong_page":
                page = await browser_page.context.new_page()
            elif fault == "wrong_target":
                candidate = replace(candidate, locator=TARGET_URL.replace("58493", "58494"))
            elif fault == "used":
                prepared.take(page, candidate)
            elif fault == "guard_stop":
                prepared.guard._stop(reason="http_429", url=LIST_URL, status=429)
            elif fault == "adapter_declines":
                async def decline(*_args):
                    return False
                monkeypatch.setattr(prepared.adapter, "adopt_prepared_access_entry", decline)
            await executor.execute_grant_only_candidate(
                page, candidate, prepared_access=prepared, output_root=tmp_path / "batch"
            )
    assert await browser_page.evaluate("window.ticketClicks") == 0
    assert catalog.get_quota_resource_state(
        candidates[0].work_id, site="zeblack", resource="work_ticket"
    ) is None
    assert catalog.get_source(candidates[0].source_id).quota_started_at is None
    assert prepared is not None and not prepared.active
    assert prepared.guard._page is None and prepared.guard._monitor_task is None
    assert len([event for event in events if event.event_type == "request"]) == (2 if fault == "reload" else 1)


def _chapter_list_html(
    *,
    unrelated_node_count: int = 0,
    ticket_count: int = 1,
    paid_control: str | None = None,
    modal_main_name: str = MAIN_NAME,
    include_cancel: bool = True,
    free_ticket_ui: bool = False,
    extra_ticket_text: str | None = None,
    cancel_count: int = 1,
    ticket_disabled: bool = False,
) -> str:
    unrelated_nodes = "".join(
        f'<div class="junk" data-index="{index}">unrelated-{index}</div>'
        for index in range(unrelated_node_count)
    )
    ticket_text = "無料チケットを使って読む" if free_ticket_ui else "チケットを使って読む"
    tag = "button" if free_ticket_ui else "div"
    disabled = (
        (' disabled' if free_ticket_ui else ' role="button" aria-disabled="true"')
        if ticket_disabled else ""
    )
    ticket_controls = "".join(
        f'<{tag} class="ticket"{disabled}>{ticket_text}</{tag}>'
        for _ in range(ticket_count)
    )
    if extra_ticket_text is not None:
        ticket_controls += f'<button class="ticket">{extra_ticket_text}</button>'
    paid_markup = f'<div>{paid_control}</div>' if paid_control else ""
    cancel_control = (
        '<button type="button" aria-label="閉じる"></button>'
        if free_ticket_ui
        else '<button type="button">キャンセル</button>'
    )
    cancel_markup = cancel_control * cancel_count if include_cancel else ""
    return f"""
    {unrelated_nodes}
    <div id="chapter58493"><p>{MAIN_NAME}</p></div>
    <script>
      const listUrl = {LIST_URL!r};
      const targetUrl = {TARGET_URL!r};
      const row = document.querySelector('#chapter58493');
      row.querySelector('p').addEventListener('click', () => {{
        row.insertAdjacentHTML('afterend', `
          <div id="modal-root">
            <div>{modal_main_name}</div>
            {ticket_controls}
            {cancel_markup}
            {paid_markup}
          </div>`);
        document.querySelector('#modal-root .ticket').addEventListener('click', () => {{
          history.pushState({{}}, '', targetUrl);
          document.body.innerHTML = '<img alt="page_1" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==">';
        }});
      }});
    </script>
    """


def _chapter_list_with_direct_link_html() -> str:
    return f"""
    <div id="chapter58493">
      <a href="{TARGET_URL}"><p>{MAIN_NAME}</p></a>
    </div>
    """


def _hydrating_chapter_list_html(*, row_mode: str, main_mode: str) -> str:
    row_markup = ""
    if row_mode == "present":
        row_markup = (
            '<div id="chapter630652" style="min-height: 1px;">'
            f"{('<p>' + HYDRATION_MAIN_NAME + ' </p>') if main_mode == 'present' else ''}"
            "</div>"
        )
    elif row_mode == "ambiguous":
        row_markup = (
            '<div id="chapter630652" style="min-height: 1px;"></div>'
            '<div id="chapter630652" style="min-height: 1px;"></div>'
        )
    delayed_row = "" if row_mode != "delayed" else """
      window.setTimeout(() => {
        const row = document.createElement('div');
        row.id = 'chapter630652';
        row.style.minHeight = '1px';
        document.body.appendChild(row);
        window.setTimeout(() => {
          row.innerHTML = '<p>個人指導3 </p>';
        }, 150);
      }, 150);
    """
    delayed_main = "" if main_mode != "delayed" else """
      window.setTimeout(() => {
        document.querySelector('#chapter630652').innerHTML = '<p>個人指導3 </p>';
      }, 150);
    """
    return f"""
    {row_markup}
    <script>
      window.chapterClicks = 0;
      document.addEventListener('click', event => {{
        if (event.target.closest('#chapter630652')) window.chapterClicks += 1;
      }});
      {delayed_row}
      {delayed_main}
    </script>
    """


async def _hydration_adapter(
    page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> ZeblackAdapter:
    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    assert adapter.resolve_initial_navigation_url(HYDRATION_TARGET_URL) == HYDRATION_LIST_URL
    adapter._live_access = ZeblackLiveAccessState(
        title_id="11551",
        chapter_id="630652",
        target_main_name=HYDRATION_MAIN_NAME,
        status_value=2,
        status_name="TICKET_AVAILABLE",
        ticket_available_ids=("630652",),
    )
    adapter._target_main_name = HYDRATION_MAIN_NAME
    adapter.page_change_timeout_ms = 1_000

    async def wait_for_modal(_page: Page, **_kwargs: object):
        return page.locator("#chapter630652")

    monkeypatch.setattr(adapter, "_wait_for_ticket_modal", wait_for_modal)
    return adapter


@pytest.mark.parametrize(
    "unrelated_node_count",
    [0, 2500],
    ids=["normal_dom", "large_dom"],
)
@pytest.mark.parametrize("free_ticket_ui", [False, True], ids=["legacy", "free_ticket"])
async def test_zeblack_work_ticket_entry_uses_modal_then_target_viewer(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    unrelated_node_count: int,
    free_ticket_ui: bool,
) -> None:
    page = browser_page
    navigation_urls: list[str] = []

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        navigation_urls.append(route.request.url)
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_chapter_list_html(
                unrelated_node_count=unrelated_node_count,
                free_ticket_ui=free_ticket_ui,
            ),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(LIST_URL)

    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    assert adapter.resolve_initial_navigation_url(TARGET_URL) == LIST_URL

    async def observe(_page: Page, **_kwargs: object) -> ZeblackLiveAccessState:
        return ZeblackLiveAccessState(
            title_id="3890",
            chapter_id="58493",
            target_main_name=MAIN_NAME,
            status_value=2,
            status_name="TICKET_AVAILABLE",
            ticket_available_ids=("58493",),
        )

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access",
        observe,
    )

    async def stable_content(_page: Page) -> None:
        return None

    monkeypatch.setattr(adapter, "_wait_for_initial_content", stable_content)
    await adapter._initialize_quota_entry(page, entry_only=True)

    assert page.url == TARGET_URL
    assert navigation_urls == [LIST_URL]
    assert adapter._chapter_click_attempted is True
    assert adapter._ticket_click_attempted is True
    assert adapter.get_access_consumption().consumed is True
    assert adapter.get_access_consumption().resource == "work_ticket"


async def test_zeblack_target_chapter_waits_for_delayed_row_hydration(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_hydrating_chapter_list_html(row_mode="delayed", main_mode="delayed"),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(HYDRATION_LIST_URL)
    adapter = await _hydration_adapter(page, monkeypatch)

    await adapter._click_target_chapter(page)

    assert await page.evaluate("window.chapterClicks") == 1
    assert adapter._chapter_click_attempted is True


async def test_zeblack_target_chapter_waits_for_delayed_main_name_hydration(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_hydrating_chapter_list_html(row_mode="present", main_mode="delayed"),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(HYDRATION_LIST_URL)
    adapter = await _hydration_adapter(page, monkeypatch)

    await adapter._click_target_chapter(page)

    assert await page.evaluate("window.chapterClicks") == 1
    assert adapter._chapter_click_attempted is True


async def test_zeblack_target_chapter_trims_observed_main_name_whitespace(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_hydrating_chapter_list_html(row_mode="present", main_mode="present"),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(HYDRATION_LIST_URL)
    adapter = await _hydration_adapter(page, monkeypatch)
    adapter._live_access = ZeblackLiveAccessState(
        title_id="11551",
        chapter_id="630652",
        target_main_name=f"{HYDRATION_MAIN_NAME} ",
        status_value=2,
        status_name="TICKET_AVAILABLE",
        ticket_available_ids=("630652",),
    )

    await adapter._click_target_chapter(page)

    assert await page.evaluate("window.chapterClicks") == 1
    assert adapter._chapter_click_attempted is True


async def test_zeblack_target_chapter_missing_main_name_fails_closed(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_hydrating_chapter_list_html(row_mode="present", main_mode="missing"),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(HYDRATION_LIST_URL)
    adapter = await _hydration_adapter(page, monkeypatch)
    adapter.page_change_timeout_ms = 300

    with pytest.raises(
        UnsupportedAccessStrategyError,
        match="mainName did not become ready",
    ):
        await adapter._click_target_chapter(page)

    assert await page.evaluate("window.chapterClicks") == 0
    assert adapter._chapter_click_attempted is False


async def test_zeblack_target_chapter_ambiguous_row_fails_immediately(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_hydrating_chapter_list_html(row_mode="ambiguous", main_mode="missing"),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(HYDRATION_LIST_URL)
    adapter = await _hydration_adapter(page, monkeypatch)

    with pytest.raises(UnsupportedAccessStrategyError, match="row is ambiguous"):
        await adapter._click_target_chapter(page)

    assert await page.evaluate("window.chapterClicks") == 0
    assert adapter._chapter_click_attempted is False


async def test_zeblack_target_chapter_ambiguous_main_name_fails_immediately(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body="""
            <div id="chapter630652" style="min-height: 1px;">
              <p>個人指導3</p><p>個人指導3</p>
            </div>
            <script>window.chapterClicks = 0;</script>
            """,
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(HYDRATION_LIST_URL)
    adapter = await _hydration_adapter(page, monkeypatch)

    with pytest.raises(
        UnsupportedAccessStrategyError,
        match="mainName is ambiguous",
    ):
        await adapter._click_target_chapter(page)

    assert await page.evaluate("window.chapterClicks") == 0
    assert adapter._chapter_click_attempted is False


@pytest.mark.parametrize(
    ("ticket_count", "paid_control", "mixed_labels", "ticket_disabled"),
    [
        (2, None, False, False),
        (1, "ポイントを使って読む", False, False),
        (1, "アイテムを使って読む", False, False),
        (1, "コインを使って読む", False, False),
        (1, "コインを購入する", False, False),
        (1, None, True, False),
        (1, None, False, True),
    ],
    ids=["ambiguous_ticket", "point", "item", "coin", "purchase", "mixed", "disabled"],
)
@pytest.mark.parametrize("free_ticket_ui", [False, True], ids=["legacy", "free_ticket"])
async def test_zeblack_modal_identity_rejects_ambiguous_or_paid_controls(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    ticket_count: int,
    paid_control: str | None,
    mixed_labels: bool,
    ticket_disabled: bool,
    free_ticket_ui: bool,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_chapter_list_html(
                ticket_count=ticket_count,
                paid_control=paid_control,
                free_ticket_ui=free_ticket_ui,
                extra_ticket_text=(
                    ("チケットを使って読む" if free_ticket_ui else "無料チケットを使って読む")
                    if mixed_labels else None
                ),
                ticket_disabled=ticket_disabled,
            ),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(LIST_URL)

    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    assert adapter.resolve_initial_navigation_url(TARGET_URL) == LIST_URL

    async def observe(_page: Page, **_kwargs: object) -> ZeblackLiveAccessState:
        return ZeblackLiveAccessState(
            title_id="3890",
            chapter_id="58493",
            target_main_name=MAIN_NAME,
            status_value=2,
            status_name="TICKET_AVAILABLE",
            ticket_available_ids=("58493",),
        )

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access",
        observe,
    )
    adapter.page_change_timeout_ms = 500

    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter._initialize_quota_entry(page, entry_only=True)

    assert page.url == LIST_URL
    assert adapter._chapter_click_attempted is True
    assert adapter._ticket_click_attempted is False
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.parametrize("free_ticket_ui", [False, True], ids=["legacy", "free_ticket"])
@pytest.mark.parametrize(
    ("modal_main_name", "include_cancel", "cancel_count"),
    [("別の章", True, 1), (MAIN_NAME, False, 1), (MAIN_NAME, True, 2)],
    ids=["wrong_target", "missing_dismiss", "ambiguous_dismiss"],
)
async def test_zeblack_modal_scope_requires_target_and_cancel_identity(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    free_ticket_ui: bool,
    modal_main_name: str,
    include_cancel: bool,
    cancel_count: int,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_chapter_list_html(
                modal_main_name=modal_main_name,
                include_cancel=include_cancel,
                cancel_count=cancel_count,
                free_ticket_ui=free_ticket_ui,
            ),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(LIST_URL)

    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    assert adapter.resolve_initial_navigation_url(TARGET_URL) == LIST_URL

    async def observe(_page: Page, **_kwargs: object) -> ZeblackLiveAccessState:
        return ZeblackLiveAccessState(
            title_id="3890",
            chapter_id="58493",
            target_main_name=MAIN_NAME,
            status_value=2,
            status_name="TICKET_AVAILABLE",
            ticket_available_ids=("58493",),
        )

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access",
        observe,
    )
    adapter.page_change_timeout_ms = 500

    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter._initialize_quota_entry(page, entry_only=True)

    assert page.url == LIST_URL
    assert adapter._chapter_click_attempted is True
    assert adapter._ticket_click_attempted is False
    assert adapter.get_access_consumption().consumed is False


async def test_zeblack_direct_viewer_link_is_rejected_before_chapter_click(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    navigation_urls: list[str] = []

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        navigation_urls.append(route.request.url)
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_chapter_list_with_direct_link_html(),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(LIST_URL)

    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    assert adapter.resolve_initial_navigation_url(TARGET_URL) == LIST_URL

    async def observe(_page: Page, **_kwargs: object) -> ZeblackLiveAccessState:
        return ZeblackLiveAccessState(
            title_id="3890",
            chapter_id="58493",
            target_main_name=MAIN_NAME,
            status_value=2,
            status_name="TICKET_AVAILABLE",
            ticket_available_ids=("58493",),
        )

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access",
        observe,
    )

    with pytest.raises(
        UnsupportedAccessStrategyError,
        match="direct navigation link",
    ):
        await adapter._initialize_quota_entry(page, entry_only=True)

    assert page.url == LIST_URL
    assert navigation_urls == [LIST_URL]
    assert adapter._chapter_click_attempted is False
    assert adapter._ticket_click_attempted is False
    assert adapter.get_access_consumption().consumed is False
