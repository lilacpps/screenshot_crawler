from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.site_adapters.kadocomi.adapter import KadocomiAdapter, _inventory_summary

WORK_URL = "https://comic-walker.com/detail/KC_004915_S"
EPISODE_URL = f"{WORK_URL}/episodes/KC_0049150000400011_E"
FOREIGN_EPISODE_URL = f"{WORK_URL}/episodes/KC_0049150000400012_E"


def test_inventory_summary_is_bounded_and_omits_native_source_data() -> None:
    summary = _inventory_summary({
        "slideRows": [{"contentSlots": ["a", "b"], "contentCanvases": [
            {"last": {"sourceUrl": "blob:private"}}
        ]}] * 40,
        "prMarkers": [{"dataN": "private", "slideIndex": "private"}] * 12,
        "mainEndMarkers": [{"dataN": "2", "slideIndex": 38}],
        "secondaryEndMarkers": [{"dataN": None, "slideIndex": 39}],
    })
    assert summary == {
        "slides": 40, "content_counts": [2] * 32, "pr": [["?", None]] * 8,
        "main_end": [["2", 38]], "secondary_end": [[None, 39]],
    }
    assert "private" not in json.dumps(summary)


@pytest.mark.parametrize(
    ("responses", "page_url", "accepted"),
    [
        pytest.param([(EPISODE_URL, 302)], EPISODE_URL, False, id="same-url-302-only"),
        pytest.param(
            [(EPISODE_URL, 302), (FOREIGN_EPISODE_URL, 200)],
            FOREIGN_EPISODE_URL,
            False,
            id="302-to-foreign-200",
        ),
        pytest.param(
            [(EPISODE_URL, 200), (FOREIGN_EPISODE_URL, 200)],
            FOREIGN_EPISODE_URL,
            False,
            id="200-to-foreign-200",
        ),
        pytest.param([(EPISODE_URL, 200)], EPISODE_URL, True, id="exact-200"),
    ],
)
async def test_initial_document_response_validation_is_identity_bound(
    responses: list[tuple[str, int]], page_url: str, accepted: bool
) -> None:
    adapter = KadocomiAdapter()
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    adapter._main_document_responses = responses
    page = SimpleNamespace(url=page_url)

    if accepted:
        await adapter._validate_initial_navigation_response(page)  # type: ignore[arg-type]
    else:
        with pytest.raises(UnknownPageStateError):
            await adapter._validate_initial_navigation_response(page)  # type: ignore[arg-type]
