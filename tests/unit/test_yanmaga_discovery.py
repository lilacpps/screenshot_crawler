from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.discovery import DiscoverySourceSnapshot
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.yanmaga import (
    YanmagaDiscoveryAdapter,
    YanmagaEpisodeParts,
    YanmagaWorkParts,
    classify_yanmaga_first_free_marker,
    classify_yanmaga_free_marker,
    classify_yanmaga_wait_marker,
    has_yanmaga_anonymous_proof,
    has_yanmaga_authenticated_proof,
    parse_yanmaga_episode_url,
    parse_yanmaga_work_url,
)
from screenshot_crawler.site_adapters.yanmaga import discovery as yanmaga_discovery
from screenshot_crawler.site_adapters.yanmaga.rental_history import (
    RentalCountdown,
    RentalHistoryObservation,
)
from screenshot_crawler.watchlist import WatchlistTarget

BASE = "https://yanmaga.jp"
WORK_URL = f"{BASE}/comics/%E3%83%86%E3%82%B9%E3%83%88%E4%BD%9C"
SLUG = "テスト作"
EPISODE_ID = "0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize("limit,expected", [(None, 150), ("1", 1), ("38", 38), ("150", 150)])
def test_yanmaga_continuation_accepts_native_default_and_explicit_limit(limit, expected):
    continuation = YanmagaDiscoveryAdapter._parse_continuation(
        {"limit": limit, "offset": "5", "sort": "older", "text": "もっと見る",
         "path": f"/comics/{SLUG}/episodes"}, YanmagaWorkParts(SLUG))
    assert continuation.limit == expected and continuation.offset == 5


@pytest.mark.parametrize("change", [
    {"limit": ""}, {"limit": "None"}, {"limit": "0"}, {"limit": "151"},
    {"limit": "-1"}, {"limit": "1.5"}, {"limit": "0150"},
    {"offset": None}, {"offset": "-1"}, {"offset": "05"},
    {"sort": None}, {"sort": "newer"}, {"path": "/comics/foreign/episodes"},
])
def test_yanmaga_continuation_default_does_not_rescue_malformed_fields(change):
    raw = {"limit": None, "offset": "5", "sort": "older", "text": "もっと見る",
           "path": f"/comics/{SLUG}/episodes"}
    with pytest.raises(DiscoveryIncompleteError):
        YanmagaDiscoveryAdapter._parse_continuation(raw | change, YanmagaWorkParts(SLUG))


def test_yanmaga_discovery_adapter_is_registered() -> None:
    adapter = _discovery_registry().create("yanmaga")

    assert isinstance(adapter, YanmagaDiscoveryAdapter)
    assert adapter.supports_bounded_discovery is False
    assert adapter.allow_inferred_display_positions is False


def test_yanmaga_work_and_episode_urls_keep_encoded_work_identity() -> None:
    assert parse_yanmaga_work_url(WORK_URL) == YanmagaWorkParts(SLUG)
    assert parse_yanmaga_work_url(f"{BASE}/comics/{SLUG}") == YanmagaWorkParts(SLUG)
    assert parse_yanmaga_episode_url(
        f"{BASE}/comics/%E3%83%86%E3%82%B9%E3%83%88%E4%BD%9C/{EPISODE_ID}"
    ) == YanmagaEpisodeParts(SLUG, EPISODE_ID)

    for url in (
        f"http://yanmaga.jp/comics/{SLUG}",
        f"https://www.yanmaga.jp/comics/{SLUG}",
        f"https://yanmaga.jp.evil.example/comics/{SLUG}",
        f"https://user@yanmaga.jp/comics/{SLUG}",
        f"https://yanmaga.jp/comics/{SLUG}?page=2",
        f"https://yanmaga.jp/comics/{SLUG}#episodes",
        "https://yanmaga.jp/comics/%2Fother",
        "https://yanmaga.jp/comics/%ZZ",
        f"{BASE}/comics/{SLUG}/",
    ):
        assert parse_yanmaga_work_url(url) is None

    for url in (
        f"http://yanmaga.jp/comics/{SLUG}/{EPISODE_ID}",
        f"https://yanmaga.jp/comics/other/{EPISODE_ID}?x=1",
        f"https://yanmaga.jp/comics/{SLUG}/not-an-id",
        f"https://yanmaga.jp/comics/{SLUG}/{EPISODE_ID.upper()}",
        f"https://yanmaga.jp/viewer/comics/{SLUG}/{EPISODE_ID}",
    ):
        assert parse_yanmaga_episode_url(url) is None


def test_yanmaga_sorted_work_url_is_internal_only_and_exact() -> None:
    expected = YanmagaWorkParts(SLUG)
    sorted_url = f"{WORK_URL}?sort=older"

    assert yanmaga_discovery._parse_yanmaga_sorted_work_url(sorted_url, expected)
    assert parse_yanmaga_work_url(sorted_url) is None
    for url in (
        f"{WORK_URL}?sort=newer",
        f"{WORK_URL}?sort=older&extra=1",
        f"{BASE}/comics/other-work?sort=older",
        f"https://user@yanmaga.jp/comics/{WORK_URL.split('/comics/', 1)[1]}?sort=older",
        f"{WORK_URL}?%73ort=older",
        f"{WORK_URL}?sort=older#episodes",
    ):
        assert not yanmaga_discovery._parse_yanmaga_sorted_work_url(url, expected)


def test_yanmaga_recovery_preserves_only_same_scope_source_with_fresh_proofs() -> None:
    target = WatchlistTarget(
        key="yanmaga-test",
        work_key="yanmaga:test-work",
        site="yanmaga",
        url=WORK_URL,
        label="test work",
    )
    external_id = f"{SLUG}:{EPISODE_ID}"
    until = datetime.now(UTC) + timedelta(hours=2)
    trusted = DiscoverySourceSnapshot(
        external_id=external_id,
        discovery_key=target.key,
        access_mode="paid",
        available=True,
        access_granted_until=until,
    )
    adapter = YanmagaDiscoveryAdapter()
    adapter.configure_source_snapshots(
        target,
        (
            trusted,
            DiscoverySourceSnapshot(
                external_id=f"{SLUG}:{'1' * 32}",
                discovery_key="other-key",
                access_mode="paid",
                available=True,
                access_granted_until=until,
            ),
            DiscoverySourceSnapshot(
                external_id=f"other-work:{'2' * 32}",
                discovery_key=target.key,
                access_mode="quota",
                available=True,
                access_granted_until=until,
            ),
            DiscoverySourceSnapshot(
                external_id=f"{SLUG}:{'3' * 32}",
                discovery_key=target.key,
                access_mode="unknown",
                available=True,
                access_granted_until=until,
            ),
            DiscoverySourceSnapshot(
                external_id=f"{SLUG}:{'4' * 32}",
                discovery_key=target.key,
                access_mode="owned",
                available=True,
                access_granted_until=until,
            ),
            DiscoverySourceSnapshot(
                external_id=f"{SLUG}:{'5' * 32}",
                discovery_key=target.key,
                access_mode="free",
                available=True,
                access_granted_until=datetime.now(UTC) - timedelta(seconds=1),
            ),
            DiscoverySourceSnapshot(
                external_id=f"{SLUG}:{'6' * 32}",
                discovery_key=target.key,
                access_mode="free",
                available=True,
                access_granted_until=datetime(2099, 1, 1),  # noqa: DTZ001 - naive expiry must be rejected
            ),
        ),
    )

    assert tuple(adapter._grant_candidates) == (external_id,)
    assert adapter.reconcile_access_mode("unknown", trusted, target) == "unknown"
    adapter._fresh_active_grants.add(external_id)
    assert adapter.reconcile_access_mode("unknown", trusted, target) == "paid"
    assert adapter.reconcile_access_mode("free", trusted, target) == "free"

    expired_during_run = DiscoverySourceSnapshot(
        external_id=external_id,
        discovery_key=target.key,
        access_mode="paid",
        available=True,
        access_granted_until=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert adapter.reconcile_access_mode("unknown", expired_during_run, target) == "unknown"

    adapter.configure_source_snapshots(target, ())
    assert adapter._grant_candidates == {}
    assert adapter._fresh_active_grants == set()
    assert adapter.reconcile_access_mode("unknown", trusted, target) == "unknown"


def test_yanmaga_imports_only_fresh_finite_history_for_unknown_rows() -> None:
    target = WatchlistTarget(
        key="yanmaga-test",
        work_key="yanmaga:test-work",
        site="yanmaga",
        url=WORK_URL,
        label="test work",
    )
    work = YanmagaWorkParts(SLUG)
    now = datetime.now(UTC)
    expiry = now + timedelta(days=1)
    def external_id(number: int) -> str:
        return f"{SLUG}:{number:032x}"

    unknown_existing = external_id(2)
    expired_known = external_id(3)
    trusted = external_id(4)
    owned = external_id(5)
    adapter = YanmagaDiscoveryAdapter()
    adapter.configure_source_snapshots(
        target,
        (
            DiscoverySourceSnapshot(
                external_id=unknown_existing,
                discovery_key=target.key,
                access_mode="unknown",
                available=True,
            ),
            DiscoverySourceSnapshot(
                external_id=expired_known,
                discovery_key=target.key,
                access_mode="paid",
                available=True,
                access_granted_until=now - timedelta(seconds=1),
            ),
            DiscoverySourceSnapshot(
                external_id=trusted,
                discovery_key=target.key,
                access_mode="free",
                available=True,
                access_granted_until=expiry,
            ),
            DiscoverySourceSnapshot(
                external_id=owned,
                discovery_key=target.key,
                access_mode="owned",
                available=True,
            ),
        ),
    )

    def row(
        number: int, *, free: bool = False, first: bool = False,
        wait: bool = False, paid: bool = False, unpublished: bool = False,
    ):
        episode_id = f"{number:032x}"
        return yanmaga_discovery.YanmagaListingRow(
            episode_id=episode_id,
            title=f"episode {number}",
            url=f"{WORK_URL}/{episode_id}",
            free_marker=free,
            red_marker_present=free,
            known_restricted=False,
            first_free_marker=first,
            wait_free_marker=wait,
            paid_marker=paid,
            unpublished=unpublished,
        )

    snapshot = yanmaga_discovery.YanmagaListingSnapshot(
        title="test work",
        anonymous=False,
        rows=(
            row(1, paid=True),
            row(2),
            row(3),
            row(4),
            row(5),
            row(6),
            row(7, paid=True),
            row(8, wait=True),
            row(9, free=True),
            row(10, first=True),
            row(11, unpublished=True),
        ),
        continuation=None,
        authenticated=True,
        mypage_href=f"{BASE}/mypage",
    )
    targets = adapter._history_targets(snapshot, work, adapter._grant_candidates)
    assert [target.episode_id for target in targets] == [
        f"{number:032x}" for number in (1, 2, 3, 4, 5, 6, 7)
    ]
    assert all(value.episode_id != f'{11:032x}' for value in adapter._history_targets(
        snapshot, work, {external_id(11): object()}))

    def countdown(hours: int, until: datetime | None, evidence: str | None):
        return RentalCountdown(
            observed_at=now,
            remaining_hours=hours,
            access_granted_until=until,
            expiry_evidence=evidence,
        )

    adapter._apply_history_countdowns(
        snapshot,
        work,
        (
            (external_id(1), countdown(14, expiry, "site_countdown_lower_bound")),
            (unknown_existing, countdown(7, expiry, "site_countdown_lower_bound")),
            (expired_known, countdown(2, expiry, "site_countdown_lower_bound")),
            (trusted, countdown(14, now + timedelta(days=2), "site_countdown_lower_bound")),
            (owned, countdown(14, expiry, "site_countdown_lower_bound")),
            (external_id(6), countdown(1, None, None)),
        ),
    )
    records = {
        record.source.external_id: record.source
        for record in adapter._records_from_snapshot(
            snapshot, target, work, adapter._fresh_history_grants
        )
    }
    assert records[external_id(1)].access_mode == "quota"
    assert records[external_id(1)].access_granted_until == expiry
    assert records[external_id(1)].access_granted_until_observed is True
    assert records[unknown_existing].access_mode == "quota"
    assert records[expired_known].access_mode == "quota"
    assert records[owned].access_mode == "unknown"
    assert records[external_id(6)].access_mode == "unknown"
    assert records[external_id(6)].access_granted_until is None
    assert records[external_id(7)].access_mode == "paid"
    assert records[external_id(8)].access_mode == "quota"
    assert records[external_id(8)].access_granted_until is None
    assert records[external_id(9)].access_mode == "free"
    assert records[external_id(10)].access_mode == "free"
    assert external_id(11) not in records
    assert records[trusted].access_mode == "unknown"
    assert records[trusted].access_granted_until is None
    assert records[trusted].access_granted_until_observed is False
    assert adapter.reconcile_access_mode("unknown", adapter._source_snapshots[trusted], target) == "free"
    assert trusted in adapter._fresh_active_grants

    adapter._fresh_history_grants.clear()
    duplicate = (external_id(1), countdown(14, expiry, "site_countdown_lower_bound"))
    adapter._apply_history_countdowns(snapshot, work, (duplicate, duplicate))
    assert adapter._fresh_history_grants == {}


@pytest.mark.parametrize("previous_mode", ["quota", "paid", "unknown"])
@pytest.mark.parametrize("history", ["inactive", "unknown", "duplicate"])
def test_yanmaga_inactive_history_clears_grant_but_only_restores_known_quota(
    previous_mode, history
) -> None:
    target = WatchlistTarget("test", "work", "yanmaga", WORK_URL, "test")
    work = YanmagaWorkParts(SLUG)
    external_id = f"{SLUG}:{EPISODE_ID}"
    previous = DiscoverySourceSnapshot(
        external_id, target.key, previous_mode, True,
        datetime.now(UTC) + timedelta(hours=2),
    )
    row = yanmaga_discovery.YanmagaListingRow(
        EPISODE_ID, "test", f"{WORK_URL}/{EPISODE_ID}", False, False, False,
    )
    snapshot = yanmaga_discovery.YanmagaListingSnapshot(
        "test", False, (row,), None, authenticated=True, mypage_href=f"{BASE}/mypage",
    )
    adapter = YanmagaDiscoveryAdapter()
    adapter.configure_source_snapshots(target, (previous,))
    observation = RentalHistoryObservation(external_id, None)
    observations = None if history == "unknown" else (
        (observation, observation) if history == "duplicate" else (observation,)
    )
    adapter._apply_history_observations(snapshot, work, observations)
    record = adapter._records_from_snapshot(
        snapshot, target, work, adapter._fresh_history_grants, adapter._fresh_inactive_grants,
    )[0].source
    expected = "quota" if previous_mode == "quota" and history == "inactive" else "unknown"
    assert adapter.reconcile_access_mode(record.access_mode, previous, target) == expected
    assert record.access_granted_until is None
    assert record.access_granted_until_observed is (history == "inactive")


@pytest.mark.parametrize(
    ("sign_ins", "sign_outs", "states", "current_document", "overflow", "expected"),
    [
        (1, 0, ("false",), True, False, True),
        (0, 0, ("false",), True, False, False),
        (1, 0, (), True, False, False),
        (1, 0, ("undefined",), True, False, False),
        (1, 0, ("false", "true"), True, False, False),
        (1, 0, ("false",), False, False, False),
        (1, 0, ("false",), True, True, False),
        (1, 1, ("false",), True, False, False),
    ],
)
def test_yanmaga_anonymous_state_requires_explicit_nonconflicting_proof(
    sign_ins, sign_outs, states, current_document, overflow, expected
) -> None:
    assert has_yanmaga_anonymous_proof(
        visible_sign_in_links=sign_ins,
        visible_sign_out_links=sign_outs,
        login_states=states,
        current_work_document=current_document,
        telemetry_overflow=overflow,
    ) is expected

    if sign_ins == 1 and states == ("false",):
        assert not has_yanmaga_anonymous_proof(
            visible_sign_in_links=sign_ins,
            visible_sign_out_links=sign_outs,
            login_states=states,
            current_work_document=current_document,
            telemetry_overflow=overflow,
            visible_mypage_links=1,
        )


@pytest.mark.parametrize(
    (
        "sign_ins",
        "mypage_links",
        "states",
        "current_document",
        "overflow",
        "expected",
    ),
    [
        (0, 1, ("true",), True, False, True),
        (0, 1, (), True, False, True),
        (0, 1, ("false",), True, False, False),
        (1, 1, ("true",), True, False, False),
        (0, 0, ("true",), True, False, False),
        (0, 1, ("true",), False, False, False),
        (0, 1, ("true",), True, True, False),
    ],
)
def test_yanmaga_authenticated_state_requires_positive_ui_and_consistent_evidence(
    sign_ins, mypage_links, states, current_document, overflow, expected
) -> None:
    assert has_yanmaga_authenticated_proof(
        visible_sign_in_links=sign_ins,
        visible_mypage_links=mypage_links,
        login_states=states,
        current_work_document=current_document,
        telemetry_overflow=overflow,
    ) is expected


def test_yanmaga_observer_rejects_stale_main_frame_telemetry_after_navigation() -> None:
    class FakePage:
        def __init__(self) -> None:
            self.main_frame = SimpleNamespace(url=WORK_URL)
            self.url = WORK_URL
            self.handlers: dict[str, list[object]] = {}

        def on(self, event: str, listener: object) -> None:
            self.handlers.setdefault(event, []).append(listener)

        def remove_listener(self, event: str, listener: object) -> None:
            self.handlers[event].remove(listener)

    page = FakePage()
    observer = yanmaga_discovery._LoginTelemetryObserver(YanmagaWorkParts(SLUG))
    observer.attach(page)
    observer.current_work_document = True
    page.url = f"{BASE}/comics/other-work"
    observer._on_request(
        SimpleNamespace(
            url="https://www.google-analytics.com/g/collect?ep.is_logged_in=false",
            frame=page.main_frame,
        )
    )
    observer._on_frame_navigated(page.main_frame)

    assert observer.states == []
    assert observer.current_work_document is False
    observer.detach()
    assert page.handlers == {"request": [], "framenavigated": []}


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (
            {
                "marker_count": 1,
                "marker_visible": True,
                "marker_text": "無料",
                "marker_class": "mod-episode-point--free",
                "marker_color": "rgb(220, 0, 0)",
                "wait_marker": False,
                "modal_marker": False,
                "anonymous": True,
            },
            "free",
        ),
        (
            {
                "marker_count": 1,
                "marker_visible": True,
                "marker_text": "無料",
                "marker_class": "mod-episode-point--free",
                "marker_color": "rgb(220, 0, 0)",
                "wait_marker": False,
                "modal_marker": False,
                "anonymous": False,
                "authenticated": True,
            },
            "free",
        ),
        (
            {
                "marker_count": 1,
                "marker_visible": True,
                "marker_text": "無料",
                "marker_class": "mod-episode-point--free by_wait",
                "marker_color": "rgb(238, 117, 27)",
                "wait_marker": True,
                "modal_marker": True,
                "anonymous": True,
            },
            "unknown",
        ),
        (
            {
                "marker_count": 1,
                "marker_visible": True,
                "marker_text": "\u7121\u6599",
                "marker_class": "mod-episode-point--free",
                "marker_color": "rgb(220, 0, 0)",
                "wait_marker": False,
                "modal_marker": False,
                "anonymous": True,
                "restricted_marker": True,
            },
            "unknown",
        ),
        (
            {
                "marker_count": 1,
                "marker_visible": True,
                "marker_text": "無料",
                "marker_class": "mod-episode-point--free",
                "marker_color": "rgb(220, 0, 0)",
                "wait_marker": False,
                "modal_marker": False,
                "anonymous": False,
            },
            "unknown",
        ),
        (
            {
                "marker_count": 2,
                "marker_visible": False,
                "marker_text": None,
                "marker_class": None,
                "marker_color": None,
                "wait_marker": False,
                "modal_marker": False,
                "anonymous": True,
            },
            "unknown",
        ),
        (
            {
                "marker_count": 1,
                "marker_visible": True,
                "marker_text": "初回無料",
                "marker_class": "mod-episode-point--free",
                "marker_color": "rgb(220, 0, 0)",
                "wait_marker": False,
                "modal_marker": False,
                "anonymous": True,
            },
            "unknown",
        ),
    ],
)
def test_yanmaga_free_classification_requires_complete_red_row_proof(evidence, expected) -> None:
    assert classify_yanmaga_free_marker(**evidence) == expected


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (
            {
                "marker_count": 1,
                "first_free_count": 1,
                "marker_visible": True,
                "marker_text": "初回無料",
                "marker_classes": ("mod-episode-point--free", "by_first_time"),
                "wait_marker": False,
                "modal_marker": False,
                "authenticated": True,
            },
            "free",
        ),
        (
            {
                "marker_count": 1,
                "first_free_count": 1,
                "marker_visible": True,
                "marker_text": "初回無料",
                "marker_classes": ("mod-episode-point--free", "by_first_time"),
                "wait_marker": False,
                "modal_marker": False,
                "authenticated": False,
            },
            "unknown",
        ),
        (
            {
                "marker_count": 1,
                "first_free_count": 1,
                "marker_visible": True,
                "marker_text": "初回無料",
                "marker_classes": ("mod-episode-point--free", "by_first_time"),
                "wait_marker": True,
                "modal_marker": False,
                "authenticated": True,
            },
            "unknown",
        ),
        (
            {
                "marker_count": 1,
                "first_free_count": 1,
                "marker_visible": True,
                "marker_text": "初回無料",
                "marker_classes": ("mod-episode-point--free", "by_first_time"),
                "wait_marker": False,
                "modal_marker": False,
                "authenticated": True,
                "conflicting_free_badge": True,
            },
            "unknown",
        ),
    ],
)
def test_yanmaga_first_free_requires_exact_authenticated_row_proof(evidence, expected) -> None:
    assert classify_yanmaga_first_free_marker(**evidence) == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "quota"),
        ({"authenticated": False}, "unknown"),
        ({"image_url": f"{BASE}/assets/logo_free_browse-96b8e1d8.svg?x=1"}, "unknown"),
        ({"original_url": f"{BASE}/comics/{SLUG}/ffffffffffffffffffffffffffffffff"}, "unknown"),
        ({"data_is_free": "false"}, "unknown"),
        ({"marker_count": 2}, "unknown"),
        ({"free_marker_count": 1}, "unknown"),
        ({"marker_classes": ("mod-episode-free_browse", "other")}, "unknown"),
        ({"first_free_count": 1}, "unknown"),
    ],
)
def test_yanmaga_wait_marker_requires_exact_authenticated_row_proof(
    overrides: dict[str, object], expected: str
) -> None:
    evidence: dict[str, object] = {
        "marker_count": 1,
        "free_marker_count": 0,
        "marker_visible": True,
        "marker_classes": ("mod-episode-free_browse",),
        "marker_text": "",
        "image_count": 1,
        "image_visible": True,
        "image_url": f"{BASE}/assets/logo_free_browse-96b8e1d8.svg",
        "data_is_free": "true",
        "anchor_url": f"{BASE}/comics/{SLUG}/{EPISODE_ID}",
        "original_url": f"{BASE}/comics/{SLUG}/{EPISODE_ID}",
        "authenticated": True,
        "modal_marker": False,
        "restricted_marker": False,
        "red_marker_present": False,
        "first_free_count": 0,
    }
    evidence.update(overrides)

    assert classify_yanmaga_wait_marker(**evidence) == expected  # type: ignore[arg-type]
