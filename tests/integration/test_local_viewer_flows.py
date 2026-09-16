import json
from pathlib import Path

import pytest
from playwright.async_api import Error, Page, async_playwright

from screenshot_crawler.core.errors import (
    MaxPagesExceededError,
    PageChangeTimeoutError,
    UnknownPageStateError,
)
from screenshot_crawler.core.models import ContentContext, ContentIdentity, RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.mangaone.adapter import MangaOneAdapter

_IMAGE = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "width='200' height='300'%3E%3Crect width='200' height='300' fill='%23bada55'/%3E%3C/svg%3E"
)
_IMAGE_ALT = _IMAGE.replace("%23bada55", "%23255f9a")


@pytest.fixture
async def browser_page() -> Page:
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Error as exc:
        await playwright.stop()
        pytest.skip(f"Chromium is unavailable: {exc}")
    page = await browser.new_page(viewport={"width": 800, "height": 600})
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


class LocalViewerAdapter(SiteAdapter):
    def __init__(self, *, spread: bool = False) -> None:
        self.spread = spread

    async def initialize(self, page: Page) -> None:
        await page.wait_for_function("document.body.dataset.state !== undefined")
        await page.wait_for_function(
            "Array.from(document.images).every(image => image.complete && image.naturalWidth > 0)"
        )

    async def detect_state(self, page: Page) -> PageState:
        value = await page.locator("body").get_attribute("data-state")
        return PageState(value or PageState.UNKNOWN.value)

    async def get_capture_target(self, page: Page):
        return page.locator("#single")

    async def get_capture_targets(self, page: Page):
        if self.spread:
            return page.locator("#right"), page.locator("#left")
        return (await self.get_capture_target(page),)

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        body = page.locator("body")
        page_id = await body.get_attribute("data-identity")
        return ContentIdentity(page_id=page_id or None, source_id="fixture")

    async def get_content_context(self, page: Page) -> ContentContext:
        return ContentContext(content_id="fixture")

    async def go_next(self, page: Page) -> None:
        await page.locator("#next").click()

    async def wait_for_change(
        self, page: Page, previous_identity: ContentIdentity | None
    ) -> None:
        for _ in range(20):
            state = await self.detect_state(page)
            if state is not PageState.LOADING:
                return
            await page.wait_for_timeout(10)
        raise PageChangeTimeoutError("local fixture remained loading")


def local_viewer_html(steps: list[dict[str, object]]) -> str:
    serialized = json.dumps(steps)
    default_image = json.dumps(_IMAGE)
    return f"""
    <style>
      body {{ margin: 0; }}
      img {{ width: 200px; height: 300px; object-fit: fill; }}
      #right, #left {{ position: fixed; left: 0; top: 0; }}
      #next {{ position: fixed; left: 400px; top: 0; z-index: 5; }}
    </style>
    <img id="single" src="{_IMAGE}">
    <img id="right" src="{_IMAGE}" hidden>
    <img id="left" src="{_IMAGE}" hidden>
    <button id="next" type="button">next</button>
    <script>
      const steps = {serialized};
      let index = 0;
      function render() {{
        const step = steps[index];
        document.body.dataset.state = step.state;
        document.body.dataset.identity = step.identity || '';
        for (const image of document.querySelectorAll('img')) {{
          image.src = step.image || {default_image};
        }}
        document.querySelector('#single').hidden = step.state !== 'content' || !!step.spread;
        document.querySelector('#right').hidden = step.state !== 'content' || !step.spread;
        document.querySelector('#left').hidden = step.state !== 'content' || !step.spread;
        if (step.auto_to !== undefined) {{
          setTimeout(() => {{ index = step.auto_to; render(); }}, step.delay || 20);
        }}
      }}
      document.querySelector('#next').addEventListener('click', () => {{
        if (index + 1 < steps.length) {{ index += 1; render(); }}
      }});
      render();
    </script>
    """


async def install_route(page: Page, url: str, body: str) -> None:
    async def fulfill(route) -> None:
        await route.fulfill(body=body, content_type="text/html")

    await page.route(url, fulfill)


@pytest.mark.parametrize(
    ("steps", "expected_pages", "expected_stop"),
    [
        (
            [
                {"state": "content", "identity": "p1"},
                {"state": "content", "identity": "p2", "image": _IMAGE_ALT},
                {"state": "end"},
            ],
            2,
            PageState.END,
        ),
        (
            [
                {"state": "content", "identity": "p1"},
                {"state": "ad"},
                {"state": "content", "identity": "p2", "image": _IMAGE_ALT},
                {"state": "end"},
            ],
            2,
            PageState.END,
        ),
        (
            [
                {"state": "content", "identity": "p1"},
                {"state": "content", "identity": "p2", "image": _IMAGE_ALT},
                {"state": "next_content"},
            ],
            2,
            PageState.NEXT_CONTENT,
        ),
        (
            [
                {"state": "content", "identity": "p1"},
                {"state": "loading", "auto_to": 2},
                {"state": "content", "identity": "p2", "image": _IMAGE_ALT},
                {"state": "end"},
            ],
            2,
            PageState.END,
        ),
    ],
)
async def test_runner_local_dom_state_flows(
    browser_page: Page,
    tmp_path: Path,
    steps: list[dict[str, object]],
    expected_pages: int,
    expected_stop: PageState,
) -> None:
    url = "http://fixture.test/viewer"
    await install_route(browser_page, url, local_viewer_html(steps))
    result = await CrawlerRunner(
        RunConfig(
            site="fixture",
            source_url=url,
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
        )
    ).run(browser_page, LocalViewerAdapter())

    assert result.stop_state is expected_stop
    assert len(result.pages) == expected_pages
    assert len(list((tmp_path / "run").glob("page-*.png"))) == expected_pages


async def test_runner_local_dom_saves_spread_parts_with_same_pixels(
    browser_page: Page,
    tmp_path: Path,
) -> None:
    url = "http://fixture.test/spread"
    await install_route(
        browser_page,
        url,
        local_viewer_html(
            [
                {"state": "content", "identity": "spread-1", "spread": True},
                {"state": "end"},
            ]
        ),
    )

    result = await CrawlerRunner(
        RunConfig(
            site="fixture",
            source_url=url,
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
        )
    ).run(browser_page, LocalViewerAdapter(spread=True))

    assert result.stop_state is PageState.END
    assert len(result.pages) == 2
    assert [page.metadata["part"] for page in result.pages] == [1, 2]


async def test_runner_local_dom_same_identity_hits_same_content_guard(
    browser_page: Page,
    tmp_path: Path,
) -> None:
    url = "http://fixture.test/same"
    await install_route(
        browser_page,
        url,
        local_viewer_html(
            [
                {"state": "content", "identity": "same"},
                {"state": "content", "identity": "same"},
            ]
        ),
    )

    with pytest.raises(PageChangeTimeoutError, match="same content"):
        await CrawlerRunner(
            RunConfig(
                site="fixture",
                source_url=url,
                output_dir=tmp_path / "run",
                diagnostics_dir=tmp_path / "diagnostics",
                max_same_content=2,
            )
        ).run(browser_page, LocalViewerAdapter())


async def test_runner_local_dom_unknown_state_stops_without_capture(
    browser_page: Page,
    tmp_path: Path,
) -> None:
    url = "http://fixture.test/unknown"
    await install_route(
        browser_page,
        url,
        local_viewer_html([{"state": "unknown"}]),
    )

    with pytest.raises(UnknownPageStateError):
        await CrawlerRunner(
            RunConfig(
                site="fixture",
                source_url=url,
                output_dir=tmp_path / "run",
                diagnostics_dir=tmp_path / "diagnostics",
            )
        ).run(browser_page, LocalViewerAdapter())

    assert not list((tmp_path / "run").glob("page-*.png"))


async def test_runner_local_dom_unresolved_loading_times_out(
    browser_page: Page,
    tmp_path: Path,
) -> None:
    url = "http://fixture.test/loading"
    await install_route(
        browser_page,
        url,
        local_viewer_html([{"state": "loading"}]),
    )

    with pytest.raises(PageChangeTimeoutError, match="Loading state"):
        await CrawlerRunner(
            RunConfig(
                site="fixture",
                source_url=url,
                output_dir=tmp_path / "run",
                diagnostics_dir=tmp_path / "diagnostics",
                retry_count=1,
            )
        ).run(browser_page, LocalViewerAdapter())


@pytest.mark.parametrize("terminal_state", [PageState.END, PageState.NEXT_CONTENT])
async def test_runner_local_dom_exact_max_pages_can_stop(
    browser_page: Page,
    tmp_path: Path,
    terminal_state: PageState,
) -> None:
    url = f"http://fixture.test/max-{terminal_state.value}"
    await install_route(
        browser_page,
        url,
        local_viewer_html(
            [
                {"state": "content", "identity": "p1"},
                {"state": "content", "identity": "p2", "image": _IMAGE_ALT},
                {"state": terminal_state.value},
            ]
        ),
    )
    result = await CrawlerRunner(
        RunConfig(
            site="fixture",
            source_url=url,
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
            max_pages=2,
        )
    ).run(browser_page, LocalViewerAdapter())

    assert len(result.pages) == 2
    assert result.stop_state is terminal_state


async def test_runner_local_dom_content_after_max_pages_fails(
    browser_page: Page,
    tmp_path: Path,
) -> None:
    url = "http://fixture.test/max-exceeded"
    await install_route(
        browser_page,
        url,
        local_viewer_html(
            [
                {"state": "content", "identity": "p1"},
                {"state": "content", "identity": "p2", "image": _IMAGE_ALT},
            ]
        ),
    )

    with pytest.raises(MaxPagesExceededError):
        await CrawlerRunner(
            RunConfig(
                site="fixture",
                source_url=url,
                output_dir=tmp_path / "run",
                diagnostics_dir=tmp_path / "diagnostics",
                max_pages=1,
            )
        ).run(browser_page, LocalViewerAdapter())


def mangaone_html() -> str:
    return f"""
    <title>Fixture 第1話</title>
    <div class="viewer-container" style="width: 600px; height: 500px;">
      <img alt="page_0" src="{_IMAGE}" style="width: 200px; height: 300px;">
    </div>
    """


async def test_mangaone_image_gap_becomes_end_after_grace_period(
    browser_page: Page,
) -> None:
    url = "http://manga-one.test/manga/work/chapter/1"
    await install_route(browser_page, url, mangaone_html())
    await browser_page.goto(url)
    adapter = MangaOneAdapter()
    adapter.page_change_timeout_ms = 3_100
    await adapter.initialize(browser_page)
    identity = await adapter.get_content_identity(browser_page)
    await browser_page.locator("img[alt^='page_']").evaluate(
        "element => element.style.display = 'none'"
    )
    await adapter.go_next(browser_page)

    assert await adapter.detect_state(browser_page) is PageState.LOADING
    await adapter.wait_for_change(browser_page, identity)
    assert await adapter.detect_state(browser_page) is PageState.END


async def test_mangaone_graceful_end_and_chapter_change_are_distinct(
    browser_page: Page,
) -> None:
    first_url = "http://manga-one.test/manga/work/chapter/1"
    second_url = "http://manga-one.test/manga/work/chapter/2"
    await install_route(browser_page, first_url, mangaone_html())
    await install_route(browser_page, second_url, mangaone_html())
    await browser_page.goto(first_url)
    adapter = MangaOneAdapter()
    await adapter.initialize(browser_page)

    await browser_page.goto(second_url)
    assert await adapter.detect_state(browser_page) is PageState.NEXT_CONTENT

    await browser_page.goto(first_url)
    adapter = MangaOneAdapter()
    await adapter.initialize(browser_page)
    identity = await adapter.get_content_identity(browser_page)
    await browser_page.locator("img[alt^='page_']").evaluate(
        "element => element.style.display = 'none'"
    )
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, identity)
    assert await adapter.detect_state(browser_page) is PageState.END


async def test_mangaone_unknown_after_image_and_viewer_disappear_times_out(
    browser_page: Page,
) -> None:
    url = "http://manga-one.test/manga/work/chapter/unknown"
    await install_route(browser_page, url, mangaone_html())
    await browser_page.goto(url)
    adapter = MangaOneAdapter()
    adapter.page_change_timeout_ms = 500
    await adapter.initialize(browser_page)
    identity = await adapter.get_content_identity(browser_page)
    await browser_page.locator("img[alt^='page_']").evaluate("element => element.remove()")
    await browser_page.locator(".viewer-container").evaluate(
        "element => element.style.display = 'none'"
    )
    await adapter.go_next(browser_page)

    assert await adapter.detect_state(browser_page) is PageState.UNKNOWN
    with pytest.raises(PageChangeTimeoutError):
        await adapter.wait_for_change(browser_page, identity)
