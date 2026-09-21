import builtins
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from screenshot_crawler import cli
from screenshot_crawler.cli import _parser
from screenshot_crawler.core.state import PageState
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


@pytest.mark.asyncio
async def test_crawl_disconnects_browser_before_packaging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeAdapter:
        def get_output_metadata(self) -> dict[str, str]:
            return {"title": "Test"}

    class FakeRegistry:
        def create(self, _site: str) -> FakeAdapter:
            return FakeAdapter()

    class FakeSession:
        @classmethod
        async def connect(cls, _endpoint: str) -> "FakeSession":
            return cls()

        async def new_page(self) -> object:
            return object()

        async def close_page(self, _page: object) -> None:
            events.append("close_page")

        async def close(self) -> None:
            events.append("close_session")

    class FakeRunner:
        def __init__(self, _config: object) -> None:
            pass

        async def run(self, _page: object, _adapter: FakeAdapter) -> object:
            events.append("crawl")
            return SimpleNamespace(
                pages=(object(),),
                stop_reason="next_content",
                stop_state=PageState.NEXT_CONTENT,
            )

    def fake_package(*_args: object, **_kwargs: object) -> object:
        events.append("package")
        return SimpleNamespace(
            archive_path=tmp_path / "archive.zip",
            status_path=tmp_path / "status.json",
        )

    monkeypatch.setattr(cli, "_registry", lambda: FakeRegistry())
    monkeypatch.setattr(cli, "BrowserSession", FakeSession)
    monkeypatch.setattr(cli, "CrawlerRunner", FakeRunner)
    monkeypatch.setattr(cli, "package_crawl_output", fake_package)

    args = _parser().parse_args(
        [
            "crawl",
            "--site",
            "magapoke",
            "--url",
            "https://example.test/title/1/episode/2",
            "--output-dir",
            str(tmp_path / "crawl"),
            "--cdp-endpoint",
            "http://127.0.0.1:9222",
        ]
    )
    await cli._run_crawl(args)

    assert events == ["crawl", "close_page", "close_session", "package"]


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


def test_discover_parser_accepts_site() -> None:
    args = _parser().parse_args(
        ["discover", "--site", "mangaone", "--mode", "incremental"]
    )

    assert args.site == "mangaone"
    assert args.key is None
    assert not args.all
    assert args.mode == "incremental"


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
        ["discover", "--site", "mangaone", "--all", "--mode", "incremental"],
        ["discover", "--key", "foo", "--site", "mangaone", "--mode", "incremental"],
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


@pytest.mark.parametrize("selector", [["--all"], ["--site", "mangaone"]])
def test_main_rejects_multi_target_discover_keep_open(
    monkeypatch: pytest.MonkeyPatch,
    selector: list[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["screenshot-crawler", "discover", *selector, "--mode", "incremental", "--keep-open"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 2


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
        [
            "catalog", "export", "--catalog", "custom.sqlite",
            "--output-dir", "output/export",
        ]
    )

    assert defaults.command == "catalog"
    assert defaults.catalog_action == "export"
    assert defaults.catalog == Path("catalog.sqlite")
    assert defaults.output_dir == Path("catalog-export")
    assert custom.catalog == Path("custom.sqlite")
    assert custom.output_dir == Path("output/export")


def test_catalog_backup_parser_accepts_default_and_optional_output() -> None:
    defaults = _parser().parse_args(["catalog", "backup"])
    custom = _parser().parse_args(
        ["catalog", "backup", "--catalog", "custom.sqlite", "--output", "backup.sqlite"]
    )

    assert defaults.catalog_action == "backup"
    assert defaults.catalog == Path("catalog.sqlite")
    assert defaults.output is None
    assert custom.catalog == Path("custom.sqlite")
    assert custom.output == Path("backup.sqlite")


def test_catalog_migrate_parser_accepts_defaults_and_backup_dir() -> None:
    defaults = _parser().parse_args(["catalog", "migrate"])
    custom = _parser().parse_args(
        ["catalog", "migrate", "--catalog", "custom.sqlite", "--backup-dir", "snapshots"]
    )

    assert defaults.catalog_action == "migrate"
    assert defaults.catalog == Path("catalog.sqlite")
    assert defaults.backup_dir == Path("backup")
    assert custom.catalog == Path("custom.sqlite")
    assert custom.backup_dir == Path("snapshots")


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


def test_batch_policy_registry_contains_bookwalker_and_mangaone() -> None:
    assert cli._batch_policy_registry().sites() == ("bookwalker", "mangaone")


def test_discovery_registry_contains_magapoke() -> None:
    assert cli._discovery_registry().sites() == ("bookwalker", "magapoke", "mangaone")


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
    result_overrides: ClassVar[dict[str, tuple[str, bool | None]]] = {}

    def __init__(self, _catalog: object, _registry: object) -> None:
        pass

    async def discover(self, page: object, target: object, mode: str) -> DiscoveryResult:
        self.calls.append((target.key, mode, page))
        if target.key in self.failures:
            raise RuntimeError(f"failure for {target.key}")
        stopped_reason, complete = self.result_overrides.get(
            target.key,
            ("known_streak", None),
        )
        return DiscoveryResult(
            mode=mode,  # type: ignore[arg-type]
            target_key=target.key,
            observed_count=2,
            new_count=1,
            known_count=1,
            complete=complete,
            stopped_reason=stopped_reason,
            warnings=(),
        )


def _write_discover_watchlist(path: Path, targets: str) -> None:
    lines: list[str] = []
    for line in targets.splitlines():
        lines.append(line)
        if line.lstrip().startswith("- key:"):
            key = line.split(":", 1)[1].strip()
            indent = line[: len(line) - len(line.lstrip())] + "  "
            lines.append(f"{indent}work_key: work-{key}")
            lines.append(f"{indent}label: Label {key}")
    path.write_text("targets:\n" + "\n".join(lines) + "\n", encoding="utf-8")


def test_watch_add_requires_work_key_and_label_and_watch_list_displays_them(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    watchlist = tmp_path / "watchlist.yaml"
    args = _parser().parse_args(
        [
            "watch", "add", "--watchlist", str(watchlist), "--key", "scope",
            "--work-key", "work", "--site", "mangaone", "--url", "https://example.test",
            "--label", "作品",
        ]
    )
    cli._run_watch(args)
    output = capsys.readouterr().out
    assert "Added watchlist target 'scope'." in output

    cli._run_watch(_parser().parse_args(["watch", "list", "--watchlist", str(watchlist)]))
    listed = capsys.readouterr().out
    assert "scope\twork\tmangaone\tenabled\thttps://example.test\t作品" in listed


def test_watch_add_requires_work_key_and_label() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            ["watch", "add", "--key", "scope", "--site", "mangaone", "--url", "https://example.test"]
        )


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
    FakeDiscoveryService.result_overrides = (
        {"A": ("exhausted", True), "C": ("exhausted", True)}
        if mode == "full"
        else {}
    )
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


@pytest.mark.parametrize("mode", ["incremental", "full"])
async def test_discover_site_uses_enabled_matching_targets_in_file_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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
        "    enabled: true\n"
        "  - key: D\n"
        "    site: mangaone\n"
        "    url: https://example.test/d\n"
        "    enabled: true\n",
    )
    FakeDiscoverySession.instances = []
    FakeDiscoveryService.calls = []
    FakeDiscoveryService.failures = set()
    FakeDiscoveryService.result_overrides = {}
    monkeypatch.setattr(cli, "BrowserSession", FakeDiscoverySession)
    monkeypatch.setattr(cli, "DiscoveryService", FakeDiscoveryService)
    monkeypatch.setattr(cli, "_discovery_registry", lambda: object())
    monkeypatch.setattr(
        cli,
        "resolve_cdp_endpoint",
        lambda **kwargs: f"endpoint:{kwargs['site']}",
    )

    args = _parser().parse_args(
        ["discover", "--site", "mangaone", "--mode", mode, "--watchlist", str(watchlist)]
    )
    await cli._run_discover(args)

    assert [(key, target_mode) for key, target_mode, _ in FakeDiscoveryService.calls] == [
        ("A", mode),
        ("D", mode),
    ]
    assert [session.endpoint for session in FakeDiscoverySession.instances] == [
        "endpoint:mangaone",
        "endpoint:mangaone",
    ]
    assert all(session.closed for session in FakeDiscoverySession.instances)
    output = capsys.readouterr().out
    assert "  site: mangaone" in output
    assert "  targets: 2" in output


async def test_discover_site_continues_after_failure_and_exits_as_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    watchlist = tmp_path / "watchlist.yaml"
    _write_discover_watchlist(
        watchlist,
        "  - key: A\n    site: mangaone\n    url: https://example.test/a\n"
        "  - key: B\n    site: bookwalker\n    url: https://example.test/b\n"
        "  - key: C\n    site: mangaone\n    url: https://example.test/c\n",
    )
    FakeDiscoverySession.instances = []
    FakeDiscoveryService.calls = []
    FakeDiscoveryService.failures = {"A"}
    FakeDiscoveryService.result_overrides = {}
    monkeypatch.setattr(cli, "BrowserSession", FakeDiscoverySession)
    monkeypatch.setattr(cli, "DiscoveryService", FakeDiscoveryService)
    monkeypatch.setattr(cli, "_discovery_registry", lambda: object())

    args = _parser().parse_args(
        ["discover", "--site", "mangaone", "--mode", "incremental", "--watchlist", str(watchlist)]
    )
    with pytest.raises(cli.DiscoveryAllError):
        await cli._run_discover(args)

    assert [key for key, _mode, _page in FakeDiscoveryService.calls] == ["A", "C"]
    output = capsys.readouterr().out
    assert "[2/2] C (mangaone)" in output
    assert "  site: mangaone" in output
    assert "succeeded: 1" in output
    assert "failed: 1" in output
    assert "A: failure for A" in output


async def test_discover_site_with_no_enabled_targets_is_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    watchlist = tmp_path / "watchlist.yaml"
    _write_discover_watchlist(
        watchlist,
        "  - key: disabled\n    site: mangaone\n    url: https://example.test/disabled\n"
        "    enabled: false\n"
        "  - key: other\n    site: bookwalker\n    url: https://example.test/other\n",
    )
    monkeypatch.setattr(
        cli,
        "BrowserSession",
        type("UnexpectedSession", (), {"connect": classmethod(lambda *_args: pytest.fail("connected"))}),
    )
    monkeypatch.setattr(cli, "DiscoveryService", lambda *_args: pytest.fail("discovered"))
    monkeypatch.setattr(cli, "CatalogService", lambda *_args: pytest.fail("catalog opened"))

    args = _parser().parse_args(
        ["discover", "--site", "mangaone", "--mode", "full", "--watchlist", str(watchlist)]
    )
    await cli._run_discover(args)

    assert capsys.readouterr().out.strip() == (
        "No enabled watchlist targets for site 'mangaone'."
    )


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
    FakeDiscoveryService.result_overrides = {}
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


@pytest.mark.parametrize(
    ("mode", "incomplete_complete", "success_result"),
    [
        ("incremental", None, ("known_streak", None)),
        ("full", False, ("exhausted", True)),
    ],
)
async def test_discover_all_treats_incomplete_result_as_failure_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    incomplete_complete: bool | None,
    success_result: tuple[str, bool | None],
) -> None:
    watchlist = tmp_path / "watchlist.yaml"
    _write_discover_watchlist(
        watchlist,
        "  - key: A\n    site: mangaone\n    url: https://example.test/a\n"
        "  - key: B\n    site: mangaone\n    url: https://example.test/b\n",
    )
    FakeDiscoverySession.instances = []
    FakeDiscoveryService.calls = []
    FakeDiscoveryService.failures = set()
    FakeDiscoveryService.result_overrides = {
        "A": ("incomplete", incomplete_complete),
        "B": success_result,
    }
    monkeypatch.setattr(cli, "BrowserSession", FakeDiscoverySession)
    monkeypatch.setattr(cli, "DiscoveryService", FakeDiscoveryService)
    monkeypatch.setattr(cli, "_discovery_registry", lambda: object())

    args = _parser().parse_args(
        ["discover", "--all", "--mode", mode, "--watchlist", str(watchlist)]
    )
    with pytest.raises(cli.DiscoveryAllError):
        await cli._run_discover(args)

    assert [key for key, _mode, _page in FakeDiscoveryService.calls] == ["A", "B"]
    output = capsys.readouterr().out
    assert "stopped_reason: incomplete" in output
    assert "status: FAILED" in output
    assert "error: Discovery incomplete" in output
    assert "status: OK" in output
    assert "succeeded: 1" in output
    assert "failed: 1" in output


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
    FakeDiscoveryService.result_overrides = {}
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
    FakeDiscoveryService.result_overrides = {}
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
