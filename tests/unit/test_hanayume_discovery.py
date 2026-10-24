from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from screenshot_crawler.discovery import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.hanayume import discovery as hanayume_discovery
from screenshot_crawler.site_adapters.hanayume.discovery import (
    HanayumeEpisodeIdentity,
    HanayumeListingRow,
    HanayumeNativeEpisodeAccess,
    HanayumeSeriesAccessSnapshot,
    _apply_discovery_scope,
    _apply_native_access,
    _latest_native_access_by_episode,
    _parse_range_links,
    _parse_series_access_snapshot,
    _records_from_rows,
    _rental_history_expiry,
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


def test_hanayume_discovery_range_pacing_default() -> None:
    assert hanayume_discovery.RANGE_PACING_MS == 2_500


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


def test_hanayume_native_access_requires_exact_work_and_episode_and_sets_conservative_expiry() -> None:
    requested_at = datetime(2026, 10, 17, 1, 2, 3, tzinfo=UTC)
    snapshot = _parse_series_access_snapshot(
        {
            "seriesAccess": {
                "seriesId": WORK_ID,
                "episodeAccesses": [
                    {
                        "episodeId": SEED_ID,
                        "accessType": "waitAndFree",
                        "hasAccess": True,
                        "timeRemainingInSeconds": 259200,
                    },
                    {
                        "episodeId": "9202b052ad237",
                        "accessType": "waitAndFree",
                        "hasAccess": True,
                        "timeRemainingInSeconds": 3600,
                    },
                ],
            }
        },
        requested_at=requested_at,
    )
    assert snapshot is not None
    native = _latest_native_access_by_episode([snapshot], work_id=WORK_ID)
    row = HanayumeListingRow(
        identity=HanayumeEpisodeIdentity(WORK_ID, SEED_ID),
        title="Episode",
        access=classify_hanayume_access(("購入",)),
        global_position=1,
        manual_rental_history=True,
    )

    updated = _apply_native_access([row], native_access=native, listing_authenticated=True)[0]

    assert updated.access.access_mode == "quota"
    assert updated.access_granted_until == requested_at + timedelta(seconds=259199)
    assert updated.access_granted_until_observed is True
    assert _latest_native_access_by_episode([snapshot], work_id="9000000000001") == {}


@pytest.mark.parametrize("access_type", ["waitAndFree", "paidContent"])
@pytest.mark.parametrize("conflicting_duplicate", [False, True])
def test_hanayume_native_duplicate_episode_rows_are_ambiguous_even_when_identical(
    conflicting_duplicate: bool, access_type: str,
) -> None:
    requested_at = datetime(2026, 10, 17, 1, 2, 3, tzinfo=UTC)
    coin = access_type == "paidContent"
    first = HanayumeNativeEpisodeAccess(
        SEED_ID, access_type, not coin, None if coin else 3600, requested_at,
        remaining_seconds_omitted=coin,
    )
    second = (
        HanayumeNativeEpisodeAccess(
            SEED_ID, access_type, True, None if coin else 1800, requested_at,
            remaining_seconds_omitted=coin,
        )
        if conflicting_duplicate
        else first
    )
    duplicate_snapshot = HanayumeSeriesAccessSnapshot(
        WORK_ID, (first, second)
    )

    assert _latest_native_access_by_episode(
        [duplicate_snapshot], work_id=WORK_ID
    ) == {}

    # A later clean, naturally observed response is allowed to supersede the
    # duplicate row set; the duplicate response itself cannot mint quota/grant.
    clean = HanayumeNativeEpisodeAccess(
        SEED_ID, "waitAndFree", True, 7200, requested_at + timedelta(seconds=1)
    )
    clean_snapshot = HanayumeSeriesAccessSnapshot(WORK_ID, (clean,))
    assert _latest_native_access_by_episode(
        [duplicate_snapshot, clean_snapshot], work_id=WORK_ID
    ) == {SEED_ID: clean}

    stale_grant = datetime(2026, 10, 18, tzinfo=UTC)
    row = HanayumeListingRow(
        identity=HanayumeEpisodeIdentity(WORK_ID, SEED_ID),
        title="Episode",
        access=classify_hanayume_access(("unknown",)),
        global_position=1,
        manual_rental_history=True,
        access_granted_until=stale_grant,
        access_granted_until_observed=True,
    )
    unchanged = _apply_native_access(
        [row],
        native_access=_latest_native_access_by_episode(
            [duplicate_snapshot], work_id=WORK_ID
        ),
        listing_authenticated=True,
    )[0]
    assert unchanged.access.access_mode == "unknown"
    assert unchanged.access_granted_until is None
    assert unchanged.access_granted_until_observed is False


@pytest.mark.parametrize(
    "remaining",
    [True, -1, 259201, "259200", None],
)
def test_hanayume_native_remaining_seconds_must_be_a_bounded_strict_integer(remaining) -> None:
    snapshot = _parse_series_access_snapshot(
        {
            "seriesAccess": {
                "seriesId": WORK_ID,
                "episodeAccesses": [
                    {
                        "episodeId": SEED_ID,
                        "accessType": "waitAndFree",
                        "hasAccess": True,
                        "timeRemainingInSeconds": remaining,
                    }
                ],
            }
        },
        requested_at=datetime(2026, 10, 17, tzinfo=UTC),
    )
    assert snapshot is not None
    assert snapshot.rows[0].remaining_seconds is None
    assert snapshot.rows[0].remaining_seconds_omitted is False


_OMITTED = object()


@pytest.mark.parametrize(
    ("authenticated", "has_access", "timer", "label", "expected", "cleared"),
    [
        (True, False, _OMITTED, "", "paid", True),
        (False, False, _OMITTED, "", "unknown", False),
        (True, True, _OMITTED, "", "unknown", False),
        (True, None, _OMITTED, "", "unknown", False),
        (True, "false", _OMITTED, "", "unknown", False),
        (True, False, None, "", "unknown", False),
        (True, False, 0, "", "unknown", False),
        (True, False, 3600, "", "unknown", False),
        (True, False, 1042674, "", "unknown", False),
        (True, False, "3600", "", "unknown", False),
        (True, False, True, "", "unknown", False),
        (True, False, -1, "", "unknown", False),
        (True, False, _OMITTED, "無料", "free", False),
        (True, False, _OMITTED, "今なら無料", "free", False),
    ],
)
def test_hanayume_coin_denial_requires_authenticated_access_and_omitted_timer(
    authenticated, has_access, timer, label, expected, cleared,
) -> None:
    raw = {"episodeId": SEED_ID, "accessType": "paidContent", "hasAccess": has_access}
    if timer is not _OMITTED:
        raw["timeRemainingInSeconds"] = timer
    snapshot = _parse_series_access_snapshot(
        {"seriesAccess": {"seriesId": WORK_ID, "episodeAccesses": [raw]}},
        requested_at=datetime(2026, 10, 25, tzinfo=UTC),
    )
    assert snapshot is not None
    assert snapshot.rows[0].remaining_seconds_omitted is (timer is _OMITTED)
    row = HanayumeListingRow(
        identity=HanayumeEpisodeIdentity(WORK_ID, SEED_ID), title="Episode",
        access=classify_hanayume_access((label,) if label else (), listing_authenticated=True),
        global_position=1,
    )
    native = _latest_native_access_by_episode([snapshot], work_id=WORK_ID)
    updated = _apply_native_access(
        [row], native_access=native, listing_authenticated=authenticated,
    )[0]
    assert updated.access.access_mode == expected
    assert updated.access_granted_until is None
    assert updated.access_granted_until_observed is cleared
    assert _latest_native_access_by_episode([snapshot], work_id="9000000000001") == {}


@pytest.mark.parametrize(
    ("display", "hours"),
    [
        ("12日+1時間", 288), ("2日+23時間", 70), ("7時間", 6),
        ("14日+0時間", 335), ("1時間", None), ("0時間", None),
        ("15日+1時間", None), ("12日+24時間", None),
        ("7分", None), ("7時間 extra", None), ("-1日+1時間", None),
    ],
)
def test_hanayume_premium_rental_display_uses_bounded_lower_expiry(display, hours) -> None:
    observed_at = datetime(2026, 10, 24, tzinfo=UTC)
    expiry = _rental_history_expiry(
        "レンタル中 閲覧期限 " + display, observed_at=observed_at
    )
    assert expiry == (observed_at + timedelta(hours=hours) if hours is not None else None)


@pytest.mark.parametrize(
    ("authenticated", "access_type", "has_access", "history", "public_label", "accepted"),
    [
        (True, "purchased", True, True, "", True),
        (True, "purchased", True, True, "無料", True),
        (False, "purchased", True, True, "", False),
        (True, "purchased", False, True, "", False),
        (True, "purchased", None, True, "", False),
        (True, "purchased", True, False, "", False),
        (True, "paidContent", False, True, "", False),
        (True, "other", True, True, "", False),
    ],
)
def test_hanayume_premium_rental_conflict_requires_authenticated_native_and_history(
    authenticated, access_type, has_access, history, public_label, accepted,
) -> None:
    observed_at = datetime(2026, 10, 24, tzinfo=UTC)
    expiry = observed_at + timedelta(days=12)
    row = HanayumeListingRow(
        identity=HanayumeEpisodeIdentity(WORK_ID, SEED_ID), title="Episode",
        access=classify_hanayume_access((public_label,) if public_label else ()),
        global_position=1, history_label_conflict=True,
        rental_history_until=expiry if history else None,
    )
    native = HanayumeNativeEpisodeAccess(
        SEED_ID, access_type, has_access, None, observed_at,
        remaining_seconds_omitted=access_type == "paidContent",
    )
    if not accepted:
        with pytest.raises(DiscoveryIncompleteError):
            _apply_native_access([row], native_access={SEED_ID: native}, listing_authenticated=authenticated)
        return
    updated = _apply_native_access(
        [row], native_access={SEED_ID: native}, listing_authenticated=authenticated
    )[0]
    assert updated.access.access_mode == ("free" if public_label == "無料" else "paid")
    assert updated.access_granted_until == expiry
    assert updated.access_granted_until_observed is True


def test_hanayume_native_inactive_clears_and_incomplete_or_unproven_grant_preserves() -> None:
    requested_at = datetime(2026, 10, 17, tzinfo=UTC)
    row = HanayumeListingRow(
        identity=HanayumeEpisodeIdentity(WORK_ID, SEED_ID),
        title="Episode",
        access=classify_hanayume_access(("購入",)),
        global_position=1,
    )
    inactive = HanayumeNativeEpisodeAccess(
        SEED_ID, "waitAndFree", False, 0, requested_at
    )
    cleared = _apply_native_access(
        [row],
        native_access={SEED_ID: inactive},
        listing_authenticated=True,
    )[0]
    assert cleared.access_granted_until is None
    assert cleared.access_granted_until_observed is True

    malformed = HanayumeNativeEpisodeAccess(
        SEED_ID, "waitAndFree", True, None, requested_at
    )
    preserved = _apply_native_access(
        [row],
        native_access={SEED_ID: malformed},
        listing_authenticated=True,
    )[0]
    assert preserved.access.access_mode == "quota"
    assert preserved.access_granted_until is None
    assert preserved.access_granted_until_observed is False

    unauthenticated = _apply_native_access(
        [row],
        native_access={
            SEED_ID: HanayumeNativeEpisodeAccess(
                SEED_ID, "waitAndFree", True, 3600, requested_at
            )
        },
        listing_authenticated=False,
    )[0]
    assert unauthenticated.access_granted_until_observed is False


class _FakeMonotonic:
    def __init__(self, *values: float) -> None:
        self.values = list(values)
        self.last = values[-1]

    def monotonic(self) -> float:
        if self.values:
            self.last = self.values.pop(0)
        return self.last


class _FakeAuthPage:
    def __init__(self, evaluate, *, url: str = f"{BASE}/series/{WORK_ID}") -> None:
        self.url = url
        self._evaluate = evaluate

    async def evaluate(self, *_args):
        return await self._evaluate()


@pytest.mark.asyncio
async def test_hanayume_auth_observation_timeout_at_total_deadline_returns_unknown_false(
    monkeypatch,
) -> None:
    monkeypatch.setattr(hanayume_discovery, "SERIES_AUTH_HYDRATION_TIMEOUT_SECONDS", 0.04)
    monkeypatch.setattr(hanayume_discovery, "OBSERVATION_TIMEOUT_SECONDS", 3.0)
    monkeypatch.setattr(hanayume_discovery, "time", _FakeMonotonic(10.0, 10.0, 10.05))

    async def delayed_evaluate():
        await asyncio.sleep(0.2)

    assert (
        await hanayume_discovery._read_series_authentication(
            _FakeAuthPage(delayed_evaluate), work_id=WORK_ID
        )
        is False
    )


@pytest.mark.asyncio
async def test_hanayume_auth_observation_timeout_before_total_deadline_remains_incomplete(
    monkeypatch,
) -> None:
    monkeypatch.setattr(hanayume_discovery, "SERIES_AUTH_HYDRATION_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(hanayume_discovery, "OBSERVATION_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(hanayume_discovery, "time", _FakeMonotonic(10.0, 10.0, 10.03))

    async def delayed_evaluate():
        await asyncio.sleep(0.2)

    with pytest.raises(ValueError, match="markers could not be read") as raised:
        await hanayume_discovery._read_series_authentication(
            _FakeAuthPage(delayed_evaluate), work_id=WORK_ID
        )
    assert isinstance(raised.value.__cause__, TimeoutError)


@pytest.mark.asyncio
async def test_hanayume_auth_route_drift_during_expired_observation_stays_incomplete(
    monkeypatch,
) -> None:
    monkeypatch.setattr(hanayume_discovery, "SERIES_AUTH_HYDRATION_TIMEOUT_SECONDS", 0.04)
    monkeypatch.setattr(hanayume_discovery, "OBSERVATION_TIMEOUT_SECONDS", 3.0)
    monkeypatch.setattr(hanayume_discovery, "time", _FakeMonotonic(10.0, 10.0, 10.05))
    page = _FakeAuthPage(None)

    async def drift_then_delay():
        page.url = f"{BASE}/series/{'f' * 13}"
        await asyncio.sleep(0.2)

    page._evaluate = drift_then_delay
    with pytest.raises(ValueError, match="authentication route identity changed") as raised:
        await hanayume_discovery._read_series_authentication(page, work_id=WORK_ID)
    assert isinstance(raised.value.__cause__, TimeoutError)


@pytest.mark.asyncio
async def test_hanayume_auth_observation_cancellation_propagates(monkeypatch) -> None:
    monkeypatch.setattr(hanayume_discovery, "SERIES_AUTH_HYDRATION_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(hanayume_discovery, "OBSERVATION_TIMEOUT_SECONDS", 3.0)
    monkeypatch.setattr(hanayume_discovery, "time", _FakeMonotonic(10.0, 10.0))

    async def cancel_evaluate():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await hanayume_discovery._read_series_authentication(
            _FakeAuthPage(cancel_evaluate), work_id=WORK_ID
        )
