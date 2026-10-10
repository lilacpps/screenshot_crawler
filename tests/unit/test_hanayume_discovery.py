from __future__ import annotations

import pytest

from screenshot_crawler.discovery import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.hanayume.discovery import (
    HanayumeEpisodeIdentity,
    HanayumeListingRow,
    _apply_discovery_scope,
    _parse_range_links,
    _records_from_rows,
    _validate_range_navigation,
    canonical_hanayume_episode_url,
    classify_hanayume_access,
    parse_hanayume_episode_url,
    parse_hanayume_work_url,
)
from screenshot_crawler.watchlist import DiscoveryScope

SEED_ID = "8c6f15923caa0"
WORK_ID = "1f9f5b0d4cd52"
BASE = "https://hanayume.com"


def _range_entries(
    *, current_page: int | None = None, selected_alias: bool = False, total: int = 32
):
    return [
        {
            "label": "最新話から",
            "href": f"{BASE}/episodes/{SEED_ID}/old",
            "current": current_page is None,
        },
        *[
            {
                "label": f"{start}-{min(start + 29, total)}",
                "href": (
                    f"{BASE}/episodes/{SEED_ID}"
                    if selected_alias and current_page == page_number
                    else f"{BASE}/episodes/{SEED_ID}/{page_number}"
                ),
                "current": current_page == page_number,
            }
            for page_number, start in enumerate(range(1, total + 1, 30), start=1)
        ],
        {
            "label": "...",
            "href": f"{BASE}/episodes/{SEED_ID}/1",
            "current": False,
        },
    ]


def test_hanayume_episode_and_work_urls_are_strict() -> None:
    assert parse_hanayume_episode_url(f"{BASE}/episodes/{SEED_ID}") is not None
    assert parse_hanayume_episode_url(
        f"https://www.hanayume.com/episodes/{SEED_ID}/"
    ) is not None
    assert canonical_hanayume_episode_url(
        f"https://www.hanayume.com/episodes/{SEED_ID}/"
    ) == f"{BASE}/episodes/{SEED_ID}"
    assert parse_hanayume_work_url(f"{BASE}/series/{WORK_ID}") == WORK_ID

    for value in (
        f"http://hanayume.com/episodes/{SEED_ID}",
        f"https://example.com/episodes/{SEED_ID}",
        f"https://user@hanayume.com/episodes/{SEED_ID}",
        f"https://hanayume.com:444/episodes/{SEED_ID}",
        f"{BASE}/episodes/{SEED_ID}?page=1",
        f"{BASE}/episodes/{SEED_ID}#reader",
        f"{BASE}/series/{WORK_ID}",
        f"{BASE}/episodes/{SEED_ID}/1",
        "https://hanayume.com/episodes/not-an-id",
    ):
        assert parse_hanayume_episode_url(value) is None


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (("無料",), "free"),
        (("今なら無料",), "unknown"),
        (("無料", "今なら無料"), "unknown"),
        (("購入",), "unknown"),
        (("待てば無料",), "unknown"),
        (("コイン",), "unknown"),
        ((), "unknown"),
        (("無料", "無料"), "unknown"),
    ],
)
def test_hanayume_access_classifier_requires_one_exact_observed_badge(
    labels: tuple[str, ...], expected: str
) -> None:
    result = classify_hanayume_access(labels)
    assert result.raw_labels == labels
    assert result.access_mode == expected


def test_hanayume_now_free_requires_verified_series_auth_and_one_exact_badge() -> None:
    now_free = "\u4eca\u306a\u3089\u7121\u6599"
    free = "\u7121\u6599"

    assert classify_hanayume_access((now_free,)).access_mode == "unknown"
    assert classify_hanayume_access(
        (now_free,), listing_authenticated=True
    ).access_mode == "free"
    for labels in ((now_free, free), (now_free, now_free), (free, now_free)):
        assert classify_hanayume_access(
            labels, listing_authenticated=True
        ).access_mode == "unknown"


def test_hanayume_range_links_validate_full_contiguous_coverage() -> None:
    ranges = _parse_range_links(_range_entries(), seed_id=SEED_ID)

    assert [(item.page_number, item.start_position, item.end_position) for item in ranges] == [
        (1, 1, 30),
        (2, 31, 32),
    ]
    assert [item.url for item in ranges] == [
        f"{BASE}/episodes/{SEED_ID}/1",
        f"{BASE}/episodes/{SEED_ID}/2",
    ]


@pytest.mark.parametrize(
    "entries",
    [
        [
            {"label": "1-30", "href": f"{BASE}/episodes/{SEED_ID}/1", "current": False},
            {"label": "32-32", "href": f"{BASE}/episodes/{SEED_ID}/2", "current": False},
        ],
        [
            {"label": "1-30", "href": f"{BASE}/episodes/{SEED_ID}/2", "current": False},
            {"label": "31-32", "href": f"{BASE}/episodes/{SEED_ID}/1", "current": False},
        ],
        [
            {"label": "1-30", "href": "https://example.com/episodes/8c6f15923caa0/1", "current": False},
            {"label": "31-32", "href": f"{BASE}/episodes/{SEED_ID}/2", "current": False},
        ],
        [
            {"label": "1-29", "href": f"{BASE}/episodes/{SEED_ID}/1", "current": False},
            {"label": "30-32", "href": f"{BASE}/episodes/{SEED_ID}/2", "current": False},
        ],
        [
            {"label": "1-30", "href": f"{BASE}/episodes/{SEED_ID}/1", "current": False},
            {"label": "31-32", "href": f"{BASE}/episodes/{SEED_ID}/2", "current": False},
            {"label": "31-32", "href": f"{BASE}/episodes/{SEED_ID}/2", "current": False},
        ],
    ],
)
def test_hanayume_invalid_range_set_fails_closed(entries) -> None:
    with pytest.raises(DiscoveryIncompleteError):
        _parse_range_links(entries, seed_id=SEED_ID)


@pytest.mark.parametrize("page_number", [1, 2, 10])
def test_hanayume_selected_seed_alias_is_narrow_and_work_scoped(page_number: int) -> None:
    entries = _range_entries(total=296)
    ranges = _parse_range_links(entries, seed_id=SEED_ID)
    selected = ranges[page_number - 1]
    _validate_range_navigation(
        _range_entries(current_page=page_number, selected_alias=True, total=296),
        seed_id=SEED_ID,
        ranges=ranges,
        selected=selected,
        actual_page_url=selected.url,
    )


@pytest.mark.parametrize(
    ("entries", "actual_page_url"),
    [
        pytest.param(
            _range_entries(current_page=2, selected_alias=True),
            f"{BASE}/episodes/{SEED_ID}/3",
            id="actual-page-url-mismatch",
        ),
        pytest.param(
            _range_entries(current_page=2),
            f"https://example.com/episodes/{SEED_ID}/2",
            id="foreign-page-url",
        ),
    ],
)
def test_hanayume_selected_range_requires_exact_actual_page_url(
    entries, actual_page_url: str
) -> None:
    ranges = _parse_range_links(_range_entries(), seed_id=SEED_ID)
    with pytest.raises(DiscoveryIncompleteError):
        _validate_range_navigation(
            entries,
            seed_id=SEED_ID,
            ranges=ranges,
            selected=ranges[1],
            actual_page_url=actual_page_url,
        )


@pytest.mark.parametrize(
    ("entries", "selected_index"),
    [
    (_range_entries(current_page=2), 0),
    (_range_entries(current_page=1) + [{"label": "1-30", "href": f"{BASE}/episodes/{SEED_ID}/1", "current": True}], 0),
    (_range_entries(current_page=1)[:-1] + [{"label": "31-32", "href": f"{BASE}/episodes/{SEED_ID}/3", "current": False}], 0),
    pytest.param(
        [
            {**entry, "href": f"{BASE}/episodes/{SEED_ID}"}
            if entry.get("label") == "1-30"
            else entry
            for entry in _range_entries(current_page=2, selected_alias=True)
        ],
        1,
        id="nonselected-seed-alias",
    ),
    pytest.param(
        [
            {**entry, "label": "1-30"}
            if entry.get("current") is True
            else entry
            for entry in _range_entries(current_page=2, selected_alias=True)
        ],
        1,
        id="selected-label-mismatch",
    ),
    pytest.param(
        [
            {**entry, "href": f"{BASE}/episodes/{SEED_ID}/3"}
            if entry.get("current") is True
            else entry
            for entry in _range_entries(current_page=2, selected_alias=True)
        ],
        1,
        id="arbitrary-selected-route-alias",
    ),
    ],
)
def test_hanayume_selected_marker_and_range_drift_are_rejected(entries, selected_index) -> None:
    ranges = _parse_range_links(_range_entries(), seed_id=SEED_ID)
    with pytest.raises(DiscoveryIncompleteError):
        _validate_range_navigation(
            entries,
            seed_id=SEED_ID,
            ranges=ranges,
            selected=ranges[selected_index],
            actual_page_url=ranges[selected_index].url,
        )


def _row(episode_id: str, position: int, label: str) -> HanayumeListingRow:
    return HanayumeListingRow(
        identity=HanayumeEpisodeIdentity(WORK_ID, episode_id),
        title=f"第{position}話" if position != 3 else "第4話①",
        access=classify_hanayume_access((label,)),
        global_position=position,
    )


def test_hanayume_records_keep_global_oldest_positions_and_latest_first_order() -> None:
    rows = [
        _row(SEED_ID, 1, "無料"),
        _row("9202b052ad237", 2, "無料"),
        _row("2ec9c6b024ee0", 3, "今なら無料"),
        _row("90868f4de278f", 4, "今なら無料"),
    ]

    records = _records_from_rows(
        rows_oldest_first=rows,
        work_title="Fixture Work",
        seed_episode_id=SEED_ID,
        scope=None,
    )

    assert [record.source.external_id for record in records] == [
        f"{WORK_ID}:90868f4de278f",
        f"{WORK_ID}:2ec9c6b024ee0",
        f"{WORK_ID}:9202b052ad237",
        f"{WORK_ID}:{SEED_ID}",
    ]
    assert [record.source.global_display_position for record in records] == [4, 3, 2, 1]
    assert records[1].item.order_label == "第4話①"
    assert records[0].source.access_mode == "unknown"


def test_hanayume_bounded_scope_is_inclusive_without_renumbering() -> None:
    rows = [
        _row(SEED_ID, 1, "無料"),
        _row("9202b052ad237", 2, "無料"),
        _row("2ec9c6b024ee0", 3, "今なら無料"),
        _row("90868f4de278f", 4, "今なら無料"),
    ]
    records = _records_from_rows(
        rows_oldest_first=rows,
        work_title="Fixture Work",
        seed_episode_id=SEED_ID,
        scope=None,
    )
    selected = _apply_discovery_scope(
        records,
        scope=DiscoveryScope(
            from_url=f"{BASE}/episodes/90868f4de278f",
            through_url=f"{BASE}/episodes/9202b052ad237",
        ),
        work_id=WORK_ID,
    )

    assert [record.source.url.rsplit("/", 1)[-1] for record in selected] == [
        "90868f4de278f",
        "2ec9c6b024ee0",
        "9202b052ad237",
    ]
    assert [record.source.global_display_position for record in selected] == [4, 3, 2]
    with pytest.raises(DiscoveryIncompleteError):
        _apply_discovery_scope(
            records,
            scope=DiscoveryScope(from_url=f"{BASE}/episodes/8cf6f15923caa0"),
            work_id=WORK_ID,
        )
