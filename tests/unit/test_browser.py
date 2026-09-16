import pytest

from screenshot_crawler.core.browser import (
    DEFAULT_CDP_ENDPOINT,
    BrowserSession,
    close_browser,
    resolve_cdp_endpoint,
)


@pytest.mark.parametrize("site", ["bookwalker", "mangaone"])
def test_cli_endpoint_has_priority_for_all_real_sites(
    monkeypatch: pytest.MonkeyPatch,
    site: str,
) -> None:
    monkeypatch.delenv(f"{site.upper()}_CDP_ENDPOINT", raising=False)
    monkeypatch.setenv("CRAWLER_CDP_ENDPOINT", "http://global.test:9222")

    assert resolve_cdp_endpoint(
        site=site,
        cli_endpoint="http://cli.test:9222",
        values={f"{site.upper()}_CDP_ENDPOINT": "http://site.test:9222"},
    ) == "http://cli.test:9222"


@pytest.mark.parametrize("site", ["bookwalker", "mangaone"])
def test_site_endpoint_has_priority_over_global_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    site: str,
) -> None:
    monkeypatch.delenv(f"{site.upper()}_CDP_ENDPOINT", raising=False)
    monkeypatch.delenv("CRAWLER_CDP_ENDPOINT", raising=False)

    assert resolve_cdp_endpoint(
        site=site,
        values={
            f"{site.upper()}_CDP_ENDPOINT": "http://site.test:9222",
            "CRAWLER_CDP_ENDPOINT": "http://global.test:9222",
        },
    ) == "http://site.test:9222"


def test_global_endpoint_is_used_without_site_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CRAWLER_CDP_ENDPOINT", raising=False)

    assert resolve_cdp_endpoint(
        site="mangaone",
        values={"CRAWLER_CDP_ENDPOINT": "http://global.test:9222"},
    ) == "http://global.test:9222"


def test_default_endpoint_is_used_without_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CRAWLER_CDP_ENDPOINT", raising=False)

    assert resolve_cdp_endpoint(site="bookwalker", values={}) == DEFAULT_CDP_ENDPOINT


class FakeRemoteBrowser:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class FakePlaywright:
    def __init__(self) -> None:
        self.stop_calls = 0

    async def stop(self) -> None:
        self.stop_calls += 1


async def test_remote_browser_is_not_closed_when_session_disconnects() -> None:
    browser = FakeRemoteBrowser()
    playwright = FakePlaywright()

    await close_browser(playwright, browser, close_browser_instance=False)

    assert browser.close_calls == 0
    assert playwright.stop_calls == 1


async def test_browser_session_disconnect_leaves_remote_browser_running() -> None:
    browser = FakeRemoteBrowser()
    playwright = FakePlaywright()
    session = BrowserSession(playwright, browser, object())  # type: ignore[arg-type]

    await session.close()

    assert browser.close_calls == 0
    assert playwright.stop_calls == 1
