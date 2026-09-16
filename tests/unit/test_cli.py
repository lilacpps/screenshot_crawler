from pathlib import Path

import pytest

from screenshot_crawler import cli
from screenshot_crawler.cli import _parser


def test_crawl_uses_cdp_options() -> None:
    args = _parser().parse_args(
        [
            "crawl",
            "--site",
            "mangaone",
            "--url",
            "https://manga-one.com/manga/2379/chapter/214131",
            "--cdp-endpoint",
            "http://127.0.0.1:9333",
        ]
    )

    assert args.cdp_endpoint == "http://127.0.0.1:9333"
    assert args.env_file == Path(".env")
    assert not hasattr(args, "auth_state")
    assert not hasattr(args, "auth_required")
    assert not hasattr(args, "headed")


@pytest.mark.parametrize("option", ["--auth-state", "--auth-required", "--headed"])
def test_crawl_rejects_non_cdp_browser_options(option: str) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "crawl",
                "--site",
                "mangaone",
                "--url",
                "https://manga-one.com/",
                option,
            ]
        )


class FakeLoginAdapter:
    def __init__(self, *, should_fail: bool) -> None:
        self.should_fail = should_fail
        self.page = None

    async def login(self, page: object, **_kwargs: object) -> None:
        self.page = page
        if self.should_fail:
            raise RuntimeError("login failed")


class FakeLoginRegistry:
    def __init__(self, adapter: FakeLoginAdapter) -> None:
        self.adapter = adapter

    def create(self, _site: str) -> FakeLoginAdapter:
        return self.adapter


class FakeLoginSession:
    instance = None

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.page = object()
        self.closed_pages: list[object] = []
        self.closed = False
        FakeLoginSession.instance = self

    @classmethod
    async def connect(cls, endpoint: str) -> "FakeLoginSession":
        return cls(endpoint)

    def existing_page(self) -> object:
        raise AssertionError("login must not reuse an existing page")

    async def new_page(self) -> object:
        return self.page

    async def close_page(self, page: object) -> None:
        self.closed_pages.append(page)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("should_fail", [False, True])
async def test_login_always_uses_and_closes_a_new_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    should_fail: bool,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CRAWLER_CDP_ENDPOINT=http://shared.test:9222\n"
        "BOOKWALKER_URL=https://bookwalker.jp/\n"
        "BOOKWALKER_EMAIL=reader@example.com\n"
        "BOOKWALKER_PASSWORD=secret\n",
        encoding="utf-8",
    )
    adapter = FakeLoginAdapter(should_fail=should_fail)
    monkeypatch.setattr(cli, "_registry", lambda: FakeLoginRegistry(adapter))
    monkeypatch.setattr(cli, "BrowserSession", FakeLoginSession)
    args = _parser().parse_args(
        ["login", "--site", "bookwalker", "--env-file", str(env_file)]
    )

    if should_fail:
        with pytest.raises(RuntimeError, match="login failed"):
            await cli._run_login(args)
    else:
        await cli._run_login(args)

    session = FakeLoginSession.instance
    assert session is not None
    assert session.endpoint == "http://shared.test:9222"
    assert adapter.page is session.page
    assert session.closed_pages == [session.page]
    assert session.closed
