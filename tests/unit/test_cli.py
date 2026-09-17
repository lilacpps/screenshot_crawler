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
    assert args.access_strategy == "auto"
    assert args.title is None
    assert args.author is None
    assert args.order is None
    assert args.genre is None
    assert args.env_file == Path(".env")
    assert not hasattr(args, "auth_state")
    assert not hasattr(args, "auth_required")
    assert not hasattr(args, "headed")


def test_discover_parser_accepts_watchlist_catalog_and_mode() -> None:
    args = _parser().parse_args(
        [
            "discover",
            "--key",
            "juou-to-yakusou",
            "--mode",
            "incremental",
            "--watchlist",
            "custom.yaml",
            "--catalog",
            "custom.sqlite",
            "--cdp-endpoint",
            "http://127.0.0.1:9333",
        ]
    )

    assert args.key == "juou-to-yakusou"
    assert args.mode == "incremental"
    assert args.watchlist == Path("custom.yaml")
    assert args.catalog == Path("custom.sqlite")
    assert args.cdp_endpoint == "http://127.0.0.1:9333"
    assert args.env_file == Path(".env")
    assert not args.keep_open


def test_crawl_accepts_access_strategy_and_output_metadata() -> None:
    args = _parser().parse_args(
        [
            "crawl",
            "--site",
            "bookwalker",
            "--url",
            "https://bookwalker.jp/",
            "--access-strategy",
            "quota",
            "--title",
            "作品A",
            "--author",
            "作者A",
            "--order",
            "第12巻",
            "--genre",
            "漫画",
        ]
    )

    assert args.access_strategy == "quota"
    assert (args.title, args.author, args.order, args.genre) == (
        "作品A",
        "作者A",
        "第12巻",
        "漫画",
    )


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


def test_watch_parser_accepts_watchlist_override_before_or_after_action() -> None:
    before = _parser().parse_args(
        ["watch", "--watchlist", "custom.yaml", "list"]
    )
    after = _parser().parse_args(
        ["watch", "list", "--watchlist", "custom.yaml"]
    )

    assert before.watchlist == Path("custom.yaml")
    assert after.watchlist == Path("custom.yaml")


def test_catalog_export_parser_accepts_defaults_and_overrides() -> None:
    defaults = _parser().parse_args(["catalog", "export"])
    custom = _parser().parse_args(
        ["catalog", "export", "--catalog", "custom.sqlite", "--output", "output/export.csv"]
    )

    assert defaults.command == "catalog"
    assert defaults.catalog_action == "export"
    assert defaults.catalog == Path("catalog.sqlite")
    assert defaults.output == Path("catalog-export.csv")
    assert custom.catalog == Path("custom.sqlite")
    assert custom.output == Path("output/export.csv")


def test_batch_plan_parser_accepts_site_and_catalog() -> None:
    defaults = _parser().parse_args(["batch", "plan", "--site", "mangaone"])
    custom = _parser().parse_args(
        ["batch", "plan", "--site", "mangaone", "--catalog", "custom.sqlite"]
    )

    assert defaults.command == "batch"
    assert defaults.batch_action == "plan"
    assert defaults.site == "mangaone"
    assert defaults.catalog == Path("catalog.sqlite")
    assert custom.catalog == Path("custom.sqlite")


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
