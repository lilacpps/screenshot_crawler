from __future__ import annotations

import asyncio
import json
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.batch import BatchExecutor, BatchPlanner
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.errors import (
    AccessConsumptionUnconfirmedError,
    AccessResourceUnavailableError,
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.site_adapters.comicdays import adapter as adapter_module
from screenshot_crawler.site_adapters.comicdays.adapter import ComicDaysAdapter
from screenshot_crawler.site_adapters.comicdays.live_access import (
    ComicDaysLiveAccessError,
    ComicDaysLiveAccessState,
    ComicDaysTargetIdentityMismatch,
    ComicDaysTicketState,
    observe_comicdays_target_access,
)
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import SitePolicyRegistry
from screenshot_crawler.site_policies.comicdays import ComicDaysSitePolicy
from tests.integration.test_comicdays_adapter_browser import RUNNER_HTML

pytestmark = pytest.mark.asyncio(loop_scope="module")

NOW = datetime(2026, 10, 4, 12, tzinfo=JST)


ENTRY_HTML = """
<section class="private-viewer js-viewer" data-json-url="https://comic-days.com/episode/1.json">
  <div id="content"><div class="read-button-container">
    <button data-test-id="use-series-ticket-button" data-ticket-type="series" data-behaviour="button"
            title="作品チケットを使って読む"
            data-ticket-rental-id="1">\u4f5c\u54c1\u30c1\u30b1\u30c3\u30c8\u3067\u8aad\u3080\uff08\u7121\u6599\uff09</button>
    <button data-test-id="purchase-button" data-buy-price="100">購入して読む</button>
  </div><div class="image-container js-viewer-content"><canvas class="page-image js-page-image"></canvas></div></div>
</section>
<div class="js-readable-products-pagination" data-type="episode" data-aggregate-id="1" data-rental-term="259200"></div>
<div data-series-id="1"></div>
"""


def _without_ticket_control(html: str) -> str:
    start = html.index('    <button data-test-id="use-series-ticket-button"')
    end = html.index("</button>", start) + len("</button>")
    return html[:start] + html[end:]


def _with_duplicate_ticket_control(html: str) -> str:
    start = html.index('    <button data-test-id="use-series-ticket-button"')
    end = html.index("</button>", start) + len("</button>")
    control = html[start:end]
    marker = '  </div><div class="image-container'
    return html.replace(marker, f"  {control}\n{marker}", 1)


def _state(
    *, mode: str, charged: bool, changed: bool = False,
    term: object = 72, charged_at: datetime | None = None,
) -> ComicDaysLiveAccessState:
    return ComicDaysLiveAccessState(
        series_id="1",
        episode_id="1",
        row={
            "purchase_info": {
                "can_read": mode == "quota" and not charged,
                "has_rented_via_ticket": mode == "quota" and not charged,
            },
            "status": {"rental_term": term},
        },
        access_mode=mode,
        grant_until=(datetime.now(UTC) + timedelta(hours=72) if mode == "quota" and not charged else None),
        grant_observed=mode == "quota" and not charged,
        ticket=ComicDaysTicketState(
            series_id="1",
            is_charged=charged,
            charged_at=(charged_at if charged_at is not None else (datetime.now(UTC) + timedelta(hours=1) if changed else datetime(1999, 1, 1, tzinfo=UTC))),
        ),
        viewer_unlocked=mode == "quota" and not charged,
        rental_term_hours=(term if isinstance(term, int) and not isinstance(term, bool) else None),
        rental_term_seconds=(term * 3600 if isinstance(term, int) and not isinstance(term, bool) else None),
        canonical_url="https://comic-days.com/episode/1",
        private_viewer_count=0 if changed else 1,
        normal_viewer_count=1 if changed else 0,
        normal_viewer_visible=changed,
        normal_viewer_json="https://comic-days.com/episode/1.json" if changed else None,
        ticket_control_count=0 if changed else 1,
    )


class _ClickRaisesAfterDispatch:
    def __init__(self, locator, error: BaseException) -> None:
        self._locator = locator
        self._error = error

    async def click(self, **kwargs: object) -> None:
        await self._locator.click(**kwargs)
        raise self._error


async def _ticket_page(browser_page, *, html: str = ENTRY_HTML):
    await browser_page.route(
        "https://comic-days.com/episode/1",
        lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html),
    )
    await browser_page.goto("https://comic-days.com/episode/1")
    await browser_page.evaluate("""() => {
      window.__comicDaysProductionCapture = { active: () => ({complete: true, rows: [{renderReady: true}], sliderNow: 1, sliderLast: 1}) };
      document.querySelector('[data-test-id="use-series-ticket-button"]')?.addEventListener('click', () => {
        document.querySelector('section.private-viewer')?.classList.remove('private-viewer');
        document.querySelector('section.js-viewer')?.classList.add('viewer');
      });
    }""")
    return browser_page


async def _observe_real_target_with_graphql(
    page, *, charged: bool, request_urls: list[str]
) -> ComicDaysLiveAccessState:
    class Response:
        status = 200

        async def body(self) -> bytes:
            return json.dumps(
                {
                    "data": {
                        "userAccount": {"eventTicketCount": 1},
                        "series": {
                            "ticket": {
                                "isCharged": charged,
                                "chargedAt": (
                                    "1999-01-01T00:00:00+00:00"
                                    if charged
                                    else (datetime.now(UTC) + timedelta(hours=1)).isoformat()
                                ),
                            }
                        },
                    }
                }
            ).encode()

    class Request:
        async def post(self, url: str, **_kwargs: object) -> Response:
            request_urls.append(url)
            return Response()

    return await observe_comicdays_target_access(
        SimpleNamespace(url=page.url, locator=page.locator, evaluate=page.evaluate, request=Request()),
        series_id="1",
        episode_id="1",
        timeout_ms=2_000,
    )


@pytest.mark.parametrize(
    ("state_name", "html", "charged", "stop_resource_pass"),
    [
        (
            "free",
            ENTRY_HTML.replace(
                'class="private-viewer js-viewer"',
                'class="viewer js-viewer"',
                1,
            ),
            True,
            False,
        ),
        (
            "active_grant",
            ENTRY_HTML.replace(
                'class="private-viewer js-viewer"',
                'class="viewer js-viewer"',
                1,
            ),
            False,
            False,
        ),
        (
            "paid",
            _without_ticket_control(ENTRY_HTML),
            True,
            False,
        ),
        (
            "unsupported_contract",
            ENTRY_HTML.replace(
                'data-rental-term="259200"',
                'data-rental-term="172800"',
                1,
            ),
            True,
            True,
        ),
    ],
)
@pytest.mark.parametrize("entry_only", [True, False])
async def test_comicdays_target_access_mismatch_classifies_entry_scope(
    browser_page,
    monkeypatch: pytest.MonkeyPatch,
    state_name: str,
    html: str,
    charged: bool,
    stop_resource_pass: bool,
    entry_only: bool,
) -> None:
    page = await _ticket_page(browser_page, html=html)
    request_urls: list[str] = []
    await page.evaluate(
        """() => {
          window.ticketClicks = 0; window.paidClicks = 0;
          document.querySelector('[data-test-id=use-series-ticket-button]')
            ?.addEventListener('click', () => window.ticketClicks++);
          document.querySelector('[data-test-id=purchase-button]')
            ?.addEventListener('click', () => window.paidClicks++);
        }"""
    )

    async def observe(self, current_page, _deadline):
        return await _observe_real_target_with_graphql(
            current_page, charged=charged, request_urls=request_urls
        )

    monkeypatch.setattr(ComicDaysAdapter, "_observe_live_access", observe)
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.configure_target_identity("1", "uchu-kyodai")

    with pytest.raises(AccessResourceUnavailableError) as error:
        if entry_only:
            await adapter.initialize_entry_only(page)
        else:
            await adapter.initialize(page)
    assert error.value.stop_resource_pass is stop_resource_pass
    assert "comicdays_discovery_refresh_required" in str(error.value)
    assert await page.evaluate("() => window.ticketClicks") == 0
    assert await page.evaluate("() => window.paidClicks") == 0
    assert request_urls and all(
        "graphql?opname=Viewer_SeriesTicketQuery" in url for url in request_urls
    )
    assert state_name in {"free", "active_grant", "paid", "unsupported_contract"}


async def test_comicdays_real_target_observer_missing_and_dual_viewer_are_unknown(
    browser_page,
) -> None:
    for html in (
        ENTRY_HTML.replace(
            'class="private-viewer js-viewer"',
            'class="viewer js-viewer"',
            1,
        ).replace(
            'data-json-url="https://comic-days.com/episode/1.json"',
            'data-json-url="https://comic-days.com/episode/2.json"',
            1,
        ),
        ENTRY_HTML.replace(
            '</section>',
            '</section><section class="viewer js-viewer" '
            'data-json-url="https://comic-days.com/episode/1.json"></section>',
            1,
        ),
    ):
        page = await _ticket_page(browser_page, html=html)
        with pytest.raises(ComicDaysLiveAccessError):
            await _observe_real_target_with_graphql(
                page, charged=True, request_urls=[]
            )


@pytest.mark.parametrize(
    "html",
    [
        ENTRY_HTML.replace(
            'data-ticket-rental-id="1"',
            'data-ticket-rental-id="1" style="display:none"',
            1,
        ),
        _with_duplicate_ticket_control(ENTRY_HTML),
    ],
)
async def test_comicdays_hidden_or_duplicate_ticket_control_is_unknown(
    browser_page,
    html: str,
) -> None:
    page = await _ticket_page(browser_page, html=html)
    state = await _observe_real_target_with_graphql(
        page, charged=True, request_urls=[]
    )
    assert state.access_mode == "unknown"
    assert state.ticket.is_charged is True


async def test_comicdays_quota_external_id_mismatch_skips_before_navigation(
    browser_page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page)
    navigation_calls: list[str] = []
    real_goto = page.goto

    async def goto(url: str, **kwargs: object):
        navigation_calls.append(url)
        return await real_goto(url, **kwargs)

    monkeypatch.setattr(page, "goto", goto)
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.configure_target_identity("2", "uchu-kyodai")
    with pytest.raises(
        AccessResourceUnavailableError,
        match="comicdays_discovery_refresh_required",
    ) as error:
        adapter.resolve_initial_navigation_url("https://comic-days.com/episode/1")
    assert error.value.stop_resource_pass is False
    assert navigation_calls == []


async def test_comicdays_quota_accepts_arbitrary_stable_work_key_before_navigation(
    browser_page,
) -> None:
    adapter = ComicDaysAdapter()
    await adapter.configure_run(browser_page, "quota")
    await adapter.configure_quota_resource(browser_page, "work_ticket")
    await adapter.configure_target_identity("1", "uchu-kyodai")
    assert adapter.resolve_initial_navigation_url(
        "https://comic-days.com/episode/1"
    ) == "https://comic-days.com/episode/1"


async def test_comicdays_ticket_trace_resets_on_configure_run(browser_page) -> None:
    adapter = ComicDaysAdapter()
    await adapter.configure_target_identity("1", "synthetic-work")
    await adapter.configure_run(browser_page, "quota")
    adapter._record_ticket_trace(browser_page, "entry_error", error_type="Synthetic")
    assert len((await adapter.collect_debug_metadata(browser_page))["ticket_trace"]) == 2

    await adapter.configure_run(browser_page, "quota")
    trace = (await adapter.collect_debug_metadata(browser_page))["ticket_trace"]
    assert [event["phase"] for event in trace] == ["entry_start"]


async def test_comicdays_direct_identity_gate_keeps_arbitrary_work_key_supported(
    browser_page,
) -> None:
    adapter = ComicDaysAdapter()
    await adapter.configure_run(browser_page, "direct")
    await adapter.configure_target_identity("episode", "arbitrary-work")
    assert adapter.resolve_initial_navigation_url(
        "https://comic-days.com/episode/1"
    ) == "https://comic-days.com/episode/1"


@pytest.mark.parametrize("entry_only", [True, False])
async def test_comicdays_live_identity_mismatch_is_candidate_local_before_ticket(
    browser_page,
    monkeypatch: pytest.MonkeyPatch,
    entry_only: bool,
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate(
        "() => { window.ticketClicks = 0; "
        "document.querySelector('[data-test-id=use-series-ticket-button]')"
        ".addEventListener('click', () => window.ticketClicks++); }"
    )

    async def observe_mismatch(*_args: object, **_kwargs: object):
        raise ComicDaysTargetIdentityMismatch(
            "Comic DAYS target work identity did not match"
        )

    monkeypatch.setattr(ComicDaysAdapter, "_observe_live_access", observe_mismatch)
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.configure_target_identity("1", "uchu-kyodai")
    with pytest.raises(
        AccessResourceUnavailableError,
        match="comicdays_discovery_refresh_required",
    ) as error:
        if entry_only:
            await adapter.initialize_entry_only(page)
        else:
            await adapter.initialize(page)
    assert error.value.stop_resource_pass is False
    assert await page.evaluate("() => window.ticketClicks") == 0


async def test_comicdays_ticket_entry_confirms_consumption_and_never_clicks_paid(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(states))
    await page.evaluate("""() => {
      document.querySelector('[data-test-id="purchase-button"]').addEventListener('click', () => window.paidClicked = true);
    }""")
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is True
    assert adapter.get_access_consumption().resource == "work_ticket"
    assert await page.evaluate("() => window.paidClicked === true") is False
    trace = (await adapter.collect_debug_metadata(page))["ticket_trace"]
    assert len(trace) <= adapter.max_ticket_trace_events
    required = {
        "timestamp_utc",
        "monotonic_offset_ms",
        "phase",
        "page_url",
        "expected_episode_id",
        "observed_episode_id",
        "observed_series_id",
    }
    assert all(required <= set(event) for event in trace)
    phases = [event["phase"] for event in trace]
    assert {
        "entry_start",
        "initialize_entry_only_start",
        "pre_observe_start",
        "pre_click_decision",
        "click_start",
        "click_returned",
        "post_click_poll",
        "consumption_confirmed",
        "entry_success",
    } <= set(phases)
    polls = [event for event in trace if event["phase"] == "post_click_poll"]
    assert polls and all(isinstance(event["elapsed_ms"], int) for event in polls)


async def test_comicdays_charged_without_charged_at_fails_before_click(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    state = _state(mode="quota", charged=True)
    state = replace(state, ticket=replace(state.ticket, charged_at=None))
    monkeypatch.setattr(
        adapter_module,
        "observe_comicdays_target_access",
        lambda *_a, **_k: _anext(iter([state])),
    )
    await page.evaluate(
        "() => { window.ticketClicks = 0; "
        "document.querySelector('[data-test-id=use-series-ticket-button]')"
        ".addEventListener('click', () => window.ticketClicks++); }"
    )
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(UnknownPageStateError, match="chargedAt"):
        await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 0
    assert adapter.get_access_consumption().consumed is False


async def test_comicdays_target_observation_uses_dom_and_small_graphql_only(
    browser_page,
) -> None:
    page = await _ticket_page(browser_page)
    requests: list[str] = []

    class Response:
        status = 200

        async def body(self) -> bytes:
            return (
                b'{"data":{"userAccount":{"eventTicketCount":1},'
                b'"series":{"ticket":{"isCharged":true,'
                b'"chargedAt":"2026-10-04T00:00:00+00:00"}}}}'
            )

    class Request:
        async def post(self, url: str, **_kwargs: object) -> Response:
            requests.append(url)
            return Response()

    observed_page = SimpleNamespace(url=page.url, locator=page.locator, evaluate=page.evaluate, request=Request())
    state = await observe_comicdays_target_access(
        observed_page, series_id="1", episode_id="1", timeout_ms=2_000
    )

    assert state.access_mode == "quota"
    assert state.rental_term_seconds == 259200
    assert state.ticket.is_charged is True
    assert len(requests) == 1
    assert all("graphql?opname=Viewer_SeriesTicketQuery" in url for url in requests)
    assert not any(
        marker in url
        for url in requests
        for marker in (
            "/api/viewer/pagination_readable_products",
            "/api/atom",
            "free_only=1",
        )
    )


async def test_comicdays_target_trace_is_metadata_only_and_body_free(browser_page) -> None:
    page = await _ticket_page(browser_page)
    trace: list[tuple[str, dict[str, object]]] = []

    class Response:
        status = 200

        async def body(self) -> bytes:
            return json.dumps(
                {
                    "data": {
                        "userAccount": {"eventTicketCount": 1},
                        "series": {
                            "ticket": {
                                "isCharged": True,
                                "chargedAt": "2026-10-04T00:00:00+00:00",
                            }
                        },
                        "secret": "must-not-enter-trace",
                    }
                }
            ).encode()

    class Request:
        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response()

    observed_page = SimpleNamespace(
        url=page.url,
        locator=page.locator,
        evaluate=page.evaluate,
        request=Request(),
    )
    await observe_comicdays_target_access(
        observed_page,
        series_id="1",
        episode_id="1",
        timeout_ms=2_000,
        trace_sink=lambda phase, fields: trace.append((phase, dict(fields))),
    )

    phases = [phase for phase, _fields in trace]
    assert phases == ["ticket_query_result", "dom_snapshot"]
    ticket = trace[0][1]
    assert ticket["graphql_status"] == 200
    assert isinstance(ticket["elapsed_ms"], int)
    assert ticket["event_ticket_count"] == 1
    dom = trace[1][1]
    assert dom["private_viewer_count"] == 1
    assert dom["normal_viewer_count"] == 0
    assert dom["private_json_matches_expected"] is True
    assert dom["aggregate_ids"] == ["1"]
    assert dom["contract_aggregate_ids"] == ["1"]
    encoded = json.dumps(trace, ensure_ascii=False)
    assert "must-not-enter-trace" not in encoded
    assert "data-json-url" not in encoded
    assert "Cookie" not in encoded


async def test_comicdays_failure_diagnostics_include_ticket_trace(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = await _ticket_page(browser_page)
    monkeypatch.setattr(
        adapter_module,
        "observe_comicdays_target_access",
        lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=True, term=71)])),
    )
    adapter = ComicDaysAdapter()
    from screenshot_crawler.core.models import RunConfig
    from screenshot_crawler.core.runner import CrawlerRunner

    with pytest.raises(AccessResourceUnavailableError):
        await CrawlerRunner(
            RunConfig(
                site="comicdays",
                source_url="https://comic-days.com/episode/1",
                output_dir=tmp_path / "run",
                diagnostics_dir=tmp_path / "run" / "diagnostics",
                entry_only=True,
                access_strategy="quota",
                quota_resource="work_ticket",
            )
        ).run(page, adapter)

    metadata = json.loads(
        (tmp_path / "run" / "diagnostics" / "metadata.json").read_text(encoding="utf-8")
    )
    ticket_trace = metadata["adapter_debug"]["ticket_trace"]
    assert any(event["phase"] == "entry_error" for event in ticket_trace)
    assert all("body" not in event for event in ticket_trace)


async def test_comicdays_target_observation_prioritizes_positive_cooldown(
    browser_page,
) -> None:
    html = ENTRY_HTML.replace(
        'data-ticket-rental-id="1"',
        'data-ticket-rental-id="1" style="display:none"',
    )
    page = await _ticket_page(browser_page, html=html)

    class Response:
        status = 200

        async def body(self) -> bytes:
            return (
                b'{"data":{"userAccount":{"eventTicketCount":0},'
                b'"series":{"ticket":{"isCharged":false,'
                b'"chargedAt":"2026-10-04T00:00:00+00:00"}}}}'
            )

    class Request:
        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response()

    observed_page = SimpleNamespace(url=page.url, locator=page.locator, evaluate=page.evaluate, request=Request())
    state = await observe_comicdays_target_access(
        observed_page, series_id="1", episode_id="1", timeout_ms=2_000
    )
    assert state.access_mode == "quota"
    assert state.ticket.is_charged is False


@pytest.mark.parametrize("post_state", ["removed", "remaining", "hidden", "dual"])
async def test_comicdays_target_observation_rechecks_atomic_dom_after_graphql_swap(
    browser_page, monkeypatch: pytest.MonkeyPatch, post_state: str,
) -> None:
    page = await _ticket_page(browser_page)
    if post_state == "dual":
        transition_script = """() => setTimeout(() => {
          const privateViewer = document.querySelector('section.private-viewer');
          const normalViewer = privateViewer?.cloneNode(true);
          if (normalViewer) {
            normalViewer.className = 'viewer js-viewer';
            privateViewer.parentNode.appendChild(normalViewer);
          }
        }, 30)"""
    else:
        transition_script = f"""() => setTimeout(() => {{
          const privateViewer = document.querySelector('section.private-viewer');
          if (privateViewer) {{
            privateViewer.className = 'viewer js-viewer';
          }}
          const ticket = document.querySelector('[data-test-id="use-series-ticket-button"]');
          {'ticket?.remove();' if post_state == 'removed' else "ticket?.remove(); document.querySelector('section.viewer')?.style.setProperty('visibility', 'hidden');" if post_state == 'hidden' else ''}
        }}, 30)"""
    await page.evaluate(transition_script)

    class Response:
        status = 200

        async def body(self) -> bytes:
            return (
                b'{"data":{"userAccount":{"eventTicketCount":1},'
                b'"series":{"ticket":{"isCharged":false,'
                b'"chargedAt":"2099-01-01T00:00:00+00:00"}}}}'
            )

    class Request:
        async def post(self, _url: str, **_kwargs: object) -> Response:
            await asyncio.sleep(0.15)
            return Response()

    observed_page = SimpleNamespace(
        url=page.url,
        locator=page.locator,
        evaluate=page.evaluate,
        request=Request(),
    )
    if post_state == "dual":
        with pytest.raises(ComicDaysLiveAccessError, match="viewer scopes"):
            await observe_comicdays_target_access(
                observed_page, series_id="1", episode_id="1", timeout_ms=2_000
            )
    else:
        state = await observe_comicdays_target_access(
            observed_page, series_id="1", episode_id="1", timeout_ms=2_000
        )
        assert state.access_mode == "free"
        assert state.private_viewer_count == 0
        assert state.normal_viewer_count == 1
        assert state.normal_viewer_json == "https://comic-days.com/episode/1.json"
        assert state.ticket.is_charged is False
        assert state.ticket.charged_at is not None
        assert state.ticket_control_count == (0 if post_state in {"removed", "hidden"} else 1)
        assert state.normal_viewer_visible is (post_state != "hidden")

    adapter = ComicDaysAdapter()
    adapter._work_id = "1"
    adapter._episode_id = "1"
    observer_calls = 0
    observed_states: list[ComicDaysLiveAccessState] = []

    async def observe(current_page, deadline):
        nonlocal observer_calls
        observer_calls += 1
        state = await observe_comicdays_target_access(
            SimpleNamespace(
                url=current_page.url,
                locator=current_page.locator,
                evaluate=current_page.evaluate,
                request=Request(),
            ),
            series_id="1",
            episode_id="1",
            timeout_ms=2_000,
        )
        observed_states.append(state)
        return state

    monkeypatch.setattr(adapter, "_observe_live_access", observe)
    confirmed = await adapter._reobserve_consumption(
        page, datetime(1999, 1, 1, tzinfo=UTC), asyncio.get_running_loop().time() + 2
    )
    assert observer_calls == 1
    if post_state == "dual":
        assert adapter._live_access is None
        assert confirmed is False
        assert adapter.get_access_consumption().consumed is False
    else:
        assert adapter._live_access is not None
        assert len(observed_states) == 1
        assert adapter._live_access is observed_states[0]
        assert adapter._live_access.ticket.is_charged is False
        assert confirmed is (post_state == "removed")
        assert adapter.get_access_consumption().consumed is (post_state == "removed")


async def test_comicdays_real_planner_executor_grant_only_navigates_once(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    await browser_page.add_init_script(
        """
        document.addEventListener('click', (event) => {
          const node = event.target instanceof Element ? event.target : null;
          if (node?.closest('[data-test-id="use-series-ticket-button"]')) {
            window.ticketClicks = (window.ticketClicks || 0) + 1;
          }
          if (node?.closest('[data-test-id="purchase-button"]')) {
            window.paidClicks = (window.paidClicks || 0) + 1;
          }
          if (node?.closest('[data-test-id="use-series-ticket-button"]')) {
            document.querySelector('section.private-viewer')?.classList.remove('private-viewer');
            document.querySelector('section.js-viewer')?.classList.add('viewer');
            node.closest('[data-test-id="use-series-ticket-button"]')?.remove();
          }
        });
        window.ticketClicks = window.ticketClicks || 0;
        window.paidClicks = window.paidClicks || 0;
        """
    )
    page = await _ticket_page(browser_page)
    navigation_urls: list[str] = []
    page.on(
        "request",
        lambda request: navigation_urls.append(request.url)
        if request.is_navigation_request()
        else None,
    )
    await page.evaluate("() => { window.ticketClicks = 0; window.paidClicks = 0; }")

    graphql_urls: list[str] = []

    async def observe(self, current_page, _deadline):
        return await _observe_real_target_with_graphql(
            current_page,
            charged=not graphql_urls,
            request_urls=graphql_urls,
        )

    monkeypatch.setattr(ComicDaysAdapter, "_observe_live_access", observe)

    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="uchu-kyodai", title="Synthetic work")
    )
    item = catalog.create_item(ItemInput(item_title="Episode 1"), work_id=work.id)
    source = catalog.create_source(
        SourceInput(site="comicdays", external_id="1", access_mode="quota"),
        item_id=item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://comic-days.com/episode/1"),
        source_id=source.id,
    )
    policies = SitePolicyRegistry()
    policies.register("comicdays", ComicDaysSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("comicdays", ComicDaysAdapter)
    planner = BatchPlanner(catalog, policies)
    candidate = planner.plan(site="comicdays", now=NOW).candidates[0]
    result = await BatchExecutor(catalog, policies, adapters).execute_grant_only_candidate(
        page, candidate, output_root=tmp_path / "batch", now=NOW
    )

    assert result.resource_consumed is True
    assert navigation_urls == ["https://comic-days.com/episode/1"]
    assert await page.evaluate("() => window.ticketClicks") == 1
    assert await page.evaluate("() => window.paidClicks") == 0
    assert catalog.get_item(item.id).status == "pending"
    assert catalog.list_artifacts() == []
    entry_trace_files = list(
        (tmp_path / "batch" / "comicdays").glob("*/diagnostics/entry_trace.json")
    )
    assert len(entry_trace_files) == 1
    entry_trace = json.loads(entry_trace_files[0].read_text(encoding="utf-8"))
    assert {
        entry_trace["item_id"],
        entry_trace["source_id"],
        entry_trace["target_id"],
        entry_trace["site"],
        entry_trace["resource"],
    } == {item.id, source.id, candidate.target_id, "comicdays", "work_ticket"}
    assert entry_trace["adapter_debug"]["ticket_trace"]
    state = catalog.get_quota_resource_state(
        work.id, site="comicdays", resource="work_ticket"
    )
    assert state is not None and state.last_consumed_at
    granted_until = datetime.fromisoformat(
        catalog.get_source(source.id).access_granted_until
    )
    consumed_at = datetime.fromisoformat(state.last_consumed_at)
    assert timedelta(hours=70) < granted_until - consumed_at < timedelta(hours=72)
    assert len(graphql_urls) >= 2
    assert all("graphql?opname=Viewer_SeriesTicketQuery" in url for url in graphql_urls)


async def test_comicdays_real_planner_executor_normal_quota_reuses_page(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    await browser_page.add_init_script(
        """
        document.addEventListener('click', (event) => {
          const node = event.target instanceof Element ? event.target : null;
          if (node?.closest('[data-test-id="use-series-ticket-button"]')) {
            window.ticketClicks = (window.ticketClicks || 0) + 1;
          }
          if (node?.closest('[data-test-id="purchase-button"]')) {
            window.paidClicks = (window.paidClicks || 0) + 1;
          }
        });
        window.ticketClicks = window.ticketClicks || 0;
        window.paidClicks = window.paidClicks || 0;
        """
    )
    normal_html = (
        RUNNER_HTML.replace(
            '<section class="private-viewer viewer js-viewer"',
            '<section class="private-viewer js-viewer"',
            1,
        )
        .replace(
            '  <div class="content-inner scroll-horizontal js-horizontal-viewer">',
            """  <div class="read-button-container">
    <button data-test-id="use-series-ticket-button" data-ticket-type="series" data-behaviour="button"
            data-ticket-rental-id="1">作品チケットで読む（無料）</button>
    <button data-test-id="purchase-button" data-buy-price="100">購入して読む</button>
  </div>
  <div class="content-inner scroll-horizontal js-horizontal-viewer">""",
            1,
        )
        .replace(
            "</section>",
            """</section>
<div class="js-readable-products-pagination" data-type="episode" data-aggregate-id="1" data-rental-term="259200"></div>
<div data-series-id="1"></div>
<script>
  document.querySelector('[data-test-id="use-series-ticket-button"]').addEventListener('click', () => {
    document.querySelector('section.private-viewer')?.classList.remove('private-viewer');
    document.querySelector('section.js-viewer')?.classList.add('viewer');
    document.querySelector('[data-test-id="use-series-ticket-button"]')?.remove();
  });
</script>""",
            1,
        )
    )
    await browser_page.route(
        "https://comic-days.com/episode/1",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=normal_html,
        ),
    )
    await browser_page.goto("https://comic-days.com/episode/1")
    page = browser_page
    navigation_urls: list[str] = []
    page.on(
        "request",
        lambda request: navigation_urls.append(request.url)
        if request.is_navigation_request()
        else None,
    )
    await page.evaluate("() => { window.ticketClicks = 0; window.paidClicks = 0; }")

    graphql_urls: list[str] = []

    class Response:
        status = 200

        async def body(self) -> bytes:
            charged = len(graphql_urls) == 1
            charged_at = (
                "1999-01-01T00:00:00+00:00"
                if charged
                else (datetime.now(UTC) + timedelta(hours=1)).isoformat()
            )
            return json.dumps(
                {
                    "data": {
                        "userAccount": {"eventTicketCount": 1},
                        "series": {
                            "ticket": {
                                "isCharged": charged,
                                "chargedAt": charged_at,
                            }
                        },
                    }
                }
            ).encode()

    class Request:
        async def post(self, url: str, **_kwargs: object) -> Response:
            graphql_urls.append(url)
            return Response()

    async def observe(self, current_page, deadline):
        observed_page = SimpleNamespace(
            url=current_page.url,
            locator=current_page.locator,
            evaluate=current_page.evaluate,
            request=Request(),
        )
        return await observe_comicdays_target_access(
            observed_page,
            series_id="1",
            episode_id="1",
            timeout_ms=max(1, int((deadline - asyncio.get_running_loop().time()) * 1000)),
        )

    monkeypatch.setattr(ComicDaysAdapter, "_observe_live_access", observe)

    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="uchu-kyodai", title="Synthetic work")
    )
    item = catalog.create_item(ItemInput(item_title="Episode 1"), work_id=work.id)
    source = catalog.create_source(
        SourceInput(site="comicdays", external_id="1", access_mode="quota"),
        item_id=item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://comic-days.com/episode/1"),
        source_id=source.id,
    )
    policies = SitePolicyRegistry()
    policies.register("comicdays", ComicDaysSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("comicdays", ComicDaysAdapter)
    planner = BatchPlanner(catalog, policies)
    candidate = planner.plan(site="comicdays", now=NOW).candidates[0]

    result = await BatchExecutor(catalog, policies, adapters).execute_candidate(
        page, candidate, output_root=tmp_path / "batch", library_dir=tmp_path / "library", now=NOW
    )

    assert result.artifact_id is not None
    assert catalog.get_item(item.id).status == "completed"
    assert result.page_count == 4
    assert result.archive_path is not None and result.archive_path.exists()
    with zipfile.ZipFile(result.archive_path) as archive:
        assert len(archive.namelist()) == 4
    assert navigation_urls == ["https://comic-days.com/episode/1"]
    assert await page.evaluate("() => window.ticketClicks") == 1
    assert await page.evaluate("() => window.paidClicks") == 0
    assert len(graphql_urls) >= 2
    assert all("graphql?opname=Viewer_SeriesTicketQuery" in url for url in graphql_urls)


async def test_comicdays_ticket_guard_uses_locked_private_viewer_scope(
    browser_page,
) -> None:
    page = await _ticket_page(browser_page, html=ENTRY_HTML.replace(
        'class="private-viewer js-viewer viewer"', 'class="private-viewer js-viewer"'
    ))
    adapter = ComicDaysAdapter()
    adapter._episode_id = "1"
    adapter._work_id = "1"
    control = await adapter._exact_ticket_control(page, asyncio.get_running_loop().time() + 2_000)
    assert await control.count() == 1


async def test_comicdays_ticket_entry_free_state_does_not_click(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(iter([_state(mode="free", charged=True)])))
    clicked = await page.locator('[data-test-id="use-series-ticket-button"]').evaluate(
        "node => { node.addEventListener('click', () => window.ticketClicked = true); return true; }"
    )
    assert clicked is True
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError, match="discovery_refresh_required"):
        await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicked === true") is False
    assert adapter.get_access_consumption().consumed is False


async def test_comicdays_ticket_entry_rejects_hidden_control(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page, html=ENTRY_HTML.replace(
        "data-ticket-rental-id=\"1\"", "data-ticket-rental-id=\"1\" style=\"display:none\""
    ))
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=True)])))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError, match="not_actionable"):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is False


async def test_comicdays_ticket_entry_rejects_disabled_control(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page, html=ENTRY_HTML.replace(
        'data-ticket-rental-id="1"', 'data-ticket-rental-id="1" disabled'
    ))
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=True)])))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError, match="not_actionable"):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is False


async def test_comicdays_ticket_entry_rejects_duplicate_control(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    duplicate = '<button data-test-id="use-series-ticket-button" data-ticket-type="series" data-behaviour="button" title="作品チケットを使って読む" data-ticket-rental-id="1">\u4f5c\u54c1\u30c1\u30b1\u30c3\u30c8\u3067\u8aad\u3080\uff08\u7121\u6599\uff09</button>'
    page = await _ticket_page(browser_page, html=ENTRY_HTML.replace(
        '    <button data-test-id="purchase-button"', duplicate + '\n    <button data-test-id="purchase-button"'
    ))
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=True)])))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError, match="ambiguous"):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('data-json-url="https://comic-days.com/episode/1.json"', 'data-json-url="https://comic-days.com/episode/2.json"'),
        ('data-aggregate-id="1"', 'data-aggregate-id="2"'),
        ('data-ticket-rental-id="1"', 'data-ticket-rental-id="2"'),
        (r"\u4f5c", "x"),
        ('data-behaviour="button"', 'data-buy-price="1" data-behaviour="button"'),
    ],
)
async def test_comicdays_ticket_entry_rejects_identity_label_and_paid_conflicts(
    browser_page, monkeypatch: pytest.MonkeyPatch, old: str, new: str
) -> None:
    html = ENTRY_HTML.replace(chr(0x4F5C), "x") if old == r"\u4f5c" else ENTRY_HTML.replace(old, new)
    page = await _ticket_page(browser_page, html=html)
    monkeypatch.setattr(
        adapter_module,
        "observe_comicdays_target_access",
        lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=True)])),
    )
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is False


async def test_comicdays_grant_only_does_not_require_capture_readiness(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate(
        "() => { window.__comicDaysProductionCapture.active = () => ({rows: [], ready: false}); }"
    )
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_normal_quota_keeps_consumption_when_capture_is_incomplete(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate(
        "() => { window.__comicDaysProductionCapture.active = () => ({rows: [], complete: false, ready: false}); }"
    )
    states = iter([
        _state(mode="quota", charged=True),
        _state(mode="quota", charged=False, changed=True),
    ])
    monkeypatch.setattr(
        adapter_module,
        "observe_comicdays_target_access",
        lambda *_a, **_k: _anext(states),
    )
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(PageChangeTimeoutError):
        await adapter.initialize(page)
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_delayed_viewer_readiness_succeeds_after_one_click(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("""() => {
      window.ticketClicks = 0;
      document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++);
      let polls = 0;
      window.__comicDaysProductionCapture.active = () => ({
        complete: true, rows: [{renderReady: ++polls >= 3}], sliderNow: 1, sliderLast: 1
      });
    }""")
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 1
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_postgrant_identity_mismatch_fails_closed_after_debit(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page, html=ENTRY_HTML.replace(
        'data-json-url="https://comic-days.com/episode/1.json"',
        'data-json-url="https://comic-days.com/episode/2.json"',
    ))
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.parametrize("mutation", ["json", "episode", "work"])
async def test_comicdays_post_debit_identity_mismatch_retains_consumption(
    browser_page, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    page = await _ticket_page(browser_page)
    good = _state(mode="quota", charged=False, changed=True)
    if mutation == "json":
        bad = replace(good, normal_viewer_json="https://comic-days.com/episode/2.json")
    elif mutation == "episode":
        bad = replace(good, episode_id="2")
    else:
        bad = replace(good, series_id="2")
    states = iter([good, bad])
    adapter = ComicDaysAdapter()
    adapter._work_id = "1"
    adapter._episode_id = "1"
    monkeypatch.setattr(adapter, "_observe_live_access", lambda *_a, **_k: _anext(states))
    previous = datetime(1999, 1, 1, tzinfo=UTC)
    assert await adapter._reobserve_consumption(
        page, previous, asyncio.get_running_loop().time() + 2
    ) is True
    assert await adapter._reobserve_consumption(
        page, previous, asyncio.get_running_loop().time() + 2
    ) is False
    consumed_at = adapter.get_access_consumption().consumed_at
    assert adapter.get_access_consumption().consumed is True
    assert consumed_at is not None


async def test_comicdays_detaching_postgrant_read_is_bounded_and_retains_consumption(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page)
    good = _state(mode="quota", charged=False, changed=True)
    bad = replace(good, viewer_unlocked=False, normal_viewer_count=0, normal_viewer_visible=False)
    states = iter([good, bad])
    adapter = ComicDaysAdapter()
    adapter._work_id = "1"
    adapter._episode_id = "1"
    monkeypatch.setattr(adapter, "_observe_live_access", lambda *_a, **_k: _anext(states))
    previous = datetime(1999, 1, 1, tzinfo=UTC)
    assert await adapter._reobserve_consumption(
        page, previous, asyncio.get_running_loop().time() + 2
    ) is True
    assert await adapter._reobserve_consumption(
        page, previous, asyncio.get_running_loop().time() + 2
    ) is False
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_grant_only_success_does_not_depend_on_viewer_readiness_callback(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(states))

    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 1
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_consumed_timestamp_is_latched_across_readonly_polls(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page)
    adapter = ComicDaysAdapter()
    adapter._work_id = "1"
    adapter._episode_id = "1"
    first = _state(mode="quota", charged=False, changed=True)
    second = _state(mode="quota", charged=False, changed=True)
    states = iter([first, second])
    monkeypatch.setattr(adapter, "_observe_live_access", lambda *_a, **_k: _anext(states))
    previous = datetime(1999, 1, 1, tzinfo=UTC)
    assert await adapter._reobserve_consumption(page, previous, asyncio.get_running_loop().time() + 2) is True
    consumed_at = adapter.get_access_consumption().consumed_at
    assert consumed_at is not None
    assert await adapter._reobserve_consumption(page, previous, asyncio.get_running_loop().time() + 2) is True
    assert adapter.get_access_consumption().consumed_at == consumed_at


async def test_comicdays_entry_never_retries_after_click_attempt(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate(
        "() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }"
    )
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.initialize_entry_only(page)
    with pytest.raises(UnsupportedAccessStrategyError, match="already attempted"):
        await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 1


@pytest.mark.parametrize("error_kind", ["timeout", "cancel"])
async def test_comicdays_click_failure_reconciles_without_retry(
    browser_page, monkeypatch: pytest.MonkeyPatch, error_kind: str
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(states))
    error: BaseException = PlaywrightTimeoutError("post-dispatch timeout") if error_kind == "timeout" else asyncio.CancelledError()
    real_locator = page.locator('[data-test-id="use-series-ticket-button"]')

    async def exact(*_args: object, **_kwargs: object):
        return _ClickRaisesAfterDispatch(real_locator, error)

    monkeypatch.setattr(ComicDaysAdapter, "_exact_ticket_control", exact)
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(type(error)):
        await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 1
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_confirmation_cancellation_reconciles_after_click_returns(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(states))
    original_poll = ComicDaysAdapter._poll_consumption
    poll_calls = 0

    async def cancel_during_confirmation(self, page, previous_charged_at, deadline):
        nonlocal poll_calls
        poll_calls += 1
        if poll_calls == 1:
            raise asyncio.CancelledError()
        return await original_poll(self, page, previous_charged_at, deadline)

    monkeypatch.setattr(ComicDaysAdapter, "_poll_consumption", cancel_during_confirmation)
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(asyncio.CancelledError):
        await adapter.initialize_entry_only(page)
    assert poll_calls == 2
    assert await page.evaluate("() => window.ticketClicks") == 1
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_delayed_native_poststate_is_polled_once_per_attempt(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    states = iter([
        _state(mode="quota", charged=True),
        _state(mode="quota", charged=True),
        _state(mode="quota", charged=False, changed=True),
    ])
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 1
    assert adapter.get_access_consumption().consumed is True


@pytest.mark.parametrize("term", [None, True, "72", 71, 73])
async def test_comicdays_unsupported_native_term_never_clicks(
    browser_page, monkeypatch: pytest.MonkeyPatch, term: object
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=True, term=term)])))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError, match="discovery_refresh_required"):
        await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 0


async def test_comicdays_preexisting_active_grant_does_not_consume(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=False, changed=True)])))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError, match="work_ticket_cooldown"):
        await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 0
    assert adapter.get_access_consumption().consumed is False


async def test_comicdays_unsupported_resource_is_rejected(browser_page) -> None:
    adapter = ComicDaysAdapter()
    await adapter.configure_run(browser_page, "quota")
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_quota_resource(browser_page, "premium_ticket")


@pytest.mark.parametrize(
    "post_time", [datetime(2026, 1, 1, tzinfo=UTC), datetime(1999, 1, 1, tzinfo=UTC)]
)
async def test_comicdays_past_or_unchanged_recharge_is_not_consumed(
    browser_page, monkeypatch: pytest.MonkeyPatch, post_time: datetime
) -> None:
    page = await _ticket_page(browser_page)
    states = iter([
        _state(mode="quota", charged=True),
        _state(mode="quota", charged=False, changed=True, charged_at=post_time),
    ])
    monkeypatch.setattr(adapter_module, "observe_comicdays_target_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    adapter.page_change_timeout_ms = 500
    adapter.ticket_recovery_window_ms = 10
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessConsumptionUnconfirmedError):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is False


async def _anext(iterator):
    return next(iterator)
