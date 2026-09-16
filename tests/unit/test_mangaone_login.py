from unittest.mock import AsyncMock, Mock

import pytest

from screenshot_crawler.site_adapters.mangaone.login import (
    MangaOneLoginError,
    login_mangaone,
)


class FakeLocator:
    def __init__(
        self,
        *,
        visible: bool = True,
        count: int = 1,
        children: dict[str, "FakeLocator"] | None = None,
    ) -> None:
        self.visible = visible
        self.count_value = count
        self.children = children or {}
        self.fill = AsyncMock()
        self.click = AsyncMock()
        self.first = self

    def locator(self, selector: str) -> "FakeLocator":
        return self.children.get(selector, self)

    def filter(self, **_kwargs: object) -> "FakeLocator":
        return self

    def nth(self, _index: int) -> "FakeLocator":
        return self

    async def count(self) -> int:
        return self.count_value

    async def is_visible(self, **_kwargs: object) -> bool:
        return self.visible


class FakePage(FakeLocator):
    def __init__(self, *, final_url: str = "https://manga-one.com/") -> None:
        super().__init__()
        self.url = "about:blank"
        self.final_url = final_url
        self.goto = AsyncMock(side_effect=self._goto)
        self.wait_for_url = AsyncMock(side_effect=self._wait_for_url)
        self.wait_for_timeout = AsyncMock()

    async def _goto(self, url: str, **_kwargs: object) -> None:
        self.url = url

    async def _wait_for_url(self, _predicate: object, **_kwargs: object) -> None:
        self.url = self.final_url


@pytest.mark.asyncio
async def test_login_mangaone_fills_named_fields_and_submits() -> None:
    page = FakePage()
    email = FakeLocator()
    password = FakeLocator()
    submit = FakeLocator()
    form = FakeLocator(
        children={
            "button[type='submit']": submit,
            "button": submit,
        }
    )
    page.locator = Mock(side_effect=[email, password, form, FakeLocator(count=0)])

    await login_mangaone(page, email="reader@example.com", password="secret")

    page.goto.assert_awaited_once_with(
        "https://manga-one.com/login",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    email.fill.assert_awaited_once_with("reader@example.com")
    password.fill.assert_awaited_once_with("secret")
    submit.click.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_login_mangaone_stops_when_form_remains_visible() -> None:
    page = FakePage()
    email = FakeLocator()
    password = FakeLocator()
    form = FakeLocator()
    submit = FakeLocator()
    form.children = {
        "button[type='submit']": submit,
        "button": submit,
    }
    page.locator = Mock(side_effect=[email, password, form, form])

    with pytest.raises(MangaOneLoginError, match="login form is still visible"):
        await login_mangaone(page, email="reader@example.com", password="secret")
