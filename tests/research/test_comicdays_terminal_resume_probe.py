"""Pure safety tests for the bounded Comic DAYS terminal probe."""

from __future__ import annotations

import pytest

from poc.comicdays_terminal_resume_probe import TARGET_PATH, click_validated


class FakeLocator:
    def __init__(self, count: int = 1) -> None:
        self.count_value = count
        self.clicks = 0

    async def count(self) -> int:
        return self.count_value

    async def is_visible(self, *, timeout: int) -> bool:
        del timeout
        return True

    async def click(self, **kwargs) -> None:
        del kwargs
        self.clicks += 1

    async def evaluate(self, expression: str) -> None:
        del expression
        self.clicks += 1


class FakePage:
    def __init__(self, locator: FakeLocator, url: str = f"https://comic-days.com{TARGET_PATH}") -> None:
        self.url = url
        self._locator = locator

    def locator(self, selector: str) -> FakeLocator:
        del selector
        return self._locator


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("free_membership", "url", "count", "control"),
    [
        (False, f"https://comic-days.com{TARGET_PATH}", 1, {"visible": True, "href_is_episode": False, "forbidden_label": False}),
        (True, "https://comic-days.com/episode/other", 1, {"visible": True, "href_is_episode": False, "forbidden_label": False}),
        (True, f"https://comic-days.com{TARGET_PATH}", 2, {"visible": True, "href_is_episode": False, "forbidden_label": False}),
        (True, f"https://comic-days.com{TARGET_PATH}", 1, {"visible": True, "href_is_episode": True, "forbidden_label": False}),
        (True, f"https://comic-days.com{TARGET_PATH}", 1, {"visible": True, "href_is_episode": False, "forbidden_label": True}),
        (True, f"https://comic-days.com{TARGET_PATH}", 1, {"visible": False, "href_is_episode": False, "forbidden_label": False}),
    ],
)
async def test_probe_safety_rejects_before_any_control_click(
    free_membership: bool,
    url: str,
    count: int,
    control: dict[str, bool],
) -> None:
    locator = FakeLocator(count)
    page = FakePage(locator, url)

    clicked = await click_validated(
        page,
        ".js-slide-forward",
        control,
        free_membership=free_membership,
    )

    assert clicked is False
    assert locator.clicks == 0


@pytest.mark.asyncio
async def test_probe_safety_allows_only_validated_control() -> None:
    locator = FakeLocator()
    page = FakePage(locator)

    clicked = await click_validated(
        page,
        ".js-slide-backward",
        {"visible": True, "href_is_episode": False, "forbidden_label": False},
        free_membership=True,
        dom_click=True,
    )

    assert clicked is True
    assert locator.clicks == 1
