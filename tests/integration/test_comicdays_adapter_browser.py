from __future__ import annotations

import asyncio
from urllib.parse import quote

import pytest

from screenshot_crawler.core.errors import PageChangeTimeoutError
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.comicdays import adapter as adapter_module
from screenshot_crawler.site_adapters.comicdays import discovery as discovery_module
from screenshot_crawler.site_adapters.comicdays.adapter import ComicDaysAdapter
from screenshot_crawler.watchlist.models import WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")


HTML = """
<section class="viewer js-viewer">
  <div class="content-inner scroll-horizontal js-horizontal-viewer">
    <div class="image-container js-viewer-content is-spread">
      <div class="page-area js-page-area" id="ad"><a href="/episode/999">ad</a></div>
      <div class="page-area js-page-area" id="body-one"><canvas class="page-image js-page-image"></canvas></div>
      <div class="page-area js-page-area" id="body-two" style="display:none;position:absolute;left:300px"><canvas class="page-image js-page-image"></canvas></div>
      <div class="page-area js-page-area" id="body-three" style="display:none;position:absolute;left:0"><canvas class="page-image js-page-image"></canvas></div>
      <div class="page-area js-page-area" id="questionnaire"><img alt="ad"></div>
      <div class="page-area js-page-area" id="viewer-colophon" style="display:none;width:300px;height:300px"></div>
    </div>
  </div>
  <span class="js-viewer-slider-pagenum-now">1</span><span class="js-viewer-slider-pagenum-last">5</span>
  <button class="page-navigation-backward js-slide-backward" disabled>back</button>
  <button class="page-navigation-forward js-slide-forward">next</button>
</section>
<h1 class="series-header-title">Synthetic Work</h1>
<script>
  const now = document.querySelector('.js-viewer-slider-pagenum-now');
  const one = document.querySelector('#body-one'); const two = document.querySelector('#body-two'); const three = document.querySelector('#body-three');
  const end = document.querySelector('#viewer-colophon');
  document.querySelector('.js-slide-forward').onclick = () => {
    const n = Number(now.textContent) + 2; now.textContent = String(n);
    if (n === 3) { one.style.display='none'; two.style.display='block'; three.style.display='block'; }
    if (n >= 5) { two.style.display='none'; end.style.display='block'; }
  };
</script>
"""


RUNNER_HTML = HTML.replace(
    "if (n === 3) { one.style.display='none'; two.style.display='block'; three.style.display='block'; }",
    "if (n === 3) { one.style.display='none'; two.style.display='block'; three.style.display='block'; window.paintRunner?.(); }",
).replace(
    "</script>",
    """
  window.paintRunner = async () => {
    const sourceCanvas = document.createElement('canvas'); sourceCanvas.width=10; sourceCanvas.height=8;
    const source = sourceCanvas.getContext('2d'); source.fillStyle='#e22'; source.fillRect(0,0,5,5);
    source.fillStyle='#2e2'; source.fillRect(5,0,5,5); source.fillStyle='#22e'; source.fillRect(0,5,5,5);
    source.fillStyle='#ee2'; source.fillRect(5,5,5,5);
    const blob = await new Promise(resolve => sourceCanvas.toBlob(resolve, 'image/png'));
    const url = URL.createObjectURL(blob);
    await Promise.all([...document.querySelectorAll('canvas.page-image')].map(canvas => new Promise(resolve => {
      const image = new Image(); image.onload = () => {
        const ctx=canvas.getContext('2d'); canvas.width=10; canvas.height=8; ctx.drawImage(image,0,0,10,8);
        for (let destY=0; destY<4; destY++) for (let destX=0; destX<4; destX++) ctx.drawImage(image,destY*2,destX*2,2,2,destX*2,destY*2,2,2);
        resolve();
      }; image.src=url;
    })));
  };
  window.paintRunner();
</script>""",
)


async def _paint_sources(
    page,
    selector: str = "canvas.page-image",
    *,
    include_spacer: bool = False,
    tile_limit: int = 16,
    geometry: str | None = None,
    reset_canvas: bool = True,
) -> None:
    await page.evaluate(
        """async () => {
          const sourceCanvas = document.createElement('canvas'); sourceCanvas.width=10; sourceCanvas.height=8;
          const source = sourceCanvas.getContext('2d');
          source.fillStyle='#e22'; source.fillRect(0,0,5,5); source.fillStyle='#2e2'; source.fillRect(5,0,5,5);
          source.fillStyle='#22e'; source.fillRect(0,5,5,5); source.fillStyle='#ee2'; source.fillRect(5,5,5,5);
          const blob = await new Promise(resolve => sourceCanvas.toBlob(resolve, 'image/png'));
          const url = URL.createObjectURL(blob);
          await Promise.all([...document.querySelectorAll('SELECTOR')].map(canvas => new Promise(resolve => {
            const image = new Image(); image.onload = () => {
              const ctx=canvas.getContext('2d'); if (RESET_CANVAS) { canvas.width=10; canvas.height=8; }
              ctx.drawImage(image,0,0,10,8);
              const geometryMode = 'GEOMETRY_MODE';
              if (geometryMode === 'alpha-zero') ctx.globalAlpha = 0;
              let tileCount = 0;
              for (let destY=0; destY<4; destY++) for (let destX=0; destX<4; destX++) {
                if (tileCount++ >= TILE_LIMIT) break;
                let sourceX = destY*2; let sourceY = destX*2; let targetX = destX*2;
                if (geometryMode === 'duplicate' && tileCount === 16) targetX = 0;
                if (geometryMode === 'fractional' && tileCount === 16) targetX = 0.5;
                if (geometryMode === 'bad-source' && tileCount === 16) sourceX = 9;
                ctx.drawImage(image,sourceX,sourceY,2,2,targetX,destY*2,2,2);
              }
              if (INCLUDE_SPACER) ctx.drawImage(image,-1,-1,1,1);
              resolve();
            }; image.src=url;
          })));
        }""".replace("SELECTOR", selector).replace("INCLUDE_SPACER", "true" if include_spacer else "false").replace("TILE_LIMIT", str(tile_limit)).replace("RESET_CANVAS", "true" if reset_canvas else "false").replace("GEOMETRY_MODE", geometry or "")
    )


async def test_comicdays_adapter_browser_spread_end_and_ad_exclusion(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adapter_module, "parse_comicdays_episode_url", lambda _url: "1")
    monkeypatch.setattr(adapter_module, "canonical_comicdays_episode_url", lambda _url: "https://comic-days.com/episode/1")
    monkeypatch.setattr(adapter_module, "_series_id_from_page", lambda _page: _completed("series"))
    monkeypatch.setattr(adapter_module, "fetch_comicdays_atom", lambda *_args, **_kwargs: _completed([{"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第１話"}]))
    await browser_page.goto("data:text/html,<html></html>")
    await browser_page.set_content(HTML)
    adapter = ComicDaysAdapter()
    await adapter.prepare_page(browser_page)
    await _paint_sources(browser_page, "#body-one canvas")
    # The init script is installed before the synthetic navigation above; add
    # it once more so the test remains independent of Playwright page reuse.
    await browser_page.reload()
    await browser_page.set_content(HTML)
    await _paint_sources(browser_page, "#body-one canvas")
    await browser_page.evaluate("""() => {
      const now = document.querySelector('.js-viewer-slider-pagenum-now');
      const one = document.querySelector('#body-one');
      const two = document.querySelector('#body-two');
      const three = document.querySelector('#body-three');
      const back = document.querySelector('.js-slide-backward');
      now.textContent = '3'; one.style.display = 'none'; two.style.display = 'block'; three.style.display = 'block';
      back.disabled = false;
      back.onclick = () => { now.textContent = '1'; one.style.display = 'block'; two.style.display = 'none'; three.style.display = 'none'; back.disabled = true; };
    }""")
    await _paint_sources(browser_page, "#body-two canvas,#body-three canvas")
    await adapter.initialize(browser_page)
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    assert (await adapter.get_content_identity(browser_page)).page_id == "1"
    captures = await adapter.capture_page(browser_page)
    assert captures is not None and len(captures) == 1
    assert captures[0].width == 10 and captures[0].height == 8
    await browser_page.evaluate("""() => {
      const canvas = document.querySelector('#body-one canvas');
      canvas.width = canvas.width; canvas.height = canvas.height;
    }""")
    assert await adapter.detect_state(browser_page) is PageState.LOADING
    with pytest.raises(LookupError):
        await adapter.capture_page(browser_page)
    await _paint_sources(browser_page, "#body-one canvas", tile_limit=4)
    assert await adapter.detect_state(browser_page) is PageState.LOADING
    await _paint_sources(browser_page, "#body-one canvas")
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    await adapter.get_content_identity(browser_page)
    assert await adapter.capture_page(browser_page) is not None
    await browser_page.evaluate("""() => {
      const canvas = document.querySelector('#body-one canvas');
      canvas.getContext('2d').fillRect(0, 0, 1, 1);
      document.querySelector('#body-two').innerHTML = '<canvas class="page-image js-page-image"></canvas>';
      document.querySelector('#body-three').innerHTML = '<canvas class="page-image js-page-image"></canvas>';
    }""")
    with pytest.raises(LookupError):
        await adapter.capture_page(browser_page)
    assert (await adapter.collect_debug_metadata(browser_page))["native"] is False
    await adapter.get_content_identity(browser_page)
    assert await adapter.capture_page(browser_page) is None
    assert await (await adapter.get_capture_targets(browser_page))[0].count() == 1
    await browser_page.evaluate("""() => {
      const now = document.querySelector('.js-viewer-slider-pagenum-now');
      now.textContent = '3'; document.querySelector('#body-one').style.display = 'none';
      document.querySelector('#body-two').style.display = 'block'; document.querySelector('#body-three').style.display = 'block';
    }""")
    with pytest.raises(LookupError):
        await adapter.get_capture_targets(browser_page)
    await browser_page.evaluate("""() => {
      const now = document.querySelector('.js-viewer-slider-pagenum-now');
      now.textContent = '1'; document.querySelector('#body-one').style.display = 'block';
      document.querySelector('#body-two').style.display = 'none'; document.querySelector('#body-three').style.display = 'none';
    }""")

    previous = await adapter.get_content_identity(browser_page)
    adapter.page_change_timeout_ms = 300
    unchanged = asyncio.create_task(adapter.wait_for_change(browser_page, previous))
    with pytest.raises(PageChangeTimeoutError):
        await unchanged
    adapter.page_change_timeout_ms = 10_000
    await adapter.go_next(browser_page)
    assert await adapter.detect_state(browser_page) is PageState.LOADING
    await _paint_sources(browser_page, "#body-two canvas", include_spacer=True)
    wait_task = asyncio.create_task(adapter.wait_for_change(browser_page, previous))
    await asyncio.sleep(0.25)
    assert not wait_task.done()
    assert await adapter.detect_state(browser_page) is PageState.LOADING
    await _paint_sources(browser_page, "#body-three canvas")
    await wait_task
    spread_identity = await adapter.get_content_identity(browser_page)
    assert spread_identity.page_id == "2,3"
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    spread = await adapter.capture_page(browser_page)
    assert spread is not None and len(spread) == 2
    assert [(item.width, item.height) for item in spread] == [(10, 8), (10, 8)]
    assert await (await adapter.get_capture_targets(browser_page))[0].count() == 1

    previous = await adapter.get_content_identity(browser_page)
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, previous)
    assert await adapter.detect_state(browser_page) is PageState.END

    monkeypatch.setattr(
        adapter_module,
        "parse_comicdays_episode_url",
        lambda url: "2" if "changed" in url else "1",
    )
    await browser_page.goto("data:text/html,<html>changed</html>")
    assert await adapter.detect_state(browser_page) is PageState.NEXT_CONTENT


async def test_comicdays_initialize_rewinds_from_colophon_before_first_ready_spread(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch, initialize=False)
    await browser_page.evaluate("""() => {
      const now = document.querySelector('.js-viewer-slider-pagenum-now');
      const one = document.querySelector('#body-one');
      const end = document.querySelector('#viewer-colophon');
      const back = document.querySelector('.js-slide-backward');
      now.textContent = '35'; document.querySelector('.js-viewer-slider-pagenum-last').textContent = '36';
      one.style.display = 'none'; end.style.display = 'block';
      back.disabled = false;
      back.onclick = () => {
        now.textContent = '1'; one.style.display = 'block'; end.style.display = 'none'; back.disabled = true;
      };
    }""")
    await adapter.initialize(browser_page)
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    identity = await adapter.get_content_identity(browser_page)
    assert identity.page_number == 1
    assert identity.page_id == "1"


async def test_comicdays_initialize_waits_for_delayed_first_ready_spread(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch, initialize=False)
    await browser_page.evaluate("""() => {
      document.querySelector('#body-one canvas').getContext('2d').clearRect(0, 0, 10, 8);
      const now = document.querySelector('.js-viewer-slider-pagenum-now');
      const one = document.querySelector('#body-one');
      const two = document.querySelector('#body-two');
      const three = document.querySelector('#body-three');
      const back = document.querySelector('.js-slide-backward');
      back.disabled = false;
      back.onclick = () => {
        now.textContent = '1'; one.style.display = 'block'; two.style.display = 'none'; three.style.display = 'none'; back.disabled = true;
      };
    }""")

    await _paint_sources(browser_page, "#body-two canvas,#body-three canvas")
    original_active = adapter._active
    calls = 0

    async def delayed_late_active(page, *, timeout_ms=None):
        nonlocal calls
        calls += 1
        state = await original_active(page, timeout_ms=timeout_ms)
        if calls == 3:
            await asyncio.sleep(0.2)
            await browser_page.evaluate("""() => {
              const now = document.querySelector('.js-viewer-slider-pagenum-now');
              now.textContent = '3'; document.querySelector('#body-one').style.display = 'none';
              document.querySelector('#body-two').style.display = 'block';
              document.querySelector('#body-three').style.display = 'block';
            }""")
            state = await original_active(page, timeout_ms=timeout_ms)
        elif calls > 3 and state.get("sliderNow") == 1 and state.get("ready") is not True:
            await _paint_sources(browser_page, "#body-one canvas", reset_canvas=False)
            state = await original_active(page, timeout_ms=timeout_ms)
        return state

    monkeypatch.setattr(adapter, "_active", delayed_late_active)
    await adapter.initialize(browser_page)
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    identity = await adapter.get_content_identity(browser_page)
    assert identity.page_number == 1


async def test_comicdays_initialize_observation_respects_wall_deadline(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch, initialize=False)
    adapter.page_change_timeout_ms = 100
    original_active = adapter._active

    async def slow_active(page, *, timeout_ms=None):
        await asyncio.sleep(0.25)
        return await original_active(page, timeout_ms=timeout_ms)

    monkeypatch.setattr(adapter, "_active", slow_active)
    started = asyncio.get_running_loop().time()
    with pytest.raises(PageChangeTimeoutError):
        await adapter.initialize(browser_page)
    assert asyncio.get_running_loop().time() - started < 0.8


async def test_comicdays_initialize_bounds_cumulative_slow_rewind_locator_reads(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch, initialize=False)
    await browser_page.evaluate("""() => {
      const now = document.querySelector('.js-viewer-slider-pagenum-now');
      const one = document.querySelector('#body-one');
      const two = document.querySelector('#body-two');
      const three = document.querySelector('#body-three');
      const back = document.querySelector('.js-slide-backward');
      now.textContent = '3'; one.style.display = 'none'; two.style.display = 'block'; three.style.display = 'block';
      back.disabled = false;
      back.onclick = () => {
        now.textContent = '1'; one.style.display = 'block'; two.style.display = 'none'; three.style.display = 'none'; back.disabled = true;
      };
    }""")
    await _paint_sources(browser_page, "#body-two canvas,#body-three canvas")
    original_locator = browser_page.locator
    events: list[str] = []

    class SlowLocator:
        def __init__(self, locator) -> None:
            self.locator = locator

        async def count(self):
            events.append("count:start")
            try:
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                events.append("count:cancelled")
                raise
            events.append("count:complete")
            return await self.locator.count()

        async def is_visible(self, **kwargs):
            events.append("visible:start")
            try:
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                events.append("visible:cancelled")
                raise
            events.append("visible:complete")
            return await self.locator.is_visible(**kwargs)

        async def get_attribute(self, name, **kwargs):
            events.append("attribute:start")
            try:
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                events.append("attribute:cancelled")
                raise
            events.append("attribute:complete")
            return await self.locator.get_attribute(name, **kwargs)

        async def inner_text(self, **kwargs):
            events.append("text:start")
            try:
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                events.append("text:cancelled")
                raise
            events.append("text:complete")
            return await self.locator.inner_text(**kwargs)

        async def click(self, **kwargs):
            events.append("click:start")
            try:
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                events.append("click:cancelled")
                raise
            events.append("click:complete")
            return await self.locator.click(**kwargs)

    def slow_locator(selector, *args, **kwargs):
        locator = original_locator(selector, *args, **kwargs)
        if "page-navigation-backward" in selector:
            return SlowLocator(locator)
        return locator

    monkeypatch.setattr(browser_page, "locator", slow_locator)
    adapter.page_change_timeout_ms = 100
    started = asyncio.get_running_loop().time()
    with pytest.raises(PageChangeTimeoutError):
        await adapter.initialize(browser_page)
    cancelled = [index for index, event in enumerate(events) if event.endswith(":cancelled")]
    assert cancelled, events
    first_cancelled = cancelled[0]
    assert not any(
        event.startswith(("attribute:", "text:", "click:"))
        for event in events[first_cancelled + 1 :]
    ), events
    assert asyncio.get_running_loop().time() - started < 0.8


@pytest.mark.parametrize("ambiguous", ["slider", "backward"])
async def test_comicdays_initialize_fails_bounded_for_ambiguous_resume(
    browser_page, monkeypatch: pytest.MonkeyPatch, ambiguous: str
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch, initialize=False)
    adapter.page_change_timeout_ms = 300
    await browser_page.evaluate(
        """ambiguous => {
          const now = document.querySelector('.js-viewer-slider-pagenum-now');
          const one = document.querySelector('#body-one');
          const end = document.querySelector('#viewer-colophon');
          const back = document.querySelector('.js-slide-backward');
          if (ambiguous === 'slider') now.textContent = '';
          else {
            now.textContent = '35'; document.querySelector('.js-viewer-slider-pagenum-last').textContent = '36';
            one.style.display = 'none'; end.style.display = 'block';
            back.disabled = false; back.onclick = () => {};
          }
        }""",
        ambiguous,
    )
    with pytest.raises(PageChangeTimeoutError):
        await adapter.initialize(browser_page)


async def test_comicdays_runner_browser_captures_spread_and_end(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(adapter_module, "parse_comicdays_episode_url", lambda _url: "1")
    monkeypatch.setattr(adapter_module, "canonical_comicdays_episode_url", lambda _url: "https://comic-days.com/episode/1")
    monkeypatch.setattr(adapter_module, "_series_id_from_page", lambda _page: _completed("series"))
    monkeypatch.setattr(adapter_module, "fetch_comicdays_atom", lambda *_args, **_kwargs: _completed([{"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第１話"}]))
    adapter = ComicDaysAdapter()
    runner_url = "data:text/html," + quote(RUNNER_HTML)
    adapter.resolve_initial_navigation_url = lambda _source_url: runner_url  # type: ignore[method-assign]
    result = await CrawlerRunner(
        RunConfig(
            site="comicdays",
            source_url="https://comic-days.com/episode/1",
            output_dir=tmp_path / "runner-output",
            diagnostics_dir=tmp_path / "runner-diagnostics",
            access_strategy="direct",
            page_turn_delay_ms=0,
            max_pages=5,
            page_change_timeout_ms=3_000,
        )
    ).run(browser_page, adapter)
    assert result.stop_state is PageState.END
    assert len(result.pages) == 3
    assert [page.identity.page_id for page in result.pages] == ["1", "2,3", "2,3"]


async def test_comicdays_discovery_browser_count_mismatch_yields_zero(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page_html = '<link rel="alternate" href="https://comic-days.com/atom/series/42"><h1 class="series-header-title">Synthetic Work</h1>'
    await browser_page.route(
        "https://comic-days.com/episode/1",
        lambda route: route.fulfill(status=200, content_type="text/html", body=page_html),
    )

    entries = [{"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第１話"}]

    async def atom(_page, _series: str, *, free_only: bool):
        return entries

    async def total(_page, _series: str, _episode: str) -> int:
        return 2

    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    target = WatchlistTarget("key", "work", "comicdays", "https://comic-days.com/episode/1", "Synthetic Work")
    iterator = discovery_module.ComicDaysDiscoveryAdapter().iter_records(browser_page, target, "full")
    with pytest.raises(DiscoveryIncompleteError):
        await anext(iterator)


async def test_comicdays_discovery_browser_success_marks_free_subset(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page_html = '<link rel="alternate" href="https://comic-days.com/atom/series/42"><h1 class="series-header-title">Synthetic Work</h1>'
    await browser_page.route(
        "https://comic-days.com/episode/1",
        lambda route: route.fulfill(status=200, content_type="text/html", body=page_html),
    )
    full = [
        {"episode_id": "2", "url": "https://comic-days.com/episode/2", "title": "第２話"},
        {"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第１話"},
    ]
    free = [full[1]]

    async def atom(_page, _series: str, *, free_only: bool):
        return free if free_only else full

    async def total(_page, _series: str, _episode: str) -> int:
        return 2

    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    target = WatchlistTarget("key", "work", "comicdays", "https://comic-days.com/episode/1", "Synthetic Work")
    rows = [
        row
        async for row in discovery_module.ComicDaysDiscoveryAdapter().iter_records(
            browser_page, target, "full"
        )
    ]
    assert [row.source.external_id for row in rows] == ["2", "1"]
    assert [row.source.access_mode for row in rows] == ["unknown", "free"]


async def test_comicdays_discovery_browser_feed_identity_mismatch_yields_zero(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page_html = '<link rel="alternate" href="https://comic-days.com/atom/series/42"><h1 class="series-header-title">Synthetic Work</h1>'
    await browser_page.route(
        "https://comic-days.com/episode/1",
        lambda route: route.fulfill(status=200, content_type="text/html", body=page_html),
    )
    wrong_full = [{"episode_id": "2", "url": "https://comic-days.com/episode/2", "title": "第２話"}]
    wrong_free = [{"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第１話"}]

    async def atom(_page, _series: str, *, free_only: bool):
        return wrong_free if free_only else wrong_full

    async def total(_page, _series: str, _episode: str) -> int:
        return 1

    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    target = WatchlistTarget("key", "work", "comicdays", "https://comic-days.com/episode/1", "Synthetic Work")
    iterator = discovery_module.ComicDaysDiscoveryAdapter().iter_records(browser_page, target, "full")
    with pytest.raises(DiscoveryIncompleteError):
        await anext(iterator)


async def _initialized_comicdays_adapter(
    browser_page,
    monkeypatch: pytest.MonkeyPatch,
    *,
    geometry: str | None = None,
    initialize: bool = True,
) -> ComicDaysAdapter:
    monkeypatch.setattr(adapter_module, "parse_comicdays_episode_url", lambda _url: "1")
    monkeypatch.setattr(adapter_module, "canonical_comicdays_episode_url", lambda _url: "https://comic-days.com/episode/1")
    monkeypatch.setattr(adapter_module, "_series_id_from_page", lambda _page: _completed("series"))
    monkeypatch.setattr(adapter_module, "fetch_comicdays_atom", lambda *_args, **_kwargs: _completed([{"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第１話"}]))
    await browser_page.goto("data:text/html,<html></html>")
    await browser_page.set_content(HTML)
    adapter = ComicDaysAdapter()
    await adapter.prepare_page(browser_page)
    await browser_page.reload()
    await browser_page.set_content(HTML)
    await _paint_sources(browser_page, "#body-one canvas", geometry=geometry)
    if initialize:
        await adapter.initialize(browser_page)
        await adapter.get_content_identity(browser_page)
    return adapter


@pytest.mark.parametrize("mutation", ["fill", "clip", "resize", "replace"])
async def test_comicdays_capture_fails_closed_when_generation_changes_during_snapshot(
    browser_page, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    operation = {
        "fill": "canvas.getContext('2d').fillRect(0, 0, 1, 1);",
        "clip": "canvas.getContext('2d').clip();",
        "resize": "canvas.width = canvas.width;",
        "replace": """void (async () => {
          const sourceCanvas = document.createElement('canvas'); sourceCanvas.width = 10; sourceCanvas.height = 8;
          const source = sourceCanvas.getContext('2d'); source.fillStyle = '#39c'; source.fillRect(0, 0, 10, 8);
          const blob = await new Promise(resolve => sourceCanvas.toBlob(resolve, 'image/png'));
          const image = new Image(); image.src = URL.createObjectURL(blob);
          await new Promise(resolve => { image.onload = resolve; });
          canvas.width = 10; canvas.height = 8;
          const ctx = canvas.getContext('2d'); ctx.drawImage(image, 0, 0, 10, 8);
          for (let destY = 0; destY < 4; destY++) for (let destX = 0; destX < 4; destX++)
            ctx.drawImage(image, destY * 2, destX * 2, 2, 2, destX * 2, destY * 2, 2, 2);
        })();""",
    }[mutation]
    await browser_page.evaluate(
        f"""() => {{
          const canvas = document.querySelector('#body-one canvas');
          const original = window.__comicDaysProductionCapture.snapshot;
          window.__comicDaysProductionCapture.snapshot = async ids => {{
            setTimeout(() => {{ {operation} }}, 10);
            await new Promise(resolve => setTimeout(resolve, 100));
            return original(ids);
          }};
        }}"""
    )
    with pytest.raises(LookupError):
        await adapter.capture_page(browser_page)
    assert (await adapter.collect_debug_metadata(browser_page))["native"] is False


async def test_comicdays_capture_rejects_same_size_source_replacement_before_fetch(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    await _paint_sources(browser_page, "#body-one canvas")
    with pytest.raises(LookupError):
        await adapter.capture_page(browser_page)
    assert (await adapter.collect_debug_metadata(browser_page))["native"] is False
    with pytest.raises(LookupError):
        await adapter.get_capture_targets(browser_page)


async def test_comicdays_persistent_mutation_survives_rolling_trace_eviction(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    await adapter.get_content_identity(browser_page)
    await browser_page.evaluate("""() => {
      const selected = document.querySelector('#body-one canvas');
      selected.getContext('2d').fillRect(0, 0, 1, 1);
      const other = document.querySelector('#body-two canvas');
      const ctx = other.getContext('2d');
      for (let index = 0; index < 6001; index++) ctx.fillRect(0, 0, 1, 1);
    }""")
    debug = await browser_page.evaluate("window.__comicDaysProductionCapture.debug()")
    assert debug["mutations"] <= 6000
    with pytest.raises(LookupError):
        await adapter.capture_page(browser_page)
    assert (await adapter.collect_debug_metadata(browser_page))["native"] is False
    await adapter.get_content_identity(browser_page)
    assert await adapter.capture_page(browser_page) is None
    assert await (await adapter.get_capture_targets(browser_page))[0].count() == 1

    await _paint_sources(browser_page, "#body-one canvas", reset_canvas=False)
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    await adapter.get_content_identity(browser_page)
    assert await adapter.capture_page(browser_page) is not None
    assert (await adapter.collect_debug_metadata(browser_page))["native"] is True


@pytest.mark.parametrize("dimension", ["width", "height"])
async def test_comicdays_resize_mutation_trace_stays_bounded_and_recovers(
    browser_page, monkeypatch: pytest.MonkeyPatch, dimension: str
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    await browser_page.evaluate(
        """dimension => (async () => {
          const canvas = document.querySelector('#body-one canvas');
          const sourceCanvas = document.createElement('canvas');
          sourceCanvas.width = 10; sourceCanvas.height = 8;
          const source = sourceCanvas.getContext('2d');
          source.fillStyle = '#39c'; source.fillRect(0, 0, 10, 8);
          const blob = await new Promise(resolve => sourceCanvas.toBlob(resolve, 'image/png'));
          const image = new Image(); image.src = URL.createObjectURL(blob);
          await new Promise(resolve => { image.onload = resolve; });
          const ctx = canvas.getContext('2d');
          for (let index = 0; index < 6001; index++) {
            ctx.drawImage(image, 0, 0, 10, 8);
            canvas[dimension] = canvas[dimension];
          }
        })()""",
        dimension,
    )
    debug = await browser_page.evaluate("window.__comicDaysProductionCapture.debug()")
    assert debug["mutations"] <= 6000
    assert await adapter.detect_state(browser_page) is PageState.LOADING
    await _paint_sources(browser_page, "#body-one canvas", reset_canvas=False)
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    await adapter.get_content_identity(browser_page)
    assert await adapter.capture_page(browser_page) is not None
    assert (await adapter.collect_debug_metadata(browser_page))["native"] is True


async def test_comicdays_clip_stays_unsafe_until_context_reset(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    await browser_page.evaluate("""() => {
      const ctx = document.querySelector('#body-one canvas').getContext('2d');
      ctx.clearRect(0, 0, 10, 8);
    }""")
    assert await adapter.detect_state(browser_page) is PageState.LOADING
    await browser_page.evaluate("""() => {
      document.querySelector('#body-one canvas').getContext('2d').clip();
    }""")
    await _paint_sources(browser_page, "#body-one canvas", reset_canvas=False)
    await browser_page.evaluate("""() => {
      document.querySelector('#body-one canvas').getContext('2d').clip();
    }""")
    assert await adapter.detect_state(browser_page) is PageState.LOADING
    with pytest.raises(LookupError):
        await adapter.capture_page(browser_page)
    assert (await adapter.collect_debug_metadata(browser_page))["native"] is False
    await browser_page.evaluate("""() => {
      const ctx = document.querySelector('#body-one canvas').getContext('2d');
      if (typeof ctx.reset !== 'function') throw new Error('CanvasRenderingContext2D.reset unavailable');
      ctx.reset();
    }""")
    assert await adapter.detect_state(browser_page) is PageState.LOADING
    await _paint_sources(browser_page, "#body-one canvas", reset_canvas=False)
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    await adapter.get_content_identity(browser_page)
    assert await adapter.capture_page(browser_page) is not None
    assert (await adapter.collect_debug_metadata(browser_page))["native"] is True


async def test_comicdays_clip_after_completed_composition_uses_fallback(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    await browser_page.evaluate("""() => {
      document.querySelector('#body-one canvas').getContext('2d').clip();
    }""")
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    await adapter.get_content_identity(browser_page)
    assert await adapter.capture_page(browser_page) is None
    assert (await adapter.collect_debug_metadata(browser_page))["native"] is False
    assert await (await adapter.get_capture_targets(browser_page))[0].count() == 1


@pytest.mark.parametrize("reset_operation", ["clear", "reset"])
async def test_comicdays_destructive_reset_requires_redraw(
    browser_page, monkeypatch: pytest.MonkeyPatch, reset_operation: str
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    await browser_page.evaluate(
        """operation => {
          const ctx = document.querySelector('#body-one canvas').getContext('2d');
          if (operation === 'clear') ctx.clearRect(0, 0, 10, 8);
          else {
            if (typeof ctx.reset !== 'function') throw new Error('CanvasRenderingContext2D.reset unavailable');
            ctx.reset();
          }
        }""",
        reset_operation,
    )
    assert await adapter.detect_state(browser_page) is PageState.LOADING
    with pytest.raises(LookupError):
        await adapter.capture_page(browser_page)
    await _paint_sources(browser_page, "#body-one canvas", reset_canvas=False)
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    await adapter.get_content_identity(browser_page)
    assert await adapter.capture_page(browser_page) is not None


@pytest.mark.parametrize("geometry", ["duplicate", "fractional", "bad-source", "alpha-zero"])
async def test_comicdays_browser_readiness_rejects_unsupported_or_suppressed_composition(
    browser_page, monkeypatch: pytest.MonkeyPatch, geometry: str
) -> None:
    adapter = await _initialized_comicdays_adapter(
        browser_page, monkeypatch, geometry=geometry, initialize=False
    )
    assert await adapter.detect_state(browser_page) is PageState.LOADING


async def test_comicdays_snapshot_aborts_stalled_response_body(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    await browser_page.evaluate("""() => {
      window.__comicDaysBodySettled = false;
      window.__comicDaysOriginalFetch = window.fetch;
      window.__comicDaysOriginalTimer = window.setTimeout;
      window.fetch = async (url, options) => {
        if (!String(url).startsWith('blob:')) return window.__comicDaysOriginalFetch(url, options);
        return {
          ok: true,
          headers: { get: () => null },
          arrayBuffer: () => new Promise((resolve, reject) => {
            options.signal.addEventListener('abort', () => {
              window.__comicDaysBodySettled = true;
              reject(new DOMException('aborted', 'AbortError'));
            }, { once: true });
          })
        };
      };
      window.setTimeout = (callback, milliseconds, ...args) =>
        window.__comicDaysOriginalTimer(callback, Math.min(milliseconds, 30), ...args);
    }""")
    assert await adapter.capture_page(browser_page) is None
    assert (await adapter.collect_debug_metadata(browser_page))["native"] is False
    settled = await browser_page.evaluate("window.__comicDaysBodySettled")
    await browser_page.evaluate("""() => {
      window.fetch = window.__comicDaysOriginalFetch;
      window.setTimeout = window.__comicDaysOriginalTimer;
    }""")
    assert settled is True


async def _completed(value):
    return value
