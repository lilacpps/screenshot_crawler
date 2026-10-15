from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image
from playwright.async_api import Page, Route

from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.zeblack.adapter import ZeblackAdapter

pytestmark = pytest.mark.asyncio(loop_scope="module")

TARGET = "https://zebrack-comic.shueisha.co.jp/title/37/chapter/50213/viewer"


def _image(color: str, *, format: str = "JPEG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 96), color).save(buffer, format=format)
    return buffer.getvalue()


def _viewer_html(*, next_story: bool) -> str:
    next_control = '<button id="next-story">次の話を読む</button>' if next_story else ""
    return f"""
    <meta charset="utf-8">
    <style>
      body {{ margin: 0; }}
      #content img {{ width: 64px; height: 96px; }}
      #ad, #final {{ display: none; width: 400px; min-height: 300px; }}
      ._b9ZNa_embed {{ width: 400px; min-height: 280px; }}
      #banner {{ width: 64px; height: 48px; }}
    </style>
    <div id="content"></div>
    <div id="ad" class="-KWKsa_spread"><iframe srcdoc="fixture ad"></iframe></div>
    <div id="final" class="-KWKsa_spread">
      <div class="_b9ZNa_embed">
        <a><img id="banner" src="/assets/app_appeal-fixture.png"></a>
        {next_control}
        <button id="comment"><p>コメントする</p><p>1</p></button>
        <button id="favorite"><p>お気に入り</p><p>2</p></button>
        <div id="recommendations">あなたへのおすすめ</div>
      </div>
    </div>
    <p id="counter">1 / 4</p>
    <script>
      window.stage = 0;
      window.keyCount = 0;
      window.nextClicks = 0;
      const content = document.querySelector('#content');
      const ad = document.querySelector('#ad');
      const final = document.querySelector('#final');
      const counter = document.querySelector('#counter');
      window.showFinal = () => {{
        content.style.display = 'none';
        ad.style.display = 'none';
        final.style.display = 'block';
        counter.textContent = '4 / 4';
      }};
      document.querySelector('#next-story')?.addEventListener('click', () => {{
        window.nextClicks += 1;
        history.pushState({{}}, '', '/title/37/chapter/50214/viewer');
      }});
      document.addEventListener('keydown', event => {{
        if (event.key !== 'ArrowLeft') return;
        window.keyCount += 1;
        window.stage += 1;
        if (window.stage === 1) {{
          document.querySelector('[alt="page_0"]').style.display = 'none';
          document.querySelector('[alt="page_1"]').style.display = 'block';
          counter.textContent = '2 / 4';
        }} else if (window.stage === 2) {{
          content.style.display = 'none';
          ad.style.display = 'block';
          counter.textContent = '3 / 4';
        }} else {{ window.showFinal(); }}
      }});
      window.ready = (async () => {{
        for (let index = 0; index < 2; index++) {{
          const response = await fetch('/fixture-' + index + '.jpg');
          const image = new Image();
          image.alt = 'page_' + index;
          image.src = URL.createObjectURL(await response.blob());
          image.style.display = index === 0 ? 'block' : 'none';
          content.appendChild(image);
          await image.decode();
        }}
        await document.querySelector('#banner').decode();
      }})();
    </script>
    """


async def _install_viewer(page: Page, *, next_story: bool = False) -> None:
    html = _viewer_html(next_story=next_story)

    async def route(request: Route) -> None:
        path = request.request.url
        if path == TARGET:
            await request.fulfill(body=html, content_type="text/html")
        elif path.endswith("/fixture-0.jpg"):
            await request.fulfill(body=_image("red"), content_type="image/jpeg")
        elif path.endswith("/fixture-1.jpg"):
            await request.fulfill(body=_image("blue"), content_type="image/jpeg")
        elif path.endswith("/assets/app_appeal-fixture.png"):
            await request.fulfill(body=_image("green", format="PNG"), content_type="image/png")
        else:
            await request.abort()

    await page.route("**/*", route)
    # Runner navigates again after installing its native Blob response listener.
    await page.goto(TARGET)
    await page.evaluate("window.ready")


@pytest.mark.parametrize("next_story", [False, True], ids=["final-chapter", "next-chapter"])
async def test_zeblack_runner_stops_after_content_and_ad_without_capturing_end_card(
    browser_page: Page, tmp_path: Path, next_story: bool
) -> None:
    await _install_viewer(browser_page, next_story=next_story)
    adapter = ZeblackAdapter()
    adapter.page_change_timeout_ms = 1_000
    output = tmp_path / "crawl"
    runner = CrawlerRunner(RunConfig(
        site="zeblack", source_url=TARGET, output_dir=output,
        diagnostics_dir=output / "diagnostics", access_strategy="direct",
        max_pages=2, page_turn_delay_ms=0,
    ))
    try:
        result = await runner.run(browser_page, adapter)
        assert result.stop_state is (PageState.NEXT_CONTENT if next_story else PageState.END)
        assert len(result.pages) == 2
        assert [entry.identity.page_id for entry in result.pages] == ["page_0", "page_1"]
        assert all((entry.width, entry.height) == (64, 96) for entry in result.pages)
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        assert len(manifest["pages"]) == 2
        assert len(list(output.glob("page-*"))) == 2
        assert not (output / "diagnostics").exists()
        assert browser_page.url == TARGET
        assert await browser_page.evaluate("window.keyCount") == 3
        assert await browser_page.evaluate("window.nextClicks") == 0
        assert adapter.get_access_consumption().consumed is False
    finally:
        await adapter._clear_source_cache()


@pytest.mark.parametrize(
    "fault",
    [
        "banner", "comment", "favorite", "recommendations", "counter", "counter-not-last",
        "counter-duplicate", "counter-zero", "outside-spread", "offscreen", "hidden",
        "transparent-parent", "next-hidden", "duplicate-card", "markers-outside-card",
        "active-content", "foreign-url", "other-chapter",
    ],
)
async def test_zeblack_final_card_requires_complete_current_viewer_evidence(
    browser_page: Page, fault: str
) -> None:
    await _install_viewer(browser_page)
    adapter = ZeblackAdapter()
    adapter.resolve_initial_navigation_url(TARGET)
    await browser_page.evaluate("window.showFinal()")
    assert await adapter._end_page_signal(browser_page) is True
    # An end card alone, before a verified transition, cannot finish a crawl.
    assert await adapter.detect_state(browser_page) is PageState.UNKNOWN
    await browser_page.evaluate("""fault => {
      const card = document.querySelector('._b9ZNa_embed');
      const final = document.querySelector('#final');
      const counter = document.querySelector('#counter');
      if (['banner', 'comment', 'favorite', 'recommendations', 'counter'].includes(fault)) {
        document.querySelector('#' + fault).remove();
      } else if (fault === 'counter-not-last') { counter.textContent = '3 / 4';
      } else if (fault === 'counter-duplicate') { counter.after(counter.cloneNode(true));
      } else if (fault === 'counter-zero') { counter.textContent = '0 / 0';
      } else if (fault === 'outside-spread') { document.body.appendChild(card);
      } else if (fault === 'offscreen') { final.style.transform = 'translateX(200vw)';
      } else if (fault === 'hidden') { final.style.display = 'none';
      } else if (fault === 'transparent-parent') { final.style.opacity = '0';
      } else if (fault === 'next-hidden') {
        card.insertAdjacentHTML('beforeend', '<button hidden>次の話を読む</button>');
      } else if (fault === 'duplicate-card') { final.appendChild(card.cloneNode(true));
      } else if (fault === 'markers-outside-card') {
        document.body.appendChild(document.querySelector('#recommendations'));
      } else if (fault === 'active-content') {
        document.querySelector('#content').style.display = 'block';
      } else if (fault === 'foreign-url') { history.pushState({}, '', '/title/37/chapter/list');
      } else if (fault === 'other-chapter') {
        history.pushState({}, '', '/title/37/chapter/50214/viewer');
      }
    }""", fault)
    adapter._transition_stable = True
    adapter._transition_kind = "terminal_end"
    expected = (
        PageState.CONTENT if fault == "active-content" else
        PageState.NEXT_CONTENT if fault == "other-chapter" else PageState.UNKNOWN
    )
    assert await adapter.detect_state(browser_page) is expected
