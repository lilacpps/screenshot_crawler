from __future__ import annotations

import pytest

from screenshot_crawler.site_adapters.jumpplus.discovery import (
    _LISTING_SNAPSHOT_SCRIPT,
    JumpPlusDiscoveryAdapter,
)
from screenshot_crawler.watchlist import WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_jumpplus_complete_listing_uses_range_slots_not_chapter_numbers(browser_page) -> None:
    html = """
    <meta charset="utf-8">
    <section class="series-information type-episode" data-giga_series="series-fixture">
      <h1 class="series-header-title">Synthetic work</h1>
      <div class="js-readable-products-pagination"><div id="pagination-top">
        <button id="range-0" aria-selected="true" onclick="selectRange(0)">4 - 3</button>
        <button id="range-1" aria-selected="false" onclick="selectRange(1)">2 - 1</button>
        <ul class="series-episode-list" id="episodes"></ul>
      </div></div>
    </section>
    <script>
      const groups = [[['400', 3], ['300', 2]], [['200', 1], ['100', 0]]];
      function selectRange(index) {
        document.getElementById('episodes').innerHTML = groups[index].map(([id, number]) =>
          `<li><a href="/episode/${id}"><h3>第${number}話</h3></a>
          <span class="series-episode-list-is-free">無料</span></li>`).join('');
        groups.forEach((_, i) => document.getElementById(`range-${i}`).setAttribute('aria-selected', String(i === index)));
      }
      selectRange(0);
    </script>
    """
    await browser_page.route("https://shonenjumpplus.com/**", lambda route: route.fulfill(
        status=200, content_type="text/html; charset=utf-8", body=html,
    ))
    target = WatchlistTarget("fixture", "fixture", "jumpplus",
                            "https://shonenjumpplus.com/episode/400", "Synthetic work")
    preview = await JumpPlusDiscoveryAdapter().preview_complete_listing(browser_page, target)
    assert preview.ready
    assert [row.external_id for row in preview.rows] == ["400", "300", "200", "100"]
    assert [row.site_position for row in preview.rows] == [4, 3, 2, 1]
    assert [row.display_title for row in preview.rows] == ["第3話", "第2話", "第1話", "第0話"]


async def test_jumpplus_snapshot_includes_single_numeric_range_only(browser_page) -> None:
    await browser_page.set_content(
        """
        <section class="series-information type-episode" data-giga_series="series-1">
          <div class="js-readable-products-pagination">
            <div id="pagination-top">
              <ul class="series-episode-list">
                <li><a id="episode-link" href="https://shonenjumpplus.com/episode/123">1</a></li>
              </ul>
              <button id="range-latest">101 - 2</button>
              <button id="range-last">1</button>
              <button id="more">もっと見る</button>
            </div>
          </div>
        </section>
        """
    )

    snapshot = await browser_page.evaluate(
        _LISTING_SNAPSHOT_SCRIPT,
        {"targetEpisodeId": "123"},
    )

    assert [control["text"] for control in snapshot["range_controls"]] == [
        "101 - 2",
        "1",
    ]
    assert [control["text"] for control in snapshot["more_controls"]] == ["もっと見る"]
