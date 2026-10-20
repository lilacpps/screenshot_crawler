from __future__ import annotations

from urllib.parse import quote

import pytest

from screenshot_crawler.core.errors import UnknownPageStateError, UnsupportedAccessStrategyError
from screenshot_crawler.site_adapters.yanmaga import (
    YanmagaAdapter,
    parse_yanmaga_composite_id,
    parse_yanmaga_page_counter,
    parse_yanmaga_viewer_url,
)
from screenshot_crawler.site_adapters.yanmaga.adapter import (
    _BodyPage,
    _ImageSegment,
    _ReaderSnapshot,
)

SLUG = "ウサギとカメのゆる山歩"
EPISODE_ID = "2de76848d607c9920f18147b763a6aec"
SOURCE_URL = f"https://yanmaga.jp/comics/{SLUG}/{EPISODE_ID}"


def test_composite_identity_and_viewer_route_are_work_bound() -> None:
    identity = f"{SLUG}:{EPISODE_ID}"

    assert parse_yanmaga_composite_id(identity) == (SLUG, EPISODE_ID)
    assert parse_yanmaga_viewer_url(
        f"https://yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}"
    ) is not None
    assert parse_yanmaga_viewer_url(
        f"https://yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}?cid=AbCd0123456789EfGhIj"
    ) == parse_yanmaga_viewer_url(
        f"https://yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}"
    )
    assert parse_yanmaga_composite_id(f"other:{EPISODE_ID}") == ("other", EPISODE_ID)
    assert parse_yanmaga_viewer_url(
        f"https://yanmaga.jp/viewer/comics/other/{EPISODE_ID}"
    ) != parse_yanmaga_viewer_url(
        f"https://yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}"
    )
    for url in (
        f"http://yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}",
        f"https://www.yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}",
        f"https://yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}?reading=1",
        f"https://yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}?cid=AbCd0123456789EfGhIj&cid=AbCd0123456789EfGhIj",
        f"https://yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}?cid=AbCd0123456789EfGhIj&x=1",
        f"https://yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}?cid=AbCd0123456789EfGhG!",
        f"https://yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}?cid=AbCd0123456789EfGhI",
        f"https://yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}#page-1",
    ):
        assert parse_yanmaga_viewer_url(url) is None


@pytest.mark.asyncio
async def test_composite_identity_is_configured_and_source_url_is_retained() -> None:
    adapter = YanmagaAdapter()
    await adapter.configure_target_identity(f"{SLUG}:{EPISODE_ID}", "watchlist-main")

    work_url = adapter.resolve_initial_navigation_url(SOURCE_URL)

    assert work_url == f"https://yanmaga.jp/comics/{quote(SLUG, safe='')}"
    assert adapter._source_url == SOURCE_URL
    assert adapter._expected_external_id == f"{SLUG}:{EPISODE_ID}"

    with pytest.raises(UnknownPageStateError):
        adapter.resolve_initial_navigation_url(
            f"https://yanmaga.jp/comics/別作品/{EPISODE_ID}"
        )
    with pytest.raises(UnknownPageStateError):
        await adapter.configure_target_identity("other:bad-id", "watchlist-main")


@pytest.mark.asyncio
async def test_only_auto_and_direct_strategies_are_supported() -> None:
    adapter = YanmagaAdapter()

    await adapter.configure_run(None, "auto")
    await adapter.configure_run(None, "direct")
    await adapter.configure_quota_resource(None, None)

    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_run(None, "quota")
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_quota_resource(None, "ticket")


def test_page_counter_is_bounded_and_consistent() -> None:
    assert parse_yanmaga_page_counter(" 1/36 ") == (1, 36)
    assert parse_yanmaga_page_counter("36/36") == (36, 36)
    for value in (None, "0/36", "37/36", "1/0", "1 / 36", "1/2001", "1/2/3"):
        assert parse_yanmaga_page_counter(value) is None


def test_rendered_body_wrapper_requires_three_loaded_contiguous_segments() -> None:
    segments = (
        _ImageSegment(1127, 536, True, 10, 20, 1266, 602, "fixture-a"),
        _ImageSegment(1127, 536, True, 10, 618, 1266, 602, "fixture-b"),
        _ImageSegment(1127, 538, True, 10, 1216, 1266, 604, "fixture-c"),
    )
    page = _BodyPage(1, 10, 20, 1266, 1800, True, False, True, segments)

    assert YanmagaAdapter._segments_form_observed_page(page)
    assert not YanmagaAdapter._segments_form_observed_page(
        _BodyPage(1, 10, 20, 1266, 1800, True, False, True, segments[:2])
    )
    gap = (
        segments[0],
        _ImageSegment(1127, 536, True, 10, 630, 1266, 602, "fixture-d"),
        segments[2],
    )
    assert not YanmagaAdapter._segments_form_observed_page(
        _BodyPage(1, 10, 20, 1266, 1800, True, False, True, gap)
    )
    thin = (
        _ImageSegment(1127, 536, True, 10, 20, 1, 602, "fixture-thin"),
        segments[1],
        segments[2],
    )
    assert not YanmagaAdapter._segments_form_observed_page(
        _BodyPage(1, 10, 20, 1266, 1800, True, False, True, thin)
    )
    oversized_last = (
        segments[0],
        segments[1],
        _ImageSegment(1127, 538, True, 10, 1216, 1266, 700, "fixture-oversized"),
    )
    assert not YanmagaAdapter._segments_form_observed_page(
        _BodyPage(1, 10, 20, 1266, 1800, True, False, True, oversized_last)
    )


def test_rendered_body_wrapper_accepts_measured_rounding_and_overlap() -> None:
    segments = (
        _ImageSegment(1127, 536, True, 0, 0, 1267.8646, 603, "measured-a"),
        _ImageSegment(1127, 536, True, 0, 598.5, 1267.8646, 603, "measured-b"),
        _ImageSegment(1127, 538, True, 0, 1197, 1267.8646, 605.2396, "measured-c"),
    )
    page = _BodyPage(36, 0, 0, 1265.625, 1800, True, False, True, segments)

    assert YanmagaAdapter._segments_form_observed_page(page)


def test_visible_body_page_must_be_whole_and_unobstructed() -> None:
    adapter = YanmagaAdapter()
    adapter._total_pages = 4
    segments = (
        _ImageSegment(1127, 536, True, 0, 0, 1266, 602, "fixture-a"),
        _ImageSegment(1127, 536, True, 0, 598, 1266, 602, "fixture-b"),
        _ImageSegment(1127, 538, True, 0, 1196, 1266, 602, "fixture-c"),
    )
    page = _BodyPage(1, 0, 0, 1266, 1800, True, False, True, segments)
    for partial, center_owned, perimeter_owned in (
        (True, True, True),
        (False, False, True),
        (False, True, False),
    ):
        snapshot = _ReaderSnapshot(
            counter_text="1/4",
            current=1,
            total=4,
            viewport_width=2560,
            viewport_height=1800,
            page_container_count=1,
            body_pages=(
                _BodyPage(
                    page.index,
                    page.x,
                    page.y,
                    page.width,
                    page.height,
                    page.visible,
                    partial,
                    center_owned,
                    page.segments,
                    perimeter_owned,
                ),
            ),
            auxiliary_ids=("ads", "recommend", "rental"),
            duplicate_indices=False,
            rental_count=1,
            rental_visible=False,
            rental_presented=False,
            rental_geometry=None,
            rental_title=None,
            rental_title_presented=False,
            rental_title_geometry=None,
            rental_next_label=None,
            rental_next_presented=False,
            rental_next_geometry=None,
            rental_next_count=0,
            access_gate_visible=False,
            next_arrow_count=1,
            next_arrow_hidden=False,
            next_arrow_parent_id="arrow-content",
            next_arrow_parent_hidden=False,
        )
        with pytest.raises(UnknownPageStateError):
            adapter._validate_snapshot(snapshot)


def test_visible_quota_gate_is_not_a_body_page() -> None:
    adapter = YanmagaAdapter()
    adapter._total_pages = 4
    segments = (
        _ImageSegment(1127, 536, True, 0, 0, 1266, 602, "fixture-a"),
        _ImageSegment(1127, 536, True, 0, 598, 1266, 602, "fixture-b"),
        _ImageSegment(1127, 538, True, 0, 1196, 1266, 602, "fixture-c"),
    )
    snapshot = _ReaderSnapshot(
        counter_text="1/4",
        current=1,
        total=4,
        viewport_width=2560,
        viewport_height=1800,
        page_container_count=1,
        body_pages=(_BodyPage(1, 0, 0, 1266, 1800, True, False, True, segments),),
        auxiliary_ids=("ads", "recommend", "rental"),
        duplicate_indices=False,
        rental_count=1,
        rental_visible=False,
        rental_presented=False,
        rental_geometry=None,
        rental_title=None,
        rental_title_presented=False,
        rental_title_geometry=None,
        rental_next_label=None,
        rental_next_presented=False,
        rental_next_geometry=None,
        rental_next_count=0,
        access_gate_visible=True,
        next_arrow_count=1,
        next_arrow_hidden=False,
        next_arrow_parent_id="arrow-content",
        next_arrow_parent_hidden=False,
    )

    with pytest.raises(UnknownPageStateError, match="resource gate"):
        adapter._validate_snapshot(snapshot)
