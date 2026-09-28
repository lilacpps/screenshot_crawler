from __future__ import annotations

import pytest
from playwright.async_api import Page

from screenshot_crawler.core.access_guard import AccessEvent, AccessGuard
from screenshot_crawler.core.errors import AccessStopError

pytestmark = pytest.mark.asyncio(loop_scope="module")


def _guard(
    events: list[AccessEvent],
    *,
    stop_on_http_403: bool = True,
    stop_on_http_429: bool = True,
    stop_on_challenge: bool = True,
    stop_on_captcha: bool = True,
) -> AccessGuard:
    return AccessGuard(
        site="test",
        relevant_host=lambda url: "first-party.test" in url,
        stop_on_http_403=stop_on_http_403,
        stop_on_http_429=stop_on_http_429,
        stop_on_challenge=stop_on_challenge,
        stop_on_captcha=stop_on_captcha,
        event_sink=events.append,
    )


async def test_visible_captcha_providers_stop_but_hidden_provider_does_not(
    browser_page: Page,
) -> None:
    page = browser_page
    for html, provider in (
        (
            '<div class="g-recaptcha" style="display:block;width:300px;height:80px"></div>',
            "recaptcha",
        ),
        (
            '<div class="h-captcha" style="display:block;width:300px;height:80px"></div>',
            "hcaptcha",
        ),
        (
            '<div class="cf-turnstile" style="display:block;width:300px;height:80px"></div>',
            "turnstile",
        ),
    ):
        await page.set_content(html)
        events: list[AccessEvent] = []
        guard = _guard(events)
        with pytest.raises(AccessStopError) as exc_info:
            await guard.check_page(page)
        assert exc_info.value.reason == "captcha_detected"
        assert exc_info.value.provider == provider

    await page.set_content(
        '<iframe src="https://www.google.com/recaptcha/api2/anchor" '
        'style="display:none"></iframe><script src="/recaptcha.js"></script>'
    )
    guard = _guard([])
    await guard.check_page(page)
    guard.raise_if_stopped()
