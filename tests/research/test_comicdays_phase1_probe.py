"""Contract tests for the bounded Comic DAYS live terminal probe."""

from __future__ import annotations

from poc.comicdays_phase1_probe import forward_control_allowed, state_signature


def _state(**control_overrides):
    control = {
        "visible": True,
        "enabled": True,
        "href": None,
        "class": "page-navigation-forward js-slide-forward",
        "text": "",
        "forbiddenLabel": False,
        **control_overrides,
    }
    return {
        "url": "https://comic-days.com/episode/123",
        "path": "/episode/123",
        "sliderNow": "3",
        "sliderLast": "20",
        "forward": {"count": 1, "items": [control]},
    }


def test_forward_guard_requires_one_safe_visible_control() -> None:
    assert forward_control_allowed(_state(), "/episode/123") == (True, "ok")
    assert forward_control_allowed(_state(visible=False), "/episode/123")[0] is False
    assert forward_control_allowed(_state(enabled=False), "/episode/123")[0] is False
    assert forward_control_allowed(_state(forbiddenLabel=True), "/episode/123")[0] is False
    assert forward_control_allowed(_state(href="https://comic-days.com/episode/456"), "/episode/123")[0] is False


def test_forward_guard_rejects_ambiguous_or_changed_target() -> None:
    state = _state()
    state["forward"]["count"] = 2
    assert forward_control_allowed(state, "/episode/123")[0] is False
    state = _state()
    state["path"] = "/episode/456"
    assert forward_control_allowed(state, "/episode/123")[0] is False


def test_state_signature_covers_viewer_scope_and_marker_children() -> None:
    state = _state()
    state["viewer"] = {"scope": "https://comic-days.com/episode/123.json"}
    state["areas"] = [{"index": 21, "children": [{"id": None, "class": "js-back-link-page", "onScreen": True}]}]
    first = state_signature(state)
    state["viewer"]["scope"] = "https://comic-days.com/episode/456.json"
    assert state_signature(state) != first
