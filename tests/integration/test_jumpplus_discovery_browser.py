from __future__ import annotations

import pytest

from screenshot_crawler.site_adapters.jumpplus.discovery import (
    _LISTING_SNAPSHOT_SCRIPT,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


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
