from __future__ import annotations

import pytest

from screenshot_crawler.site_adapters.younganimal.live_access import (
    _parse_episode_payload,
    _parse_series_payload,
    _target_id_in_json,
    guarded_route_reason,
)

WORK_ID = "8246f8b8b2e6c"
EPISODE_ID = "856137d88753b"
EPISODE_URL = f"https://younganimal.com/episodes/{EPISODE_ID}"


@pytest.mark.parametrize(
    (
        "url",
        "resource_type",
        "method",
        "is_navigation",
        "is_main_frame",
        "has_rsc_header",
        "expected",
    ),
    [
        (EPISODE_URL, "document", "GET", True, True, False, None),
        (f"{EPISODE_URL}/2?_rsc=opaque", "fetch", "GET", False, False, False, None),
        (f"{EPISODE_URL}/old?_rsc=opaque", "fetch", "GET", False, False, False, None),
        (
            f"https://younganimal.com/series/{WORK_ID}/1?_rsc=opaque",
            "fetch",
            "GET",
            False,
            True,
            False,
            "same_work_rsc_prefetch",
        ),
        (
            f"https://younganimal.com/series/{WORK_ID}/1?_rsc=opaque",
            "fetch",
            "POST",
            False,
            False,
            False,
            "series_page_or_rsc_route",
        ),
        (
            "https://younganimal.com/series/0000000000001/1?_rsc=opaque",
            "fetch",
            "GET",
            False,
            False,
            False,
            "series_page_or_rsc_route",
        ),
        (
            "https://evil.example/episodes/other",
            "document",
            "GET",
            True,
            True,
            False,
            "non_target_navigation",
        ),
        (
            "https://younganimal.com/episodes/0000000000001",
            "document",
            "GET",
            True,
            True,
            False,
            "non_target_main_document",
        ),
        (
            f"https://younganimal.com/episodes/{EPISODE_ID}/new?_rsc=opaque",
            "fetch",
            "GET",
            False,
            False,
            False,
            "other_episode_page_route",
        ),
        (
            "https://younganimal.com/episodes/d19dd3fa4563f?_rsc=fixture",
            "fetch",
            "GET",
            False,
            True,
            True,
            "other_episode_rsc_prefetch",
        ),
        (
            "https://younganimal.com/episodes/d19dd3fa4563f?_rsc=fixture",
            "fetch",
            "GET",
            False,
            True,
            False,
            "other_episode_page_route",
        ),
        (
            "https://younganimal.com/episodes/d19dd3fa4563f?_rsc=fixture",
            "script",
            "GET",
            False,
            True,
            True,
            "other_episode_page_route",
        ),
        (
            "https://younganimal.com/episodes/d19dd3fa4563f?_rsc=fixture",
            "image",
            "GET",
            False,
            True,
            True,
            "other_episode_page_route",
        ),
        (
            "https://younganimal.com/episodes/d19dd3fa4563f/image.webp",
            "image",
            "GET",
            False,
            True,
            False,
            None,
        ),
        (
            "https://younganimal.com/episodes/d19dd3fa4563f",
            "fetch",
            "GET",
            False,
            True,
            True,
            "other_episode_page_route",
        ),
        (
            "https://younganimal.com/episodes/d19dd3fa4563f?_rsc=fixture",
            "fetch",
            "POST",
            False,
            True,
            True,
            "other_episode_page_route",
        ),
        (
            "https://younganimal.com/episodes/d19dd3fa4563f?_rsc=fixture",
            "fetch",
            "HEAD",
            False,
            True,
            True,
            "other_episode_page_route",
        ),
        (
            "https://younganimal.com/episodes/d19dd3fa4563f?_rsc=fixture",
            "fetch",
            "GET",
            False,
            False,
            True,
            "other_episode_page_route",
        ),
        (
            f"https://younganimal.com/series/{WORK_ID}?_rsc=opaque",
            "fetch",
            "GET",
            False,
            False,
            False,
            "same_work_rsc_prefetch",
        ),
        (
            "https://younganimal.com/unrecognized?_rsc=opaque",
            "fetch",
            "GET",
            False,
            False,
            False,
            "unknown_rsc_page_route",
        ),
        (
            "https://younganimal.com/series/0000000000001",
            "document",
            "GET",
            True,
            True,
            False,
            "non_target_main_document",
        ),
        (
            "https://younganimal.com/assets/reader.js",
            "script",
            "GET",
            False,
            False,
            False,
            None,
        ),
    ],
)
def test_younganimal_route_guard_is_target_bound(
    url: str,
    resource_type: str,
    method: str,
    is_navigation: bool,
    is_main_frame: bool,
    has_rsc_header: bool,
    expected: str | None,
) -> None:
    assert (
        guarded_route_reason(
            url=url,
            expected_episode_url=EPISODE_URL,
            expected_work_id=WORK_ID,
            resource_type=resource_type,
            method=method,
            is_navigation=is_navigation,
            is_main_frame=is_main_frame,
            has_rsc_header=has_rsc_header,
        )
        == expected
    )


def test_episode_access_parser_requires_one_exact_work_bound_record() -> None:
    payload = {
        "episode": {
            "access": {
                "episodeId": EPISODE_ID,
                "hasAccess": False,
                "accessType": "waitAndFree",
                "timeRemainingInSeconds": 0,
            },
            "series": {"id": WORK_ID},
        }
    }
    state = _parse_episode_payload(payload, episode_id=EPISODE_ID)
    assert state is not None
    assert (state.work_id, state.access_type, state.has_access) == (
        WORK_ID,
        "waitAndFree",
        False,
    )
    assert state.remaining_state == "valid"
    assert (
        _parse_episode_payload(
            {"episode": payload["episode"], "recommendation": payload["episode"]},
            episode_id=EPISODE_ID,
        )
        is None
    )
    malformed_duplicate = {
        "episode": payload["episode"],
        "recommendation": {"access": {"episodeId": EPISODE_ID, "hasAccess": "false"}},
    }
    assert _parse_episode_payload(malformed_duplicate, episode_id=EPISODE_ID) is None


def test_series_access_parser_binds_work_and_rejects_duplicate_target_rows() -> None:
    row = {
        "episodeId": EPISODE_ID,
        "hasAccess": True,
        "accessType": "waitAndFree",
        "timeRemainingInSeconds": 100,
    }
    payload = {"seriesAccess": {"seriesId": WORK_ID, "episodeAccesses": [row]}}
    parsed = _parse_series_payload(payload, episode_id=EPISODE_ID)
    assert parsed is not None
    assert parsed[0:2] == (WORK_ID, 1)
    assert parsed[2] is not None and parsed[2].has_access is True
    duplicate = {
        "seriesAccess": {
            "seriesId": WORK_ID,
            "episodeAccesses": [row, dict(row)],
        }
    }
    parsed_duplicate = _parse_series_payload(duplicate, episode_id=EPISODE_ID)
    assert parsed_duplicate == (WORK_ID, 2, None)


def test_checkout_binding_requires_a_bounded_exact_target_identifier() -> None:
    assert _target_id_in_json('{"episodeId":"' + EPISODE_ID + '"}', target_id=EPISODE_ID)
    assert _target_id_in_json(
        '{"metadata":{"episodeId":"' + EPISODE_ID + '"}}', target_id=EPISODE_ID
    )
    assert not _target_id_in_json(
        '{"episodeId":"0000000000001"}', target_id=EPISODE_ID
    )
