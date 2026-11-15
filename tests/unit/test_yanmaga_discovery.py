from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.discovery import DiscoverySourceSnapshot
from screenshot_crawler.site_adapters.yanmaga import (
    YanmagaDiscoveryAdapter,
    YanmagaEpisodeParts,
    YanmagaWorkParts,
    classify_yanmaga_first_free_marker,
    classify_yanmaga_free_marker,
    has_yanmaga_anonymous_proof,
    has_yanmaga_authenticated_proof,
    parse_yanmaga_episode_url,
    parse_yanmaga_work_url,
)
from screenshot_crawler.site_adapters.yanmaga import discovery as yanmaga_discovery
from screenshot_crawler.watchlist import WatchlistTarget

BASE = "https://yanmaga.jp"
WORK_URL = f"{BASE}/comics/%E3%83%86%E3%82%B9%E3%83%88%E4%BD%9C"
SLUG = "テスト作"
EPISODE_ID = "0123456789abcdef0123456789abcdef"


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
