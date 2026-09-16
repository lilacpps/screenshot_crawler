from pathlib import Path

import pytest

from screenshot_crawler.auth.storage import (
    AuthenticationStateNotFoundError,
    auth_state_path,
    require_auth_state,
)
from screenshot_crawler.core.browser import create_browser_context, default_browser_context


def test_auth_state_path_is_scoped_to_auth_directory(tmp_path: Path) -> None:
    assert auth_state_path("bookwalker", auth_dir=tmp_path) == tmp_path / "bookwalker.json"


@pytest.mark.parametrize("site", ["", ".", "..", "nested/site", "nested\\site"])
def test_auth_state_path_rejects_unsafe_site_names(tmp_path: Path, site: str) -> None:
    with pytest.raises(ValueError):
        auth_state_path(site, auth_dir=tmp_path)


def test_require_auth_state_has_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(AuthenticationStateNotFoundError, match="Run save_auth first"):
        require_auth_state("bookwalker", auth_dir=tmp_path)


class FakeBrowser:
    def __init__(self) -> None:
        self.options: dict[str, object] | None = None

    async def new_context(self, **options: object) -> object:
        self.options = options
        return object()


async def test_create_browser_context_reuses_saved_state(tmp_path: Path) -> None:
    state = tmp_path / "bookwalker.json"
    state.write_text("{}", encoding="utf-8")
    browser = FakeBrowser()

    await create_browser_context(browser, auth_state=state)

    assert browser.options == {
        "viewport": {"width": 1920, "height": 1080},
        "device_scale_factor": 1.0,
        "storage_state": str(state),
    }


async def test_create_browser_context_requires_state_for_authenticated_site(
    tmp_path: Path,
) -> None:
    browser = FakeBrowser()

    with pytest.raises(AuthenticationStateNotFoundError, match="Authentication state not found"):
        await create_browser_context(
            browser,
            site="bookwalker",
            auth_required=True,
            auth_dir=tmp_path,
        )


async def test_create_browser_context_can_follow_native_headed_viewport() -> None:
    browser = FakeBrowser()

    await create_browser_context(browser, no_viewport=True)

    assert browser.options == {"no_viewport": True}


class FakeConnectedBrowser:
    def __init__(self, contexts: list[object]) -> None:
        self.contexts = contexts


def test_default_browser_context_uses_existing_context() -> None:
    context = object()
    assert default_browser_context(FakeConnectedBrowser([context])) is context


def test_default_browser_context_rejects_missing_context() -> None:
    with pytest.raises(RuntimeError, match="no browser context"):
        default_browser_context(FakeConnectedBrowser([]))
