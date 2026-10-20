from __future__ import annotations

from types import SimpleNamespace

import pytest

from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.site_adapters.yanmaga import (
    YanmagaDiscoveryAdapter,
    YanmagaEpisodeParts,
    YanmagaWorkParts,
    classify_yanmaga_free_marker,
    has_yanmaga_anonymous_proof,
    parse_yanmaga_episode_url,
    parse_yanmaga_work_url,
)
from screenshot_crawler.site_adapters.yanmaga import discovery as yanmaga_discovery

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
