from __future__ import annotations

import asyncio
import json
import zipfile
from datetime import UTC, datetime
from urllib.parse import quote

import pytest

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import PageChangeTimeoutError
from screenshot_crawler.core.models import ContentIdentity, RunConfig
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.comicdays import adapter as adapter_module
from screenshot_crawler.site_adapters.comicdays import discovery as discovery_module
from screenshot_crawler.site_adapters.comicdays.adapter import ComicDaysAdapter
from screenshot_crawler.site_adapters.comicdays.live_access import (
    ComicDaysLiveAccessState,
    ComicDaysTicketState,
)
from screenshot_crawler.watchlist.models import WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(autouse=True)
def synthetic_live_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep synthetic viewer tests independent of first-party network APIs."""

    async def observe(_page, *, series_id: str, episode_id: str, **_kwargs):
        return ComicDaysLiveAccessState(
            series_id=str(series_id),
            episode_id=str(episode_id),
            row={},
            access_mode="free",
            grant_until=None,
            grant_observed=True,
            ticket=ComicDaysTicketState(
                series_id=str(series_id),
                is_charged=True,
                charged_at=datetime(1999, 1, 1, tzinfo=UTC),
            ),
        )

    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", observe)


HTML = """
<section class="private-viewer viewer js-viewer" data-json-url="https://comic-days.com/episode/1.json">
  <div class="content-inner scroll-horizontal js-horizontal-viewer">
    <div class="image-container js-viewer-content is-spread">
      <div class="page-area js-page-area" id="ad" style="display:none"><a href="/episode/999">ad</a></div>
      <div class="page-area js-page-area" id="body-one"><canvas class="page-image js-page-image"></canvas></div>
      <div class="page-area js-page-area" id="body-two" style="display:none;position:absolute;left:300px"><canvas class="page-image js-page-image"></canvas></div>
      <div class="page-area js-page-area" id="body-three" style="display:none;position:absolute;left:0"><canvas class="page-image js-page-image"></canvas></div>
      <div class="page-area js-page-area" id="body-four" style="display:none;position:absolute;left:300px"><canvas class="page-image js-page-image"></canvas></div>
      <div class="page-area js-page-area" style="display:none;position:absolute;left:-1000px;top:0;width:300px;height:300px"><div class="page js-page back-link-page link-page js-link-page js-back-link-page link-page-half" style="display:block;width:300px;height:300px"><div class="link-page-content"><img alt="back"><img alt="back"></div></div></div>
      <div class="page-area js-page-area" style="display:none;position:absolute;left:-1000px;top:0;width:300px;height:300px"><div class="page js-page page-ad js-page-ad" style="display:block;width:300px;height:300px"><div class="ad-nav-area-wrap page-content"><iframe></iframe><iframe></iframe></div></div></div>
      <div class="page-area js-page-area" id="viewer-colophon" style="display:none;width:300px;height:300px"><div class="back-matter js-back-matter"><div class="back-matter-content"><img><img><img><img><img><img><img><img><img><img></div></div></div>
    </div>
  </div>
  <span class="js-viewer-slider-pagenum-now">1</span><span class="js-viewer-slider-pagenum-last">8</span>
  <button class="page-navigation-backward js-slide-backward" disabled>back</button>
  <button class="page-navigation-forward js-slide-forward" style="position:relative;z-index:5">next</button>
</section>
<h1 class="series-header-title">Synthetic Work</h1>
<script>
  const now = document.querySelector('.js-viewer-slider-pagenum-now');
  const one = document.querySelector('#body-one'); const two = document.querySelector('#body-two'); const three = document.querySelector('#body-three');
  const end = document.querySelector('#viewer-colophon'); const tailBack = document.querySelector('.js-back-link-page').parentElement; const tailAd = document.querySelector('.js-page-ad').parentElement;
  document.querySelector('.js-slide-forward').onclick = () => {
    const current = Number(now.textContent); const n = current === 3 ? 6 : current === 6 ? 8 : current + 2; now.textContent = String(n);
    if (n === 3) { one.style.display='none'; two.style.display='block'; three.style.display='block'; }
    if (n === 6) { two.style.display='none'; three.style.display='none'; tailBack.style.display='block'; tailBack.style.left='0px'; tailAd.style.display='block'; tailAd.style.left='310px'; }
    if (n >= 8) { tailBack.style.display='none'; tailAd.style.display='none'; end.style.display='block'; }
  };
</script>
"""


RUNNER_HTML = HTML.replace(
    "const one = document.querySelector('#body-one'); const two = document.querySelector('#body-two'); const three = document.querySelector('#body-three');",
    "const one = document.querySelector('#body-one'); const two = document.querySelector('#body-two'); const three = document.querySelector('#body-three'); const four = document.querySelector('#body-four');",
).replace(
    "if (n === 3) { one.style.display='none'; two.style.display='block'; three.style.display='block'; }",
    "if (n === 3) { one.style.display='none'; two.style.display='block'; three.style.display='block'; window.paintRunner?.(); }",
).replace(
    "const current = Number(now.textContent); const n = current === 3 ? 6 : current === 6 ? 8 : current + 2; now.textContent = String(n);",
    "const current = Number(now.textContent); const n = current === 3 ? 5 : current === 5 ? 6 : current === 6 ? 8 : current + 2; now.textContent = String(n);",
).replace(
    "if (n === 6) { two.style.display='none'; three.style.display='none'; tailBack.style.display='block';",
    "if (n === 5) { two.style.display='none'; three.style.display='none'; four.style.display='block'; window.paintRunner?.(); }\n    if (n === 6) { four.style.display='none'; tailBack.style.display='block';",
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


NEXT_CONTENT_HTML = RUNNER_HTML + """
<script>
  document.querySelector('.js-slide-forward').onclick = () => history.pushState({}, '', '#episode2');
</script>
"""


TAIL_HTML = """
<section class="private-viewer viewer js-viewer" data-json-url="https://comic-days.com/episode/1.json" style="position:relative;width:900px;height:400px">
  <div class="image-container js-viewer-content is-spread"><canvas class="page-image js-page-image"></canvas></div>
  <div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div><div class="page-area js-page-area" style="display:none"></div>
  <div class="page-area js-page-area" style="display:none;position:absolute;left:-1000px;top:0;width:300px;height:300px"><div class="page js-page back-link-page link-page js-link-page js-back-link-page link-page-half" style="display:block;width:300px;height:300px"><div class="link-page-content"><img><img></div></div></div>
  <div class="page-area js-page-area" style="display:none;position:absolute;left:-1000px;top:0;width:300px;height:300px"><div class="page js-page page-ad js-page-ad" style="display:block;width:300px;height:300px"><div class="ad-nav-area-wrap page-content"><iframe></iframe><iframe></iframe></div></div></div>
  <div id="viewer-colophon" class="page-area js-page-area" style="display:none;position:absolute;left:-1000px;top:0;width:300px;height:300px"><div class="back-matter js-back-matter"><div class="back-matter-content"><img><img><img><img><img><img><img><img><img><img></div></div></div>
  <span class="js-viewer-slider-pagenum-now">17</span><span class="js-viewer-slider-pagenum-last">21</span>
  <button class="page-navigation-forward js-slide-forward" style="position:relative;z-index:5">next</button>
</section>
<script>
  window.__tailState = {sliderNow:17, sliderLast:21, colophon:false, complete:true, rows:[{areaIndex:16, renderReady:true, canvasIndex:0}]};
  window.__comicDaysProductionCapture = {active: () => ({...window.__tailState, rows: [...window.__tailState.rows]})};
  const back = document.querySelector('.js-back-link-page').parentElement; const ad = document.querySelector('.js-page-ad').parentElement; const end = document.querySelector('#viewer-colophon');
  const now = document.querySelector('.js-viewer-slider-pagenum-now');
  document.querySelector('.js-slide-forward').onclick = () => {
    if (window.__tailState.sliderNow === 17) {
      window.__tailState = {sliderNow:19, sliderLast:21, colophon:false, complete:false, rows:[]}; back.style.display='block'; ad.style.display='block'; back.style.left='0px'; ad.style.left='310px';
      now.textContent = '19';
    } else if (window.__tailState.sliderNow === 19) {
      window.__tailState = {sliderNow:21, sliderLast:21, colophon:true, complete:false, rows:[]}; back.style.display='none'; ad.style.display='none'; back.style.left='-1000px'; ad.style.left='-1000px'; end.style.display='block'; end.style.left='0px';
      now.textContent = '21';
    }
  };
</script>
"""


OFFSET_TAIL_HTML = (
    TAIL_HTML.replace(
        '<div class="image-container js-viewer-content is-spread"><canvas',
        '<div class="image-container js-viewer-content is-spread"><div class="page-area js-page-area" style="display:none"></div><canvas',
    )
    .replace(
        "window.__tailState = {sliderNow:17, sliderLast:21, colophon:false, complete:true, rows:[{areaIndex:16, renderReady:true, canvasIndex:0}]};",
        "window.__tailState = {sliderNow:17, sliderLast:21, colophon:false, complete:true, rows:[{areaIndex:17, renderReady:true, canvasIndex:0}]};",
    )
    .replace(
        "window.__tailState = {sliderNow:19, sliderLast:21, colophon:false, complete:false, rows:[]}",
        "window.__tailState = {sliderNow:20, sliderLast:21, colophon:false, complete:false, rows:[]}",
    )
    .replace("now.textContent = '19'", "now.textContent = '20'")
    .replace(
        "window.__tailState.sliderNow === 19",
        "window.__tailState.sliderNow === 20",
    )
)


DIRECT_TERMINAL_HTML = """
<section class="viewer js-viewer" data-json-url="https://comic-days.com/episode/1.json" style="position:relative;width:900px;height:400px">
  <div class="image-container js-viewer-content is-spread">
    AREAS
    <div class="page-area js-page-area" id="body-final"><canvas class="page-image js-page-image"></canvas></div>
    <div class="page-area js-page-area" style="display:none"><div class="page js-page back-link-page js-link-page js-back-link-page" style="width:300px;height:300px"><div class="link-page-content"><img><img></div></div></div>
    <div class="page-area js-page-area" style="display:none"><div class="page js-page page-ad js-page-ad" style="width:300px;height:300px"><div class="ad-nav-area-wrap page-content"><iframe></iframe><iframe></iframe></div></div></div>
    <div id="viewer-colophon" class="page-area js-page-area" style="display:none;width:300px;height:300px"><div class="back-matter js-back-matter"><div class="back-matter-content"><img><img><img><img><img><img><img><img><img><img></div></div></div>
  </div>
  <span class="js-viewer-slider-pagenum-now">20</span><span class="js-viewer-slider-pagenum-last">23</span>
  <button class="page-navigation-forward js-slide-forward">next</button>
</section>
<script>
  const now = document.querySelector('.js-viewer-slider-pagenum-now');
  const body = document.querySelector('#body-final');
  const colophon = document.querySelector('#viewer-colophon');
  document.querySelector('.js-slide-forward').onclick = () => { now.textContent = '22'; body.style.display = 'none'; colophon.style.display = 'block'; };
</script>
""".replace(
    "AREAS", "".join('<div class="page-area js-page-area" style="display:none"></div>' for _ in range(20))
)


PRODUCTION_HOOK_CASES = [
    pytest.param("legacy-even", HTML, 8, [(1, [1]), (3, [2, 3]), (5, [4])], id="legacy-even"),
    pytest.param(
        "legacy-odd",
        HTML.replace('<div class="page-area js-page-area" id="body-four" style="display:none;position:absolute;left:300px"><canvas class="page-image js-page-image"></canvas></div>\n', ""),
        7,
        [(1, [1]), (3, [2, 3])],
        id="legacy-odd",
    ),
    pytest.param("leading-even", HTML, 7, [(1, [1]), (2, [2, 3]), (4, [4])], id="leading-even"),
    pytest.param(
        "leading-odd",
        HTML.replace('<div class="page-area js-page-area" id="body-four" style="display:none;position:absolute;left:300px"><canvas class="page-image js-page-image"></canvas></div>\n', ""),
        6,
        [(1, [1]), (2, [2, 3])],
        id="leading-odd",
    ),
]


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
    assert await adapter.detect_state(browser_page) is PageState.AD
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


@pytest.mark.parametrize(
    ("case", "jpeg_results", "png_results", "expected_mode", "expected_count", "expect_locator"),
    [
        ("all-jpeg", ["jpeg", "jpeg"], ["png", "png"], "jpeg", 2, False),
        ("one-jpeg-unsafe", ["jpeg", None], ["png", "png"], "reconstructed_png", 2, False),
        ("progressive-source", [None, None], ["png", "png"], "reconstructed_png", 2, False),
        ("unsupported-420", [None, None], ["png", "png"], "reconstructed_png", 2, False),
        ("unsupported-422", [None, None], ["png", "png"], "reconstructed_png", 2, False),
        ("metadata-changed", [None, None], ["png", "png"], "reconstructed_png", 2, False),
        ("png-one-unsafe", [None, None], ["png", None], "locator_fallback", 0, True),
    ],
)
async def test_comicdays_capture_spread_modes_are_atomic(
    browser_page,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    jpeg_results: list[str | None],
    png_results: list[str | None],
    expected_mode: str,
    expected_count: int,
    expect_locator: bool,
) -> None:
    """A two-area spread is captured wholly in one mode or remains uncaptured."""

    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    await browser_page.evaluate(
        """() => {
          document.querySelector('.js-viewer-slider-pagenum-now').textContent = '3';
          document.querySelector('#body-one').style.display = 'none';
          document.querySelector('#body-two').style.display = 'block';
          document.querySelector('#body-three').style.display = 'block';
        }"""
    )
    await _paint_sources(browser_page, "#body-two canvas,#body-three canvas")
    await adapter.get_content_identity(browser_page)

    def fake_result(kind: str) -> CaptureResult:
        return CaptureResult(
            data=kind.encode(),
            width=10,
            height=8,
            mime_type="image/jpeg" if kind == "jpeg" else "image/png",
            file_extension=".jpg" if kind == "jpeg" else ".png",
        )

    jpeg_iter = iter(jpeg_results)
    png_iter = iter(png_results)

    def next_capture(iterator):
        value = next(iterator, None)
        return fake_result(value) if value is not None else None

    monkeypatch.setattr(
        adapter_module,
        "reconstruct_jpeg",
        lambda _raw, _plan: next_capture(jpeg_iter),
    )
    monkeypatch.setattr(
        adapter_module,
        "reconstruct_png",
        lambda _raw, _plan: next_capture(png_iter),
    )
    captures = await adapter.capture_page(browser_page)
    if expect_locator:
        assert captures is None
        assert len(await adapter.get_capture_targets(browser_page)) == 2
    else:
        assert captures is not None and len(captures) == expected_count
        assert {capture.file_extension for capture in captures} == {
            ".jpg" if expected_mode == "jpeg" else ".png"
        }
    debug = await adapter.collect_debug_metadata(browser_page)
    assert debug.get("capture_mode") == expected_mode, case


@pytest.mark.parametrize("_family,case_html,slider_last,positions", PRODUCTION_HOOK_CASES)
async def test_comicdays_production_hook_covers_tail_family_and_body_parity(
    browser_page, _family: str, case_html: str, slider_last: int, positions: list[tuple[int, list[int]]]
) -> None:
    """The shipped hook selects complete single/double bodies for both layouts."""

    await browser_page.goto("data:text/html,<html></html>")
    adapter = ComicDaysAdapter()
    await adapter.prepare_page(browser_page)
    await browser_page.reload()
    await browser_page.set_content(case_html)
    await _paint_sources(browser_page, "canvas.page-image")
    await browser_page.evaluate(
        """last => { document.querySelector('.js-viewer-slider-pagenum-last').textContent = String(last); }""",
        slider_last,
    )
    for slider, expected_areas in positions:
        await browser_page.evaluate(
            """expected => {
              document.querySelector('.js-viewer-slider-pagenum-now').textContent = String(expected.slider);
              for (const area of document.querySelectorAll('.page-area.js-page-area')) area.style.display = 'none';
              for (const index of expected.areas) {
                const area = document.querySelector(`#body-${index === 1 ? 'one' : index === 2 ? 'two' : index === 3 ? 'three' : 'four'}`);
                if (area) area.style.display = 'block';
              }
            }""",
            {"slider": slider, "areas": expected_areas},
        )
        state = await adapter._active(browser_page)
        assert state["complete"] is True
        assert [row["areaIndex"] for row in state["rows"]] == expected_areas
        captures = await adapter.capture_page(browser_page)
        assert captures is not None and len(captures) == len(expected_areas)


async def test_comicdays_initialize_rewinds_from_colophon_before_first_ready_spread(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch, initialize=False)
    await browser_page.evaluate("""() => {
      const now = document.querySelector('.js-viewer-slider-pagenum-now');
      const one = document.querySelector('#body-one');
      const end = document.querySelector('#viewer-colophon');
      const back = document.querySelector('.js-slide-backward');
      now.textContent = '7'; document.querySelector('.js-viewer-slider-pagenum-last').textContent = '8';
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


async def test_comicdays_known_tail_ad_then_colophon_never_enters_tail_content(
    browser_page,
) -> None:
    await browser_page.set_content(TAIL_HTML)
    adapter = ComicDaysAdapter()
    adapter._episode_id = "1"
    previous = ContentIdentity(page_id="16,17", page_number=17, source_id="1", fingerprint="body")
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, previous)
    assert await adapter.detect_state(browser_page) is PageState.AD
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, previous)
    assert await adapter.detect_state(browser_page) is PageState.END


async def test_comicdays_active_requires_explicit_complete_flag(browser_page) -> None:
    await browser_page.set_content(TAIL_HTML)
    await browser_page.evaluate("() => { delete window.__tailState.complete; }")
    adapter = ComicDaysAdapter()
    adapter._episode_id = "1"
    state = await adapter._active(browser_page)
    assert state["rows"]
    assert state["complete"] is False
    assert state["ready"] is False




async def test_comicdays_leading_area_tail_variant_reaches_end(browser_page) -> None:
    await browser_page.set_content(OFFSET_TAIL_HTML)
    adapter = ComicDaysAdapter()
    adapter._episode_id = "1"
    previous = ContentIdentity(page_id="17", page_number=17, source_id="1", fingerprint="body")
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, previous)
    assert await adapter.detect_state(browser_page) is PageState.AD
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, previous)
    assert await adapter.detect_state(browser_page) is PageState.END


async def test_comicdays_direct_colophon_terminal_variant_reaches_end(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The observed final-body-to-slider-22 transition is terminal directly."""

    monkeypatch.setattr(adapter_module, "parse_comicdays_episode_url", lambda _url: "1")
    monkeypatch.setattr(adapter_module, "canonical_comicdays_episode_url", lambda _url: "https://comic-days.com/episode/1")
    await browser_page.goto("data:text/html,<html></html>")
    await browser_page.set_content(DIRECT_TERMINAL_HTML)
    adapter = ComicDaysAdapter()
    await adapter.prepare_page(browser_page)
    await browser_page.reload()
    await browser_page.set_content(DIRECT_TERMINAL_HTML)
    await _paint_sources(browser_page, "#body-final canvas")
    adapter._episode_id = "1"
    previous = await adapter.get_content_identity(browser_page)
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, previous)
    assert await adapter.detect_state(browser_page) is PageState.END


async def test_comicdays_known_tail_uses_actual_pre_advance_and_rejects_stall(
    browser_page,
) -> None:
    await browser_page.set_content(TAIL_HTML)
    adapter = ComicDaysAdapter()
    adapter._episode_id = "1"
    previous = ContentIdentity(page_id="16,17", page_number=17, source_id="1", fingerprint="body")
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, previous)
    assert await adapter.detect_state(browser_page) is PageState.AD
    adapter.page_change_timeout_ms = 200
    await adapter.go_next(browser_page)
    await browser_page.evaluate("""() => {
      window.__tailState = {sliderNow:19, sliderLast:21, colophon:false, complete:false, rows:[]};
      document.querySelector('#viewer-colophon').style.display='none';
      document.querySelector('.js-back-link-page').style.left='0px';
      document.querySelector('.js-page-ad').style.left='310px';
      document.querySelector('.js-slide-forward').onclick = () => {};
    }""")
    with pytest.raises(PageChangeTimeoutError):
        await adapter.wait_for_change(browser_page, previous)


async def test_comicdays_nonbody_mismatched_slider_snapshot_resets_stability(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_content(TAIL_HTML)
    adapter = ComicDaysAdapter()
    adapter._episode_id = "1"
    original = adapter._nonbody_observation

    async def mismatched(page, **kwargs):
        observation = await original(page, **kwargs)
        observation["sliderNow"] = int(observation["sliderNow"]) - 2
        return observation

    monkeypatch.setattr(adapter, "_nonbody_observation", mismatched)
    adapter.page_change_timeout_ms = 200
    with pytest.raises(PageChangeTimeoutError):
        await adapter.go_next(browser_page)
        await adapter.wait_for_change(
            browser_page,
            ContentIdentity(page_id="16,17", page_number=17, source_id="1", fingerprint="body"),
        )


async def test_comicdays_colophon_without_validated_transition_is_not_end(browser_page) -> None:
    await browser_page.set_content(TAIL_HTML)
    await browser_page.evaluate("""() => {
      window.__tailState = {sliderNow:21, sliderLast:21, colophon:true, complete:false, rows:[]};
      document.querySelector('.js-viewer-slider-pagenum-now').textContent = '21';
      document.querySelector('#viewer-colophon').style.display='block';
      document.querySelector('#viewer-colophon').style.left='0px';
    }""")
    adapter = ComicDaysAdapter()
    adapter._episode_id = "1"
    assert await adapter.detect_state(browser_page) is not PageState.END


@pytest.mark.parametrize("mutation", ["unknown", "blank", "paid", "mixed", "unknown_area"])
async def test_comicdays_unknown_or_mixed_nonbody_tail_fails_closed(
    browser_page, mutation: str,
) -> None:
    await browser_page.set_content(TAIL_HTML)
    if mutation == "unknown":
        extra = '<div class="page js-page unknown-panel" style="position:absolute;left:620px;top:0;width:100px;height:100px"></div>'
    elif mutation == "blank":
        extra = '<div class="page js-page" style="position:absolute;left:620px;top:0;width:100px;height:100px"></div>'
    elif mutation == "paid":
        extra = '<div class="page js-page paid-panel" style="position:absolute;left:620px;top:0;width:100px;height:100px">購入して読む</div>'
    elif mutation == "mixed":
        extra = '<div class="page js-page" style="position:absolute;left:620px;top:0;width:100px;height:100px"><canvas></canvas></div>'
    else:
        extra = '<div class="page-area js-page-area" style="display:block;position:absolute;left:620px;top:0;width:100px;height:100px"></div>'
    await browser_page.locator("section.viewer.js-viewer").evaluate("(node, html) => node.insertAdjacentHTML('beforeend', html)", extra)
    adapter = ComicDaysAdapter()
    adapter._episode_id = "1"
    adapter.page_change_timeout_ms = 200
    with pytest.raises(PageChangeTimeoutError):
        await adapter.go_next(browser_page)
        await adapter.wait_for_change(
            browser_page,
            ContentIdentity(page_id="16,17", page_number=17, source_id="1", fingerprint="body"),
        )


@pytest.mark.parametrize(
    "mutation",
    ["back_extra", "back_missing", "ad_extra", "colophon_extra", "resources1", "resources3", "blank", "unknown", "paid"],
)
async def test_comicdays_terminal_resource_shape_must_match_observation(
    browser_page, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    await browser_page.goto("data:text/html,<html></html>")
    await browser_page.set_content(DIRECT_TERMINAL_HTML)
    adapter = ComicDaysAdapter()
    await adapter.prepare_page(browser_page)
    await browser_page.reload()
    await browser_page.set_content(DIRECT_TERMINAL_HTML)
    await _paint_sources(browser_page, "#body-final canvas")
    if mutation == "back_extra":
        script = "document.querySelector('.js-back-link-page').append(document.createElement('span'))"
    elif mutation == "back_missing":
        script = "document.querySelector('.js-back-link-page img').remove()"
    elif mutation == "ad_extra":
        script = "document.querySelector('.js-page-ad').append(document.createElement('span'))"
    elif mutation == "colophon_extra":
        script = "document.querySelector('#viewer-colophon .back-matter').append(document.createElement('span'))"
    elif mutation == "resources1":
        script = "document.querySelector('#viewer-colophon .back-matter-content img').remove()"
    elif mutation == "resources3":
        script = "document.querySelector('#viewer-colophon .back-matter-content').append(document.createElement('img'))"
    elif mutation == "blank":
        script = "document.querySelector('.image-container').insertAdjacentHTML('beforeend', '<div class=\"page-area js-page-area\" style=\"display:block;pointer-events:none;position:absolute;left:0;top:0;width:300px;height:300px\"></div>')"
    elif mutation == "unknown":
        script = "document.querySelector('.image-container').insertAdjacentHTML('beforeend', '<div class=\"page-area js-page-area\" style=\"display:block;pointer-events:none;position:absolute;left:0;top:0;width:300px;height:300px\"><div class=\"page js-page unknown-panel\"></div></div>')"
    else:
        script = "document.querySelector('.image-container').insertAdjacentHTML('beforeend', '<div class=\"page-area js-page-area\" style=\"display:block;pointer-events:none;position:absolute;left:0;top:0;width:300px;height:300px\"><div class=\"page js-page paid-panel\">paid</div></div>')"
    await browser_page.evaluate(script)
    adapter._episode_id = "1"
    previous = await adapter.get_content_identity(browser_page)
    await adapter.go_next(browser_page)
    adapter.page_change_timeout_ms = 200
    with pytest.raises(PageChangeTimeoutError):
        await adapter.wait_for_change(browser_page, previous)


@pytest.mark.parametrize("case_html", [TAIL_HTML, OFFSET_TAIL_HTML], ids=["legacy", "leading"])
@pytest.mark.parametrize(
    "mutation",
    ["back_img1", "back_img3", "ad_iframe1", "ad_iframe3"],
)
async def test_comicdays_both_tail_families_reject_wrong_resource_counts(
    browser_page, case_html: str, mutation: str,
) -> None:
    """The tail shape is positive evidence; resource cardinality is part of it."""

    await browser_page.set_content(case_html)
    if mutation == "back_img1":
        script = "document.querySelector('.js-back-link-page .link-page-content img').remove()"
    elif mutation == "back_img3":
        script = "document.querySelector('.js-back-link-page .link-page-content').append(document.createElement('img'))"
    elif mutation == "ad_iframe1":
        script = "document.querySelector('.js-page-ad .ad-nav-area-wrap iframe').remove()"
    else:
        script = "document.querySelector('.js-page-ad .ad-nav-area-wrap').append(document.createElement('iframe'))"
    await browser_page.evaluate(script)
    adapter = ComicDaysAdapter()
    adapter._episode_id = "1"
    adapter.page_change_timeout_ms = 200
    previous = await adapter.get_content_identity(browser_page)
    with pytest.raises(PageChangeTimeoutError):
        await adapter.go_next(browser_page)
        await adapter.wait_for_change(browser_page, previous)


@pytest.mark.parametrize("slider", [16, 22])
async def test_comicdays_tail_slider_retrograde_or_out_of_range_fails_closed(
    browser_page, slider: int,
) -> None:
    await browser_page.set_content(TAIL_HTML)
    await browser_page.evaluate("(value) => { window.__tailState.sliderNow = value; }", slider)
    adapter = ComicDaysAdapter()
    adapter._episode_id = "1"
    adapter.page_change_timeout_ms = 200
    with pytest.raises(PageChangeTimeoutError):
        await adapter.go_next(browser_page)
        if slider == 16:
            await adapter.wait_for_change(
                browser_page,
                ContentIdentity(page_id="16,17", page_number=16, source_id="1", fingerprint="body"),
            )


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
            now.textContent = '7'; document.querySelector('.js-viewer-slider-pagenum-last').textContent = '8';
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
    assert len(result.pages) == 4
    assert [page.identity.page_id for page in result.pages] == ["1", "2,3", "2,3", "4"]
    manifest = json.loads((tmp_path / "runner-output" / "manifest.json").read_text(encoding="utf-8"))
    assert [page["identity"]["page_id"] for page in manifest["pages"]] == ["1", "2,3", "2,3", "4"]
    assert [page.get("metadata", {}).get("part") for page in manifest["pages"]] == [None, 1, 2, None]
    package = package_crawl_output(
        tmp_path / "runner-output",
        adapter.get_output_metadata(),
        library_dir=tmp_path / "runner-library",
    )
    with zipfile.ZipFile(package.archive_path) as archive:
        assert len(archive.namelist()) == 4


async def test_comicdays_runner_returns_next_content_after_episode_url_change(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def episode_id(url: str) -> str | None:
        return "2" if "#episode2" in url else "1"

    monkeypatch.setattr(adapter_module, "parse_comicdays_episode_url", episode_id)
    monkeypatch.setattr(
        adapter_module,
        "canonical_comicdays_episode_url",
        lambda url: f"https://comic-days.com/episode/{episode_id(url)}",
    )
    monkeypatch.setattr(adapter_module, "_series_id_from_page", lambda _page: _completed("series"))
    adapter = ComicDaysAdapter()
    adapter.resolve_initial_navigation_url = lambda _source_url: "data:text/html," + quote(NEXT_CONTENT_HTML)  # type: ignore[method-assign]
    result = await CrawlerRunner(
        RunConfig(
            site="comicdays",
            source_url="https://comic-days.com/episode/1",
            output_dir=tmp_path / "next-output",
            diagnostics_dir=tmp_path / "next-diagnostics",
            access_strategy="direct",
            page_turn_delay_ms=0,
            max_pages=5,
            page_change_timeout_ms=1_000,
        )
    ).run(browser_page, adapter)
    assert result.stop_state is PageState.NEXT_CONTENT
    assert len(result.pages) == 1


async def test_comicdays_runner_detects_canonical_next_episode_and_old_viewer_removal(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """A real canonical navigation is NEXT_CONTENT only when the episode changes."""

    initial_url = "https://comic-days.com/episode/1"
    next_url = "https://comic-days.com/episode/2"
    initial_html = NEXT_CONTENT_HTML.replace(
        "history.pushState({}, '', '#episode2')",
        f"location.href = {next_url!r}",
    )
    next_html = "<html><body><h1>next episode</h1></body></html>"

    async def fulfill(route):
        body = initial_html if route.request.url == initial_url else next_html
        await route.fulfill(status=200, content_type="text/html", body=body)

    await browser_page.route("https://comic-days.com/episode/*", fulfill)

    def episode_id(url: str) -> str | None:
        if url.rstrip("/").endswith("/episode/1"):
            return "1"
        if url.rstrip("/").endswith("/episode/2"):
            return "2"
        return None

    monkeypatch.setattr(adapter_module, "parse_comicdays_episode_url", episode_id)
    monkeypatch.setattr(
        adapter_module,
        "canonical_comicdays_episode_url",
        lambda url: f"https://comic-days.com/episode/{episode_id(url)}"
        if episode_id(url) is not None else url,
    )
    monkeypatch.setattr(adapter_module, "_series_id_from_page", lambda _page: _completed("series"))
    adapter = ComicDaysAdapter()
    adapter.resolve_initial_navigation_url = lambda _source_url: initial_url  # type: ignore[method-assign]
    result = await CrawlerRunner(
        RunConfig(
            site="comicdays",
            source_url=initial_url,
            output_dir=tmp_path / "next-canonical-output",
            diagnostics_dir=tmp_path / "next-canonical-diagnostics",
            access_strategy="direct",
            page_turn_delay_ms=0,
            max_pages=5,
            page_change_timeout_ms=1_000,
        )
    ).run(browser_page, adapter)
    assert result.stop_state is PageState.NEXT_CONTENT
    assert len(result.pages) == 1
    assert browser_page.url == next_url
    assert await browser_page.locator("section.viewer.js-viewer").count() == 0
    assert await browser_page.locator(".js-viewer-slider-pagenum-now").count() == 0


async def test_comicdays_non_episode_redirect_is_not_next_content(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An access/unknown redirect must remain bounded UNKNOWN/LOADING."""

    html = NEXT_CONTENT_HTML.replace(
        "history.pushState({}, '', '#episode2')",
        "location.href = 'https://comic-days.com/account/login'",
    )
    adapter = ComicDaysAdapter()
    await browser_page.goto("data:text/html,<html></html>")
    await adapter.prepare_page(browser_page)
    await browser_page.reload()
    await browser_page.set_content(html)
    await _paint_sources(browser_page, "canvas.page-image")
    monkeypatch.setattr(adapter_module, "parse_comicdays_episode_url", lambda _url: "1")
    adapter._episode_id = "1"
    adapter.page_change_timeout_ms = 200
    previous = await adapter.get_content_identity(browser_page)
    await adapter.go_next(browser_page)
    with pytest.raises(PageChangeTimeoutError):
        await adapter.wait_for_change(browser_page, previous)
    assert await adapter.detect_state(browser_page) is not PageState.NEXT_CONTENT


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

    async def bulk(_page, _series: str, *, expected_total: int) -> list[dict]:
        assert expected_total == 2
        return [
            {
                "readable_product_id": "2",
                "viewer_uri": "https://comic-days.com/episode/2",
                "purchase_info": {"can_read": False, "is_free": False, "has_rented_via_ticket": False, "rentable_via_ticket": False, "unavailable": False, "has_purchased": False, "has_rented_via_point": False},
                "status": {"is_support_ticket": False, "buy_price": 100, "rental_price": None, "rental_end_at": None, "rental_term": None},
            },
            {
                "readable_product_id": "1",
                "viewer_uri": "https://comic-days.com/episode/1",
                "purchase_info": {"can_read": True, "is_free": True, "has_rented_via_ticket": False, "rentable_via_ticket": False, "unavailable": False, "has_purchased": False, "has_rented_via_point": False},
                "status": {"is_support_ticket": False, "buy_price": None, "rental_price": None, "rental_end_at": None, "rental_term": None},
            },
        ]

    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_readable_products", bulk)
    target = WatchlistTarget("key", "work", "comicdays", "https://comic-days.com/episode/1", "Synthetic Work")
    rows = [
        row
        async for row in discovery_module.ComicDaysDiscoveryAdapter().iter_records(
            browser_page, target, "full"
        )
    ]
    assert [row.source.external_id for row in rows] == ["2", "1"]
    assert [row.source.access_mode for row in rows] == ["paid", "free"]


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


@pytest.mark.parametrize("property_name", ["visibility", "opacity"])
async def test_comicdays_invisible_canvas_is_loading(
    browser_page, monkeypatch: pytest.MonkeyPatch, property_name: str
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    await browser_page.evaluate(
        "(name) => document.querySelector('#body-one canvas').style[name] = name === 'opacity' ? '0' : 'hidden'",
        property_name,
    )
    assert await adapter.detect_state(browser_page) is PageState.LOADING


async def test_comicdays_hidden_second_body_area_is_loading(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A delayed spread area cannot be reduced to a successful one-page capture."""

    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    await browser_page.evaluate(
        """() => {
          document.querySelector('#body-one').style.display = 'none';
          document.querySelector('#body-two').style.display = 'block';
          document.querySelector('#body-three').style.display = 'none';
          document.querySelector('.js-viewer-slider-pagenum-now').textContent = '3';
        }"""
    )
    await _paint_sources(browser_page, '#body-two canvas')
    assert await adapter.detect_state(browser_page) is PageState.LOADING


@pytest.mark.parametrize("mutation", ["area_removed", "canvas_removed", "ancestor_overflow"])
async def test_comicdays_incomplete_second_spread_part_is_loading(
    browser_page, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    await browser_page.evaluate(
        """mutation => {
          const now = document.querySelector('.js-viewer-slider-pagenum-now');
          now.textContent = '3';
          document.querySelector('#body-one').style.display = 'none';
          document.querySelector('#body-two').style.display = 'block';
          document.querySelector('#body-three').style.display = 'block';
          if (mutation === 'area_removed') document.querySelector('#body-three').remove();
          if (mutation === 'canvas_removed') document.querySelector('#body-three').innerHTML = '';
          if (mutation === 'ancestor_overflow') {
            const area = document.querySelector('#body-three');
            area.style.width = '1px'; area.style.overflow = 'hidden';
          }
        }""",
        mutation,
    )
    await _paint_sources(browser_page, '#body-two canvas,#body-three canvas')
    assert await adapter.detect_state(browser_page) is PageState.LOADING


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


async def test_comicdays_capture_rechecks_generation_after_jpeg_reconstruction(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = await _initialized_comicdays_adapter(browser_page, monkeypatch)
    monkeypatch.setattr(
        adapter_module,
        "reconstruct_jpeg",
        lambda _raw, _plan: CaptureResult(data=b"jpeg", width=1, height=1, mime_type="image/jpeg", file_extension=".jpg"),
    )
    original_active = adapter._active
    calls = 0

    async def stale_after_reconstruction(page, *, timeout_ms=None):
        nonlocal calls
        calls += 1
        state = await original_active(page, timeout_ms=timeout_ms)
        if calls >= 3:
            rows = [dict(row) for row in state.get("rows", [])]
            for row in rows:
                if isinstance(row.get("base"), dict):
                    row["base"] = {**row["base"], "sourceId": "stale-after-dct"}
            state["rows"] = rows
        return state

    monkeypatch.setattr(adapter, "_active", stale_after_reconstruction)
    with pytest.raises(LookupError, match="JPEG reconstruction"):
        await adapter.capture_page(browser_page)
    assert calls >= 3
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
