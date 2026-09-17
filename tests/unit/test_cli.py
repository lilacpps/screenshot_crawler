import builtins
import sys
from pathlib import Path
from typing import ClassVar

import pytest

from screenshot_crawler import cli
from screenshot_crawler.cli import _parser
from screenshot_crawler.discovery.models import DiscoveryResult


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
    assert not args.all
    assert args.mode == "incremental"
    assert args.watchlist == Path("custom.yaml")
    assert args.catalog == Path("custom.sqlite")
    assert args.cdp_endpoint == "http://127.0.0.1:9333"
    assert args.env_file == Path(".env")
    assert not args.keep_open


@pytest.mark.parametrize("mode", ["incremental", "full"])
def test_discover_parser_accepts_all(mode: str) -> None:
    args = _parser().parse_args(["discover", "--all", "--mode", mode])

    assert args.all
    assert args.key is None
    assert args.mode == mode


@pytest.mark.parametrize(
    "argv",
    [
        ["discover", "--mode", "incremental"],
        ["discover", "--key", "foo", "--all", "--mode", "incremental"],
    ],
)
def test_discover_parser_requires_one_target_selector(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(argv)


def test_main_returns_nonzero_for_discover_all_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail(_args: object) -> None:
        raise cli.DiscoveryAllError([("B", "failure for B")], total=3)

    monkeypatch.setattr(cli, "_run_discover", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        ["screenshot-crawler", "discover", "--all", "--mode", "incremental"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 2
    assert "Error: Discovery failed for 1 of 3 targets" in capsys.readouterr().err


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


def test_batch_run_parser_accepts_execution_options() -> None:
    defaults = _parser().parse_args(["batch", "run", "--site", "mangaone"])
    args = _parser().parse_args(
        [
            "batch",
            "run",
            "--site",
            "mangaone",
            "--catalog",
            "custom.sqlite",
            "--output-root",
            "runs",
            "--library-dir",
            "library",
            "--env-file",
            "custom.env",
            "--cdp-endpoint",
            "http://127.0.0.1:9333",
            "--limit",
            "2",
            "--keep-open",
        ]
    )

    assert defaults.output_root == Path("output/batch")
    assert defaults.library_dir == Path("output/Books")
    assert defaults.env_file == Path(".env")
    assert defaults.limit is None
    assert not defaults.keep_open
    assert args.batch_action == "run"
    assert args.site == "mangaone"
    assert args.catalog == Path("custom.sqlite")
    assert args.output_root == Path("runs")
    assert args.library_dir == Path("library")
    assert args.env_file == Path("custom.env")
    assert args.cdp_endpoint == "http://127.0.0.1:9333"
    assert args.limit == 2
    assert args.keep_open


def test_batch_run_parser_rejects_zero_limit() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            ["batch", "run", "--site", "mangaone", "--limit", "0"]
        )


class FakeLoginAdapter:
    def __init__(self, *, should_fail: bool) -> None:
        self.should_fail = should_fail
        self.page = None

    async def login(self, page: object, **_kwargs: object) -> None:
        self.page = page
        if self.should_fail:
            raise RuntimeError("login failed")


class FakeDiscoverySession:
    instances: ClassVar[list["FakeDiscoverySession"]] = []

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.page = object()
        self.closed_pages: list[object] = []
        self.closed = False
        self.__class__.instances.append(self)

    @classmethod
    async def connect(cls, endpoint: str) -> "FakeDiscoverySession":
        return cls(endpoint)

    async def new_page(self) -> object:
        return self.page

    async def close_page(self, page: object) -> None:
        self.closed_pages.append(page)

    async def close(self) -> None:
        self.closed = True


class FakeDiscoveryService:
    calls: ClassVar[list[tuple[str, str, object]]] = []
    failures: ClassVar[set[str]] = set()

    def __init__(self, _catalog: object, _registry: object) -> None:
        pass

    async def discover(self, page: object, target: object, mode: str) -> DiscoveryResult:
        self.calls.append((target.key, mode, page))
        if target.key in self.failures:
            raise RuntimeError(f"failure for {target.key}")
        return DiscoveryResult(
            mode=mode,  # type: ignore[arg-type]
            target_key=target.key,
            observed_count=2,
            new_count=1,
            known_count=1,
            complete=None,
            stopped_reason="known_streak",
            warnings=(),
        )


def _write_discover_watchlist(path: Path, targets: str) -> None:
    path.write_text(f"targets:\n{targets}", encoding="utf-8")


@pytest.mark.parametrize("mode", ["incremental", "full"])
async def test_discover_all_uses_enabled_targets_in_file_order_and_propagates_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    watchlist = tmp_path / "watchlist.yaml"
    _write_discover_watchlist(
        watchlist,
        "  - key: A\n"
        "    site: mangaone\n"
        "    url: https://example.test/a\n"
        "    enabled: true\n"
        "  - key: B\n"
        "    site: mangaone\n"
        "    url: https://example.test/b\n"
        "    enabled: false\n"
        "  - key: C\n"
        "    site: bookwalker\n"
        "    url: https://example.test/c\n"
        "    enabled: true\n",
    )
    FakeDiscoverySession.instances = []
    FakeDiscoveryService.calls = []
    FakeDiscoveryService.failures = set()
    monkeypatch.setattr(cli, "BrowserSession", FakeDiscoverySession)
    monkeypatch.setattr(cli, "DiscoveryService", FakeDiscoveryService)
    monkeypatch.setattr(cli, "_discovery_registry", lambda: object())
    monkeypatch.setattr(
        cli,
        "resolve_cdp_endpoint",
        lambda **kwargs: f"endpoint:{kwargs['site']}",
    )

    args = _parser().parse_args(
        ["discover", "--all", "--mode", mode, "--watchlist", str(watchlist)]
    )
    await cli._run_discover(args)

    assert [(key, target_mode) for key, target_mode, _ in FakeDiscoveryService.calls] == [
        ("A", mode),
        ("C", mode),
    ]
    assert [session.endpoint for session in FakeDiscoverySession.instances] == [
        "endpoint:mangaone",
        "endpoint:bookwalker",
    ]
    assert all(session.closed for session in FakeDiscoverySession.instances)
    assert all(session.closed_pages == [session.page] for session in FakeDiscoverySession.instances)


async def test_discover_all_continues_after_failure_and_exits_as_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    watchlist = tmp_path / "watchlist.yaml"
    _write_discover_watchlist(
        watchlist,
        "  - key: A\n    site: mangaone\n    url: https://example.test/a\n"
        "  - key: B\n    site: mangaone\n    url: https://example.test/b\n"
        "  - key: C\n    site: mangaone\n    url: https://example.test/c\n",
    )
    FakeDiscoverySession.instances = []
    FakeDiscoveryService.calls = []
    FakeDiscoveryService.failures = {"B"}
    monkeypatch.setattr(cli, "BrowserSession", FakeDiscoverySession)
    monkeypatch.setattr(cli, "DiscoveryService", FakeDiscoveryService)
    monkeypatch.setattr(cli, "_discovery_registry", lambda: object())

    args = _parser().parse_args(
        ["discover", "--all", "--mode", "incremental", "--watchlist", str(watchlist)]
    )
    with pytest.raises(cli.DiscoveryAllError):
        await cli._run_discover(args)

    assert [key for key, _mode, _page in FakeDiscoveryService.calls] == ["A", "B", "C"]
    output = capsys.readouterr().out
    assert "[3/3] C (mangaone)" in output
    assert "succeeded: 2" in output
    assert "failed: 1" in output
    assert "B: failure for B" in output


async def test_discover_all_success_is_normal_and_empty_enabled_is_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    watchlist = tmp_path / "watchlist.yaml"
    _write_discover_watchlist(
        watchlist,
        "  - key: disabled\n    site: mangaone\n    url: https://example.test/disabled\n"
        "    enabled: false\n",
    )
    monkeypatch.setattr(
        cli,
        "BrowserSession",
        type("UnexpectedSession", (), {"connect": classmethod(lambda *_args: pytest.fail("connected"))}),
    )
    monkeypatch.setattr(cli, "DiscoveryService", lambda *_args: pytest.fail("discovered"))
    monkeypatch.setattr(cli, "CatalogService", lambda *_args: pytest.fail("catalog opened"))

    args = _parser().parse_args(
        ["discover", "--all", "--mode", "full", "--watchlist", str(watchlist)]
    )
    await cli._run_discover(args)

    assert capsys.readouterr().out.strip() == "No enabled watchlist targets."


async def test_discover_key_still_runs_one_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = tmp_path / "watchlist.yaml"
    _write_discover_watchlist(
        watchlist,
        "  - key: A\n    site: mangaone\n    url: https://example.test/a\n",
    )
    FakeDiscoveryService.calls = []
    FakeDiscoveryService.failures = set()
    monkeypatch.setattr(cli, "BrowserSession", FakeDiscoverySession)
    monkeypatch.setattr(cli, "DiscoveryService", FakeDiscoveryService)
    monkeypatch.setattr(cli, "_discovery_registry", lambda: object())

    args = _parser().parse_args(
        ["discover", "--key", "A", "--mode", "incremental", "--watchlist", str(watchlist)]
    )
    await cli._run_discover(args)

    assert [key for key, _mode, _page in FakeDiscoveryService.calls] == ["A"]


async def test_discover_key_keep_open_waits_before_closing_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = tmp_path / "watchlist.yaml"
    _write_discover_watchlist(
        watchlist,
        "  - key: A\n    site: mangaone\n    url: https://example.test/a\n",
    )
    FakeDiscoverySession.instances = []
    FakeDiscoveryService.calls = []
    FakeDiscoveryService.failures = set()
    monkeypatch.setattr(cli, "BrowserSession", FakeDiscoverySession)
    monkeypatch.setattr(cli, "DiscoveryService", FakeDiscoveryService)
    monkeypatch.setattr(cli, "_discovery_registry", lambda: object())
    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": pytest.fail("session closed before keep-open input")
        if FakeDiscoverySession.instances[0].closed
        else "",
    )

    args = _parser().parse_args(
        [
            "discover",
            "--key",
            "A",
            "--mode",
            "incremental",
            "--keep-open",
            "--watchlist",
            str(watchlist),
        ]
    )
    await cli._run_discover(args)

    assert FakeDiscoverySession.instances[0].closed


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
