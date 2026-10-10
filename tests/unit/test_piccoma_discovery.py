from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from screenshot_crawler.discovery import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.piccoma.discovery import (
    BINGE_FREE_MARKER,
    FREE_MARKER,
    GRANTED_MARKER,
    POINT_MARKER,
    WAIT_FREE_MARKER,
    PiccomaEpisodeIdentity,
    _parse_listing_rows,
    canonical_piccoma_viewer_url,
    classify_piccoma_access,
    parse_piccoma_listing_url,
    parse_piccoma_viewer_url,
)
from screenshot_crawler.watchlist import DiscoveryScope


def test_piccoma_viewer_identity_is_product_scoped() -> None:
    identity = parse_piccoma_viewer_url("https://piccoma.com/web/viewer/28600/1910027")

    assert identity == PiccomaEpisodeIdentity("28600", "1910027")
    assert identity is not None
    assert identity.external_id == "28600:1910027"
    assert canonical_piccoma_viewer_url("https://www.piccoma.com/web/viewer/28600/1910027/") == (
        "https://piccoma.com/web/viewer/28600/1910027"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://piccoma.com/web/viewer/28600/1910027",
        "https://example.test/web/viewer/28600/1910027",
        "https://piccoma.com/web/product/28600/episodes",
        "https://piccoma.com/web/viewer/28600/1910027?campaign=1",
        "https://piccoma.com/web/viewer/28600/1910027#page=2",
        "https://piccoma.com:bad/web/viewer/28600/1910027",
        "/web/viewer/28600/1910027",
    ],
)
def test_piccoma_viewer_parser_rejects_ambiguous_or_foreign_urls(url: str) -> None:
    assert parse_piccoma_viewer_url(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://piccoma.com/web/product/900/episodes",
        "https://example.test/web/product/900/episodes",
        "https://user@piccoma.com/web/product/900/episodes",
        "https://piccoma.com:444/web/product/900/episodes",
        "https://piccoma.com:bad/web/product/900/episodes",
        "https://piccoma.com/web/product/901/episodes",
        "https://piccoma.com/web/product/900/episodes?sort=asc",
        "https://piccoma.com/web/product/900/episodes#top",
        "/web/product/900/episodes",
    ],
)
def test_piccoma_final_listing_url_parser_rejects_untrusted_urls(url: str) -> None:
    assert parse_piccoma_listing_url(url) != "900"


def test_piccoma_final_listing_url_parser_accepts_target_canonical_url() -> None:
    assert parse_piccoma_listing_url("https://www.piccoma.com/web/product/900/episodes") == "900"


@pytest.mark.parametrize(
    ("markers", "label", "expected"),
    [
        ([FREE_MARKER], "¥0", "free"),
        ([FREE_MARKER], "", "unknown"),
        ([FREE_MARKER, WAIT_FREE_MARKER], "¥0", "unknown"),
        ([FREE_MARKER], "¥0+", "unknown"),
        ([WAIT_FREE_MARKER, BINGE_FREE_MARKER], "", "quota"),
        ([WAIT_FREE_MARKER], "", "quota"),
        ([POINT_MARKER], "69", "paid"),
        ([POINT_MARKER], "", "unknown"),
        ([POINT_MARKER, FREE_MARKER], "69", "unknown"),
        (["PCM-epList_status_unknown"], "¥0", "unknown"),
        ([], "¥0", "unknown"),
        ([GRANTED_MARKER], "閲覧期限\n残り71時間", "quota"),
        ([GRANTED_MARKER], "閲覧期限 残り1時間", "quota"),
        ([GRANTED_MARKER], "閲覧期限 残り0時間", "unknown"),
        ([GRANTED_MARKER], "閲覧期限 残り30分", "unknown"),
        ([GRANTED_MARKER], "残り71時間", "unknown"),
        ([WAIT_FREE_MARKER], "閲覧期限 残り71時間", "quota"),
        ([GRANTED_MARKER, FREE_MARKER], "閲覧期限 残り71時間", "unknown"),
        ([GRANTED_MARKER, POINT_MARKER], "閲覧期限 残り71時間", "unknown"),
    ],
)
def test_piccoma_access_requires_exact_free_marker_and_price(
    markers: list[str], label: str, expected: str
) -> None:
    assert classify_piccoma_access(markers, label) == expected


def _row(
    episode_id: str,
    *,
    product_id: str = "900",
    title: str | None = None,
    markers: list[str] | None = None,
    label: str = "¥0",
    status_count: int = 1,
) -> dict[str, object]:
    return {
        "product_id": product_id,
        "episode_id": episode_id,
        "title": title if title is not None else f"Chapter {episode_id}",
        "status_count": status_count,
        "status_markers": markers if markers is not None else [FREE_MARKER],
        "status_label": label,
    }


def test_piccoma_full_listing_reverses_traversal_but_keeps_global_positions() -> None:
    records = _parse_listing_rows(
        rows=[_row("101"), _row("102"), _row("103"), _row("104")],
        product_id="900",
        canonical_title="Fixture Work",
        declared_count=4,
        scope=None,
    )

    assert [record.source.external_id for record in records] == [
        "900:104",
        "900:103",
        "900:102",
        "900:101",
    ]
    assert [record.source.global_display_position for record in records] == [4, 3, 2, 1]
    assert [record.item.order_label for record in records] == [
        "Chapter 104",
        "Chapter 103",
        "Chapter 102",
        "Chapter 101",
    ]
    assert [record.source.url for record in records] == [
        f"https://piccoma.com/web/viewer/900/{episode_id}"
        for episode_id in ("104", "103", "102", "101")
    ]


@pytest.mark.parametrize(
    ("markers", "label", "hours"),
    [
        ([GRANTED_MARKER], "閲覧期限\n残り71時間", 70),
        ([GRANTED_MARKER], "閲覧期限 残り2時間", 1),
        ([GRANTED_MARKER], "閲覧期限 残り1時間", 0),
        ([GRANTED_MARKER], "閲覧期限 残り0時間", None),
        ([GRANTED_MARKER], "閲覧期限 残り30分", None),
        ([WAIT_FREE_MARKER], "閲覧期限 残り71時間", None),
        ([GRANTED_MARKER, FREE_MARKER], "閲覧期限 残り71時間", None),
        ([FREE_MARKER], "¥0", None),
    ],
)
def test_piccoma_manual_grant_requires_exact_badge_and_records_conservative_expiry(
    markers: list[str], label: str, hours: int | None
) -> None:
    observed_at = datetime(2026, 10, 10, 4, tzinfo=UTC)
    record, = _parse_listing_rows(
        rows=[_row("101", markers=markers, label=label)],
        product_id="900",
        canonical_title="Fixture Work",
        declared_count=1,
        scope=None,
        observed_at=observed_at,
    )
    assert record.source.access_granted_until == (
        observed_at + timedelta(hours=hours) if hours is not None else None
    )
    assert record.source.access_checked_at == observed_at
    assert record.source.access_granted_until_observed is True
    assert record.source.free_until is None


@pytest.mark.parametrize(
    ("scope", "expected_ids", "expected_positions"),
    [
        (
            DiscoveryScope(
                from_url="https://piccoma.com/web/viewer/900/103",
                through_url="https://piccoma.com/web/viewer/900/102",
            ),
            ["900:103", "900:102"],
            [3, 2],
        ),
        (
            DiscoveryScope(from_url="https://piccoma.com/web/viewer/900/103"),
            ["900:103", "900:102", "900:101"],
            [3, 2, 1],
        ),
        (
            DiscoveryScope(through_url="https://piccoma.com/web/viewer/900/102"),
            ["900:104", "900:103", "900:102"],
            [4, 3, 2],
        ),
        (
            DiscoveryScope(
                from_url="https://piccoma.com/web/viewer/900/102",
                through_url="https://piccoma.com/web/viewer/900/102",
            ),
            ["900:102"],
            [2],
        ),
    ],
)
def test_piccoma_bounded_scope_is_inclusive_and_does_not_renumber(
    scope: DiscoveryScope,
    expected_ids: list[str],
    expected_positions: list[int],
) -> None:
    records = _parse_listing_rows(
        rows=[_row("101"), _row("102"), _row("103"), _row("104")],
        product_id="900",
        canonical_title="Fixture Work",
        declared_count=4,
        scope=scope,
    )

    assert [record.source.external_id for record in records] == expected_ids
    assert [record.source.global_display_position for record in records] == expected_positions


@pytest.mark.parametrize(
    "scope",
    [
        DiscoveryScope(),
        DiscoveryScope(from_url="https://example.test/web/viewer/900/103"),
        DiscoveryScope(from_url="https://piccoma.com/web/viewer/901/103"),
        DiscoveryScope(from_url="https://piccoma.com/web/viewer/900/999"),
        DiscoveryScope(
            from_url="https://piccoma.com/web/viewer/900/102",
            through_url="https://piccoma.com/web/viewer/900/103",
        ),
    ],
)
def test_piccoma_invalid_bounded_scope_fails_closed(scope: DiscoveryScope) -> None:
    with pytest.raises(DiscoveryIncompleteError):
        _parse_listing_rows(
            rows=[_row("101"), _row("102"), _row("103"), _row("104")],
            product_id="900",
            canonical_title="Fixture Work",
            declared_count=4,
            scope=scope,
        )


@pytest.mark.parametrize(
    ("rows", "count"),
    [
        ([_row("101"), _row("102"), _row("102")], 3),
        ([_row("101"), _row("102", product_id="901")], 2),
        ([_row("101"), _row("102", title="")], 2),
        ([_row("101"), _row("102", status_count=0)], 2),
        ([_row("101"), _row("102")], 3),
    ],
)
def test_piccoma_incomplete_or_ambiguous_listing_is_rejected_before_records(
    rows: list[dict[str, object]], count: int
) -> None:
    with pytest.raises(DiscoveryIncompleteError):
        _parse_listing_rows(
            rows=rows,
            product_id="900",
            canonical_title="Fixture Work",
            declared_count=count,
            scope=None,
        )
