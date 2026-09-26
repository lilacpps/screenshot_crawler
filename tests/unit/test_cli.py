import asyncio
import builtins
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from screenshot_crawler import cli
from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
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


def test_batch_grant_only_accepts_explicit_resource_and_all_shape() -> None:
    args = _parser().parse_args(
        ["batch", "run", "--site", "magapoke", "--grant-only", "work_ticket"]
    )
    assert args.grant_only == "work_ticket"
    all_args = _parser().parse_args(
        ["batch", "run", "--site", "magapoke", "--grant-only", "all"]
    )
    assert all_args.grant_only == "all"


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


def test_catalog_item_status_parser_accepts_read_and_transition_forms() -> None:
    read = _parser().parse_args(["catalog", "item-status", "13745"])
    completed = _parser().parse_args(
        ["catalog", "item-status", "13745", "completed", "--catalog", "custom.sqlite"]
    )
    pending = _parser().parse_args(["catalog", "item-status", "13745", "pending"])

    assert read.item_id == 13745
    assert read.status is None
    assert read.catalog == Path("catalog.sqlite")
    assert completed.status == "completed"
    assert completed.catalog == Path("custom.sqlite")
    assert pending.status == "pending"


@pytest.mark.parametrize("status", ["skipped", "other"])
def test_catalog_item_status_parser_rejects_unsupported_status(status: str) -> None:
    with pytest.raises(SystemExit) as error:
        _parser().parse_args(["catalog", "item-status", "13745", status])

    assert error.value.code == 2


def test_catalog_item_status_cli_updates_batch_eligibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    service = CatalogService(catalog_path)
    work = service.create_work(WorkInput(work_key="manual-status", title="Manual status"))
    item = service.create_item(ItemInput(item_title="Chapter 1"), work_id=work.id)
    source = service.create_source(
        SourceInput(site="mangaone", external_id="chapter-1", access_mode="free"),
        item_id=item.id,
    )
    service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.test/chapter/1"),
        source_id=source.id,
    )
    planner = BatchPlanner(service, cli._batch_policy_registry())

    monkeypatch.setattr(
        sys,
        "argv",
        ["screenshot-crawler", "catalog", "item-status", str(item.id), "completed",
         "--catalog", str(catalog_path)],
    )
    cli.main()
    completed_output = capsys.readouterr().out.strip()
    completed = service.get_item(item.id)
    assert completed_output.startswith(f"item={item.id} status=completed completed_at=")
    assert completed.completed_at is not None
    assert "+09:00" in completed.completed_at
    completed_at = datetime.fromisoformat(completed.completed_at)
    assert completed_at.utcoffset() is not None
    cli.main()
    repeated_completed_output = capsys.readouterr().out.strip()
    assert repeated_completed_output.startswith(
        f"item={item.id} status=completed completed_at="
    )
    assert service.get_item(item.id).completed_at is not None
    completed_plan = planner.plan(site="mangaone")
    assert all(candidate.item_id != item.id for candidate in completed_plan.candidates)
    assert any(
        skipped.item_id == item.id and skipped.reason == "completed"
        for skipped in completed_plan.skipped
    )
    assert service.list_crawl_runs(item_id=item.id) == []
    assert service.list_artifacts(item_id=item.id) == []

    monkeypatch.setattr(
        sys,
        "argv",
        ["screenshot-crawler", "catalog", "item-status", str(item.id), "pending",
         "--catalog", str(catalog_path)],
    )
    cli.main()
    assert capsys.readouterr().out.strip() == (
        f"item={item.id} status=pending completed_at=None"
    )
    pending = service.get_item(item.id)
    assert pending.status == "pending"
    assert pending.completed_at is None
    monkeypatch.setattr(
        sys,
        "argv",
        ["screenshot-crawler", "catalog", "item-status", str(item.id), "pending",
         "--catalog", str(catalog_path)],
    )
    cli.main()
    assert capsys.readouterr().out.strip() == (
        f"item={item.id} status=pending completed_at=None"
    )
    pending_plan = planner.plan(site="mangaone")
    assert [candidate.item_id for candidate in pending_plan.candidates] == [item.id]


def test_catalog_item_status_cli_displays_current_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    service = CatalogService(catalog_path)
    work = service.create_work(WorkInput(work_key="status-display", title="Status display"))
    item = service.create_item(ItemInput(), work_id=work.id)
    monkeypatch.setattr(
        sys,
        "argv",
        ["screenshot-crawler", "catalog", "item-status", str(item.id),
         "--catalog", str(catalog_path)],
    )

    cli.main()

    assert capsys.readouterr().out.strip() == (
        f"item={item.id} status=pending completed_at=None"
    )


def test_catalog_item_status_cli_missing_item_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["screenshot-crawler", "catalog", "item-status", "123", "--catalog",
         str(tmp_path / "catalog.sqlite")],
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert "Catalog item not found: 123" in capsys.readouterr().err


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


def test_batch_policy_registry_contains_bookwalker_jumpplus_magapoke_and_mangaone() -> None:
    assert cli._batch_policy_registry().sites() == (
        "bookwalker",
        "jumpplus",
        "magapoke",
        "mangaone",
    )


def test_discovery_registry_contains_magapoke() -> None:
    assert cli._discovery_registry().sites() == (
        "bookwalker",
        "jumpplus",
        "magapoke",
        "mangaone",
    )


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


def test_batch_plan_magapoke_shows_potential_premium_pass_without_browser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str | None] = []

    def candidate(strategy: str, index: int) -> SimpleNamespace:
        return SimpleNamespace(
            item_id=index,
            source_id=index,
            metadata={},
            access_mode="quota" if strategy == "quota" else "free",
            access_strategy=strategy,
            locator=f"https://example.invalid/{index}",
        )

    normal = [candidate("direct", index) for index in range(5)] + [
        candidate("quota", 5)
    ]
    premium = [candidate("quota", index) for index in range(135)]

    class FakePlanner:
        def __init__(self, *_args: object) -> None:
            pass

        def plan(self, *, site: str, quota_resource: str | None = None) -> object:
            assert site == "magapoke"
            calls.append(quota_resource)
            return SimpleNamespace(
                candidates=normal if quota_resource is None else premium,
                skipped=[],
                direct_count=5 if quota_resource is None else 0,
                quota_count=1 if quota_resource is None else 135,
                quota_remaining=None,
            )

    monkeypatch.setattr(cli, "CatalogService", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "_batch_policy_registry",
        lambda: SimpleNamespace(
            create=lambda _site: SimpleNamespace(
                ordered_access_resource_passes=lambda: (
                    "work_ticket",
                    "premium_ticket",
                )
            )
        ),
    )
    monkeypatch.setattr(cli, "BatchPlanner", FakePlanner)

    args = _parser().parse_args(["batch", "plan", "--site", "magapoke"])
    cli._run_batch_plan(args)

    output = capsys.readouterr().out
    assert calls == [None, "premium_ticket"]
    assert "Potential resource pass (premium_ticket):" in output
    assert "  candidates: 135" in output
    assert "  availability: checked during batch run" in output


@pytest.mark.parametrize("site", ["mangaone", "bookwalker"])
def test_batch_plan_non_magapoke_does_not_show_potential_premium_pass(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    site: str,
) -> None:
    class FakePlanner:
        def __init__(self, *_args: object) -> None:
            pass

        def plan(self, *, site: str, quota_resource: str | None = None) -> object:
            assert quota_resource is None
            return SimpleNamespace(
                candidates=[], skipped=[], direct_count=0, quota_count=0,
                quota_remaining=None,
            )

    monkeypatch.setattr(cli, "CatalogService", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "_batch_policy_registry",
        lambda: SimpleNamespace(
            create=lambda _site: SimpleNamespace(
                ordered_access_resource_passes=lambda: ()
            )
        ),
    )
    monkeypatch.setattr(cli, "BatchPlanner", FakePlanner)

    args = _parser().parse_args(["batch", "plan", "--site", site])
    cli._run_batch_plan(args)

    assert "Potential resource pass" not in capsys.readouterr().out


def test_batch_run_continues_after_work_ticket_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidates = [
        SimpleNamespace(
            item_id=1, source_id=11, metadata={}, access_strategy="quota",
            quota_resource="work_ticket",
        ),
        SimpleNamespace(
            item_id=2, source_id=22, metadata={}, access_strategy="direct",
            quota_resource=None,
        ),
    ]
    calls: list[int] = []

    class FakePlanner:
        def __init__(self, *_args: object) -> None:
            pass

        def plan(self, *, site: str, quota_resource: str | None = None) -> object:
            assert site == "magapoke"
            assert quota_resource is None
            return SimpleNamespace(candidates=candidates, skipped=[])

    class FakeSession:
        @classmethod
        async def connect(cls, _endpoint: str) -> "FakeSession":
            return cls()

        async def new_page(self) -> object:
            return object()

        async def close_page(self, _page: object) -> None:
            pass

        async def close(self) -> None:
            pass

    class FakeExecutor:
        def __init__(self, *_args: object) -> None:
            pass

        async def execute_candidate(
            self, _page: object, candidate: object, **_kwargs: object
        ) -> object:
            calls.append(candidate.item_id)
            if candidate.item_id == 1:
                raise cli.AccessResourceUnavailableError("work_ticket_unavailable")
            return SimpleNamespace(archive_path=Path("candidate-b.zip"))

    monkeypatch.setattr(cli, "CatalogService", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "_batch_policy_registry",
        lambda: SimpleNamespace(
            create=lambda _site: SimpleNamespace(additional_quota_resources=lambda: ())
        ),
    )
    monkeypatch.setattr(cli, "BatchPlanner", FakePlanner)
    monkeypatch.setattr(cli, "BrowserSession", FakeSession)
    monkeypatch.setattr(cli, "BatchExecutor", FakeExecutor)
    monkeypatch.setattr(cli, "_registry", lambda: object())
    monkeypatch.setattr(
        cli, "resolve_cdp_endpoint", lambda **_kwargs: "http://example.test:9222"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["screenshot-crawler", "batch", "run", "--site", "magapoke"],
    )

    cli.main()

    output = capsys.readouterr()
    assert calls == [1, 2]
    assert "SKIPPED item=1" in output.out
    assert "work_ticket_unavailable" in output.out
    assert "completed: candidate-b.zip" in output.out
    assert "FAILED" not in output.out
    assert "FAILED" not in output.err


def test_batch_run_replans_premium_after_work_pass_and_stops_at_zero_balance(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    initial = [
        SimpleNamespace(
            item_id=1, source_id=11, metadata={}, access_strategy="direct",
            quota_resource=None,
        ),
        SimpleNamespace(
            item_id=2, source_id=22, metadata={}, access_strategy="quota",
            quota_resource="work_ticket",
        ),
    ]
    premium = [
        SimpleNamespace(
            item_id=3, source_id=33, metadata={}, access_strategy="quota",
            quota_resource="premium_ticket",
        ),
        SimpleNamespace(
            item_id=4, source_id=44, metadata={}, access_strategy="quota",
            quota_resource="premium_ticket",
        ),
    ]
    calls: list[int] = []
    plans: list[str | None] = []

    class FakePlanner:
        def __init__(self, *_args: object) -> None:
            pass

        def plan(self, *, site: str, quota_resource: str | None = None) -> object:
            assert site == "magapoke"
            plans.append(quota_resource)
            return SimpleNamespace(
                candidates=initial if quota_resource is None else premium,
                skipped=[],
            )

    class FakeSession:
        @classmethod
        async def connect(cls, _endpoint: str) -> "FakeSession":
            return cls()

        async def new_page(self) -> object:
            return object()

        async def close_page(self, _page: object) -> None:
            pass

        async def close(self) -> None:
            pass

    class FakeExecutor:
        def __init__(self, *_args: object) -> None:
            pass

        async def execute_candidate(
            self, _page: object, candidate: object, **_kwargs: object
        ) -> object:
            calls.append(candidate.item_id)
            if candidate.item_id == 3:
                raise cli.AccessResourceUnavailableError(
                    "premium_ticket_exhausted", stop_resource_pass=True
                )
            return SimpleNamespace(archive_path=Path(f"item-{candidate.item_id}.zip"))

    monkeypatch.setattr(cli, "CatalogService", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "_batch_policy_registry",
        lambda: SimpleNamespace(
            create=lambda _site: SimpleNamespace(
                additional_quota_resources=lambda: ("premium_ticket",)
            )
        ),
    )
    monkeypatch.setattr(cli, "BatchPlanner", FakePlanner)
    monkeypatch.setattr(cli, "BrowserSession", FakeSession)
    monkeypatch.setattr(cli, "BatchExecutor", FakeExecutor)
    monkeypatch.setattr(cli, "_registry", lambda: object())
    monkeypatch.setattr(
        cli, "resolve_cdp_endpoint", lambda **_kwargs: "http://example.test:9222"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["screenshot-crawler", "batch", "run", "--site", "magapoke"],
    )

    cli.main()

    output = capsys.readouterr()
    assert plans == [None, "premium_ticket"]
    assert calls == [1, 2, 3]
    assert "reason=premium_ticket_exhausted" in output.out
    assert "stopping this resource pass" in output.out
    assert "item=4" not in output.out
    assert "FAILED" not in output.out


def test_batch_run_limit_spans_initial_and_premium_phases(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    initial = [
        SimpleNamespace(item_id=1, source_id=11, metadata={}, access_strategy="direct", quota_resource=None),
        SimpleNamespace(item_id=2, source_id=22, metadata={}, access_strategy="quota", quota_resource="work_ticket"),
    ]
    premium = [
        SimpleNamespace(item_id=3, source_id=33, metadata={}, access_strategy="quota", quota_resource="premium_ticket"),
        SimpleNamespace(item_id=4, source_id=44, metadata={}, access_strategy="quota", quota_resource="premium_ticket"),
        SimpleNamespace(item_id=5, source_id=55, metadata={}, access_strategy="quota", quota_resource="premium_ticket"),
    ]
    calls: list[int] = []
    plans: list[str | None] = []

    class FakePlanner:
        def __init__(self, *_args: object) -> None:
            pass

        def plan(self, *, site: str, quota_resource: str | None = None) -> object:
            assert site == "magapoke"
            plans.append(quota_resource)
            return SimpleNamespace(candidates=initial if quota_resource is None else premium, skipped=[])

    class FakeSession:
        @classmethod
        async def connect(cls, _endpoint: str) -> "FakeSession":
            return cls()

        async def new_page(self) -> object:
            return object()

        async def close_page(self, _page: object) -> None:
            pass

        async def close(self) -> None:
            pass

    class FakeExecutor:
        def __init__(self, *_args: object) -> None:
            pass

        async def execute_candidate(self, _page: object, candidate: object, **_kwargs: object) -> object:
            calls.append(candidate.item_id)
            return SimpleNamespace(archive_path=Path(f"item-{candidate.item_id}.zip"))

    monkeypatch.setattr(cli, "CatalogService", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "_batch_policy_registry",
        lambda: SimpleNamespace(
            create=lambda _site: SimpleNamespace(
                additional_quota_resources=lambda: ("premium_ticket",)
            )
        ),
    )
    monkeypatch.setattr(cli, "BatchPlanner", FakePlanner)
    monkeypatch.setattr(cli, "BrowserSession", FakeSession)
    monkeypatch.setattr(cli, "BatchExecutor", FakeExecutor)
    monkeypatch.setattr(cli, "_registry", lambda: object())
    monkeypatch.setattr(
        cli, "resolve_cdp_endpoint", lambda **_kwargs: "http://example.test:9222"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["screenshot-crawler", "batch", "run", "--site", "magapoke", "--limit", "3"],
    )

    cli.main()

    output = capsys.readouterr()
    assert plans == [None, "premium_ticket"]
    assert calls == [1, 2, 3]
    assert "item=4" not in output.out
    assert "item=5" not in output.out
    assert "FAILED" not in output.out
    assert "FAILED" not in output.err


def test_grant_only_all_uses_policy_order_replans_and_shares_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plans: list[str | None] = []
    executions: list[tuple[str, int]] = []

    def candidate(resource: str, item_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            item_id=item_id,
            source_id=item_id + 100,
            metadata={},
            access_strategy="quota",
            quota_resource=resource,
        )

    class FakePlanner:
        def __init__(self, *_args: object) -> None:
            pass

        def plan(self, *, site: str, quota_resource: str | None = None) -> object:
            assert site == "magapoke"
            plans.append(quota_resource)
            if quota_resource == "resource_a":
                candidates = [candidate("resource_a", 1), candidate("resource_a", 2)]
            else:
                assert quota_resource == "resource_b"
                candidates = [candidate("resource_b", 3), candidate("resource_b", 4)]
            return SimpleNamespace(candidates=candidates, skipped=[])

    class FakeSession:
        @classmethod
        async def connect(cls, _endpoint: str) -> "FakeSession":
            return cls()

        async def new_page(self) -> object:
            return object()

        async def close_page(self, _page: object) -> None:
            pass

        async def close(self) -> None:
            pass

    class FakeExecutor:
        def __init__(self, *_args: object) -> None:
            pass

        def grant_only_skip_reason(self, _candidate: object, **_kwargs: object) -> None:
            return None

        async def execute_grant_only_candidate(
            self, _page: object, candidate: object, **_kwargs: object
        ) -> object:
            executions.append((candidate.quota_resource, candidate.item_id))
            return SimpleNamespace(
                resource=candidate.quota_resource,
                resource_consumed=True,
                stop_reason="entry_confirmed",
            )

    monkeypatch.setattr(cli, "CatalogService", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "_batch_policy_registry",
        lambda: SimpleNamespace(
            create=lambda _site: SimpleNamespace(
                ordered_access_resource_passes=lambda: ("resource_a", "resource_b"),
                grant_only_supported_access_resources=lambda: (
                    "resource_a", "resource_b"
                ),
            )
        ),
    )
    monkeypatch.setattr(cli, "BatchPlanner", FakePlanner)
    monkeypatch.setattr(cli, "BrowserSession", FakeSession)
    monkeypatch.setattr(cli, "BatchExecutor", FakeExecutor)
    monkeypatch.setattr(cli, "_registry", lambda: object())
    monkeypatch.setattr(
        cli, "resolve_cdp_endpoint", lambda **_kwargs: "http://example.test:9222"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "screenshot-crawler",
            "batch",
            "run",
            "--site",
            "magapoke",
            "--grant-only",
            "all",
            "--limit",
            "3",
        ],
    )

    cli.main()

    output = capsys.readouterr()
    assert plans == ["resource_a", "resource_b"]
    assert executions == [("resource_a", 1), ("resource_a", 2), ("resource_b", 3)]
    assert "resource=all" in output.out
    assert "item=4" not in output.out
    assert "FAILED" not in output.out


def test_grant_only_all_moves_to_next_policy_pass_after_resource_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executions: list[int] = []

    def candidate(resource: str, item_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            item_id=item_id,
            source_id=item_id + 100,
            metadata={},
            access_strategy="quota",
            quota_resource=resource,
        )

    class FakePlanner:
        def __init__(self, *_args: object) -> None:
            pass

        def plan(self, *, site: str, quota_resource: str | None = None) -> object:
            assert site == "magapoke"
            return SimpleNamespace(
                candidates=(
                    [candidate("resource_a", 1)]
                    if quota_resource == "resource_a"
                    else [candidate("resource_b", 2)]
                ),
                skipped=[],
            )

    class FakeSession:
        @classmethod
        async def connect(cls, _endpoint: str) -> "FakeSession":
            return cls()

        async def new_page(self) -> object:
            return object()

        async def close_page(self, _page: object) -> None:
            pass

        async def close(self) -> None:
            pass

    class FakeExecutor:
        def __init__(self, *_args: object) -> None:
            pass

        def grant_only_skip_reason(self, _candidate: object, **_kwargs: object) -> None:
            return None

        async def execute_grant_only_candidate(
            self, _page: object, candidate: object, **_kwargs: object
        ) -> object:
            executions.append(candidate.item_id)
            if candidate.item_id == 1:
                raise cli.AccessResourceUnavailableError(
                    "resource_a_exhausted", stop_resource_pass=True
                )
            return SimpleNamespace(
                resource=candidate.quota_resource,
                resource_consumed=True,
                stop_reason="entry_confirmed",
            )

    monkeypatch.setattr(cli, "CatalogService", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "_batch_policy_registry",
        lambda: SimpleNamespace(
            create=lambda _site: SimpleNamespace(
                ordered_access_resource_passes=lambda: ("resource_a", "resource_b"),
                grant_only_supported_access_resources=lambda: (
                    "resource_a", "resource_b"
                ),
            )
        ),
    )
    monkeypatch.setattr(cli, "BatchPlanner", FakePlanner)
    monkeypatch.setattr(cli, "BrowserSession", FakeSession)
    monkeypatch.setattr(cli, "BatchExecutor", FakeExecutor)
    monkeypatch.setattr(cli, "_registry", lambda: object())
    monkeypatch.setattr(
        cli, "resolve_cdp_endpoint", lambda **_kwargs: "http://example.test:9222"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["screenshot-crawler", "batch", "run", "--site", "magapoke", "--grant-only", "all"],
    )

    cli.main()

    assert executions == [1, 2]


async def test_batch_candidate_delay_runs_after_close_only_between_site_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeSession:
        def __init__(self) -> None:
            self.index = 0

        async def new_page(self) -> object:
            self.index += 1
            page = f"page-{self.index}"
            events.append(f"new:{page}")
            return page

        async def close_page(self, page: object) -> None:
            events.append(f"close:{page}")

    class FakeExecutor:
        async def execute_candidate(
            self, _page: object, candidate: object, **_kwargs: object
        ) -> object:
            events.append(f"execute:{candidate.item_id}")
            return SimpleNamespace(archive_path=Path(f"item-{candidate.item_id}.zip"))

    async def fake_sleep(seconds: float) -> None:
        events.append(f"delay:{seconds}")

    monkeypatch.setattr(cli.asyncio, "sleep", fake_sleep)
    args = SimpleNamespace(
        output_root=Path("output/batch"),
        library_dir=Path("output/Books"),
        max_pages=1000,
        max_same_content=3,
        keep_open=False,
    )
    candidates = [
        SimpleNamespace(
            item_id=1, source_id=11, metadata={}, access_strategy="direct", quota_resource=None
        ),
        SimpleNamespace(
            item_id=2, source_id=22, metadata={}, access_strategy="direct", quota_resource=None
        ),
    ]

    processed, should_continue = await cli._execute_batch_candidates(
        args,
        FakeSession(),
        FakeExecutor(),
        candidates,
        phase="test",
        inter_candidate_delay_ms=17,
    )

    assert (processed, should_continue) == (2, True)
    assert events == [
        "new:page-1",
        "execute:1",
        "close:page-1",
        "delay:0.017",
        "new:page-2",
        "execute:2",
        "close:page-2",
    ]


async def test_candidate_failure_is_recorded_and_batch_stops() -> None:
    events: list[str] = []

    class FakeSession:
        async def new_page(self) -> object:
            page = object()
            events.append("new")
            return page

        async def close_page(self, _page: object) -> None:
            events.append("close")

    class FakeExecutor:
        async def execute_candidate(
            self, _page: object, candidate: object, **_kwargs: object
        ) -> object:
            events.append(f"execute:{candidate.item_id}")
            if candidate.item_id == 1:
                raise cli.CandidateExecutionError("viewer timeout")
            return SimpleNamespace(archive_path=Path("item-2.zip"))

    args = SimpleNamespace(
        output_root=Path("output/batch"),
        library_dir=Path("output/Books"),
        max_pages=1000,
        max_same_content=3,
        keep_open=False,
    )
    candidates = [
        SimpleNamespace(item_id=1, source_id=11, metadata={}, access_strategy="direct", quota_resource=None),
        SimpleNamespace(item_id=2, source_id=22, metadata={}, access_strategy="direct", quota_resource=None),
    ]

    with pytest.raises(cli.CandidateExecutionError, match="viewer timeout"):
        await cli._execute_batch_candidates(
            args,
            FakeSession(),
            FakeExecutor(),
            candidates,
            phase="test",
            inter_candidate_delay_ms=0,
        )

    assert events == ["new", "execute:1", "close"]


async def test_cleanup_cancellation_does_not_replace_candidate_failure() -> None:
    class FakeSession:
        async def new_page(self) -> object:
            return object()

        async def close_page(self, _page: object) -> None:
            raise asyncio.CancelledError()

    class FakeExecutor:
        async def execute_candidate(
            self, _page: object, _candidate: object, **_kwargs: object
        ) -> object:
            raise cli.CandidateExecutionError("viewer timeout")

    args = SimpleNamespace(
        output_root=Path("output/batch"),
        library_dir=Path("output/Books"),
        max_pages=1000,
        max_same_content=3,
        keep_open=False,
    )
    candidate = SimpleNamespace(
        item_id=1, source_id=11, metadata={}, access_strategy="direct", quota_resource=None
    )

    with pytest.raises(cli.CandidateExecutionError, match="viewer timeout"):
        await cli._execute_batch_candidates(
            args,
            FakeSession(),
            FakeExecutor(),
            [candidate],
            phase="test",
            inter_candidate_delay_ms=0,
        )


async def test_batch_interruption_does_not_start_next_candidate() -> None:
    events: list[str] = []

    class FakeSession:
        async def new_page(self) -> object:
            events.append("new")
            return object()

        async def close_page(self, _page: object) -> None:
            events.append("close")

    class FakeExecutor:
        async def execute_candidate(
            self, _page: object, candidate: object, **_kwargs: object
        ) -> object:
            events.append(f"execute:{candidate.item_id}")
            raise cli.BatchInterruptedError("interrupted")

    args = SimpleNamespace(
        output_root=Path("output/batch"),
        library_dir=Path("output/Books"),
        max_pages=1000,
        max_same_content=3,
        keep_open=False,
    )
    candidates = [
        SimpleNamespace(item_id=1, source_id=11, metadata={}, access_strategy="direct", quota_resource=None),
        SimpleNamespace(item_id=2, source_id=22, metadata={}, access_strategy="direct", quota_resource=None),
    ]

    with pytest.raises(cli.BatchInterruptedError):
        await cli._execute_batch_candidates(
            args,
            FakeSession(),
            FakeExecutor(),
            candidates,
            phase="test",
            inter_candidate_delay_ms=0,
        )

    assert events == ["new", "execute:1", "close"]


async def test_batch_empty_candidate_list_has_no_candidate_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_sleep(_seconds: float) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(cli.asyncio, "sleep", fake_sleep)
    args = SimpleNamespace(
        output_root=Path("output/batch"),
        library_dir=Path("output/Books"),
        max_pages=1000,
        max_same_content=3,
        keep_open=False,
    )

    assert await cli._execute_batch_candidates(
        args,
        object(),
        object(),
        [],
        phase="test",
        inter_candidate_delay_ms=17,
    ) == (0, True)
    assert called is False


@pytest.mark.asyncio
async def test_grant_only_local_skip_does_not_open_page_or_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeSession:
        async def new_page(self) -> object:
            events.append("new")
            return object()

        async def close_page(self, _page: object) -> None:
            events.append("close")

    class FakeExecutor:
        def grant_only_skip_reason(self, candidate: object, **_kwargs: object) -> str | None:
            return "work_ticket_cooldown" if candidate.item_id == 1 else None

        async def execute_grant_only_candidate(
            self, _page: object, candidate: object, **_kwargs: object
        ) -> object:
            events.append(f"execute:{candidate.item_id}")
            return SimpleNamespace(
                resource="work_ticket", stop_reason="entry_confirmed", resource_consumed=True
            )

    async def fake_sleep(seconds: float) -> None:
        events.append(f"delay:{seconds}")

    monkeypatch.setattr(cli.asyncio, "sleep", fake_sleep)
    args = SimpleNamespace(
        output_root=Path("output/batch"),
        library_dir=Path("output/Books"),
        max_pages=1000,
        max_same_content=3,
        keep_open=False,
    )
    candidates = [
        SimpleNamespace(item_id=1, source_id=11, metadata={}, access_strategy="quota", quota_resource="work_ticket"),
        SimpleNamespace(item_id=2, source_id=22, metadata={}, access_strategy="quota", quota_resource="work_ticket"),
    ]

    processed, should_continue = await cli._execute_batch_candidates(
        args,
        FakeSession(),
        FakeExecutor(),
        candidates,
        phase="grant-only",
        inter_candidate_delay_ms=17,
        grant_only=True,
    )

    assert (processed, should_continue) == (1, True)
    assert events == ["new", "execute:2", "close"]


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
