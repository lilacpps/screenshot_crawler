from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from screenshot_crawler import cli
from screenshot_crawler.batch import (
    BatchExecutionError,
    BatchExecutor,
    BatchPlanner,
    CandidateExecutionError,
)
from screenshot_crawler.batch.grants import group_grant_candidates
from screenshot_crawler.batch.metrics import BatchMetricsWriter
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.core.errors import AccessResourceUnavailableError, AccessStopError
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_adapters.zeblack.access_resolver import (
    resolve_zeblack_work_ticket_candidates,
)
from screenshot_crawler.site_adapters.zeblack.discovery_protobuf import (
    ConsumptionStatus,
    ZeblackChapterV3,
)
from screenshot_crawler.site_adapters.zeblack.live_access import ZeblackChapterListSnapshot
from screenshot_crawler.site_policies import SitePolicyRegistry, ZeblackSitePolicy
from screenshot_crawler.watchlist.service import WatchlistService


@pytest.mark.parametrize("resource", ["work_ticket", "all", "normal"])
@pytest.mark.parametrize("scenario", [
    "success", "limit", "unavailable", "missing", "local_skip", "entry_unavailable",
    "resolver_failure", "entry_failure", "consumed_failure", "interrupted", "access_stop",
    "multiple_targets", "outside_work",
    "interrupted_wait",
])
async def test_deferred_grant_run_is_sequential_and_reports_each_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    resource: str,
    scenario: str,
) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    catalog = CatalogService(catalog_path)
    watchlist_path = tmp_path / "watchlist.yaml"
    watchlist = WatchlistService(watchlist_path)
    events: list[str] = []
    crawled: list[int] = []
    for work_index in range(1, 4):
        work = catalog.create_work(WorkInput(work_key=f"work-{work_index}", title=f"旧名{work_index}"))
        watchlist.add(
            key=f"target-{work_index}", work_key=work.work_key, site="zeblack",
            url=f"https://zebrack-comic.shueisha.co.jp/title/{work_index}/chapter/list",
            label=f"最新作品{work_index}",
        )
        for chapter_index in range(1, 3):
            external_id = f"{work_index}0{chapter_index}"
            item = catalog.create_item(ItemInput(order_label=f"第{chapter_index}話"), work_id=work.id)
            source = catalog.create_source(
                SourceInput(site="zeblack", external_id=external_id,
                            discovery_key=f"target-{work_index}", access_mode="quota"),
                item_id=item.id,
            )
            catalog.create_source_target(
                SourceTargetInput(backend="web", locator=(
                    f"https://zebrack-comic.shueisha.co.jp/title/{work_index}"
                    f"/chapter/{external_id}/viewer"
                )), source_id=source.id,
            )

    async def sleep(seconds: float) -> None:
        assert seconds == 0.017
        events.append("sleep")
        if scenario == "interrupted_wait" and "grant:1" in events:
            raise asyncio.CancelledError()

    async def observe(_page: object, *, title_id: str, **_kwargs: object) -> object:
        events.append(f"resolve:{title_id}")
        if title_id == "2" and scenario == "resolver_failure":
            raise BatchExecutionError("bounded resolver timeout")
        chapter_id = f"{title_id}02"
        status = ConsumptionStatus.TICKET_AVAILABLE
        if title_id == "2" and scenario == "unavailable":
            status = ConsumptionStatus.TICKET_UNAVAILABLE
        if title_id == "2" and scenario == "missing":
            chapter_id = "9999"
        return ZeblackChapterListSnapshot(title_id=title_id, chapters=(
            ZeblackChapterV3(chapter_id=chapter_id, title_id=title_id, main_name="第2話",
                            remaining_rental_time=None, status_value=int(status), price=None),
        ))

    class Session:
        @classmethod
        async def connect(cls, _endpoint: str) -> Session:
            return cls()

        async def new_page(self) -> object:
            events.append("new")
            return object()

        async def close_page(self, _page: object) -> None:
            events.append("close")

        async def close(self) -> None:
            events.append("disconnect")

    class Executor:
        def __init__(self, *_args: object) -> None:
            pass

        def grant_only_skip_reason(self, candidate: object) -> str | None:
            if candidate.work_id == 2 and scenario == "local_skip":
                return "local_cooldown"
            return None

        async def resolve_access_resource_candidates(
            self, page: object, candidates: list, quota_resource: str
        ) -> object:
            assert quota_resource == "work_ticket"
            assert len(candidates) == 2
            assert len({item.work_id for item in candidates}) == 1
            resolution = await resolve_zeblack_work_ticket_candidates(page, candidates)
            if candidates[0].work_id == 2 and scenario in {"multiple_targets", "outside_work"}:
                return SimpleNamespace(
                    selected_source_ids=(
                        tuple(item.source_id for item in candidates)
                        if scenario == "multiple_targets" else (9999,)
                    ), skipped_source_reasons=(),
                )
            return resolution

        @asynccontextmanager
        async def prepare_access_resource_candidates(self, page, candidates, resource):
            resolution = await self.resolve_access_resource_candidates(page, candidates, resource)
            yield SimpleNamespace(page=page, resolution=resolution)

        async def execute_grant_only_candidate(self, _page: object, candidate: object, **_kwargs: object):
            assert _kwargs["prepared_access"].page is _page
            events.append(f"grant:{candidate.work_id}")
            assert candidate.external_id == f"{candidate.work_id}02"
            # Display labels do not replace packaging metadata or source identity.
            assert candidate.metadata["title"] == f"旧名{candidate.work_id}"
            if candidate.work_id == 2:
                if scenario == "entry_unavailable":
                    raise AccessResourceUnavailableError("resource_unavailable", stop_resource_pass=True)
                if scenario in {"entry_failure", "consumed_failure"}:
                    raise CandidateExecutionError(
                        "viewer/finalization failure",
                        resource_consumed=True if scenario == "consumed_failure" else None,
                    )
                if scenario == "interrupted":
                    raise asyncio.CancelledError()
                if scenario == "access_stop":
                    raise BatchExecutionError("fatal access stop", access_stop=AccessStopError(
                        reason="http_429", site="zeblack", url=candidate.locator, status=429,
                    ))
            if resource == "normal":
                catalog.record_quota_access(
                    candidate.source_id, quota_started_at=datetime.now(UTC),
                    access_granted_until=datetime.now(UTC) + timedelta(hours=71),
                )
            return SimpleNamespace(resource="work_ticket", resource_consumed=True, stop_reason="entry_confirmed")

        async def execute_candidate(self, _page: object, candidate: object, **_kwargs: object):
            assert candidate.access_strategy == "direct"
            events.append(f"crawl:{candidate.work_id}")
            crawled.append(candidate.work_id)
            catalog.mark_item_completed(candidate.item_id)
            return SimpleNamespace(archive_path=Path("fake.zip"), stop_reason="end")

    monkeypatch.setattr(cli, "BrowserSession", Session)
    monkeypatch.setattr(cli, "BatchExecutor", Executor)
    monkeypatch.setattr(cli, "resolve_cdp_endpoint", lambda **_kwargs: "http://example.test:9222")
    monkeypatch.setattr(cli, "BatchMetricsWriter", lambda *_args, **kwargs: BatchMetricsWriter(
        tmp_path / "metrics", **kwargs
    ))
    monkeypatch.setattr(cli, "load_runtime_settings", lambda *_args: SimpleNamespace(
        for_site=lambda _site: SimpleNamespace(inter_candidate_delay_ms=17)
    ))
    monkeypatch.setattr(cli.asyncio, "sleep", sleep)
    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.access_resolver.observe_zeblack_chapter_list", observe
    )
    argv = ["batch", "run", "--site", "zeblack",
            "--catalog", str(catalog_path), "--watchlist", str(watchlist_path),
            "--env-file", str(tmp_path / "missing.env")]
    if resource != "normal":
        argv.extend(["--grant-only", resource])
    elif scenario == "entry_unavailable":
        # A historical consumption timestamp must not trigger post-grant capture
        # when this run did not confirm any consumption for that Work.
        catalog.record_quota_access(
            4, quota_started_at=datetime.now(UTC) - timedelta(days=5),
            access_granted_until=datetime.now(UTC) - timedelta(days=2),
        )
    if scenario == "limit":
        argv.extend(["--limit", "1"])
    args = cli._parser().parse_args(argv)
    fatal = scenario in {
        "resolver_failure", "entry_failure", "consumed_failure", "interrupted", "access_stop",
        "multiple_targets", "outside_work",
        "interrupted_wait",
    }
    if fatal:
        with pytest.raises((BatchExecutionError, cli.BatchPlanningError)):
            await cli._run_batch_run(args)
    else:
        await cli._run_batch_run(args)

    output = capsys.readouterr().out
    if resource == "normal":
        assert "Grant-only results:" not in output
        assert output.count("Grant results:") == 1
        summary = output.split("Grant results:")[1]
        assert "OK  最新作品1  第2話" in summary and "旧名" not in summary
        records = [json.loads(line) for line in next((tmp_path / "metrics").glob("*.jsonl")).read_text(
            encoding="utf-8"
        ).splitlines()]
        results = [record for record in records if record["type"] == "grant_result"]
        assert len(results) == 3 and records[-1]["type"] == "batch_summary"
        assert results[0]["label"] == "最新作品1" and results[0]["resource_consumed"] is True
        first = ["new", "resolve:1", "grant:1", "close"]
        assert events[:len(first)] == first
        assert events[-1] == "disconnect"
        if scenario == "limit":
            assert "resolve:2" not in events and "resolve:3" not in events
            assert crawled == [1]
            assert all(row["status"] == "未実行" and row["reason"] == "limit_reached"
                       and row["source_id"] is None for row in results[1:])
        elif fatal:
            assert "resolve:3" not in events
            assert crawled == []
            expected = (
                "OK" if scenario == "consumed_failure"
                else "未実行" if scenario == "interrupted_wait" else "NG"
            )
            assert results[1]["status"] == expected
            assert results[1]["resource_consumed"] is (True if scenario == "consumed_failure" else None)
            assert results[2]["status"] == "未実行" and results[2]["reason"] == "stopped"
        else:
            if scenario != "local_skip":
                assert events.index("grant:1") < events.index("resolve:2")
            assert events.index("grant:3") < events.index("crawl:1")
            assert crawled == ([1, 2, 3] if scenario == "success" else [1, 3])
            assert results[1]["status"] == (
                "OK" if scenario == "success" else "SKIP" if scenario == "local_skip" else "NG"
            )
            assert results[2]["status"] == "OK"
            if scenario in {"unavailable", "missing", "local_skip"}:
                assert "grant:2" not in events
                assert results[1]["source_id"] is None
        # Each site-accessing Work closes its resolver Page before one pacing
        # delay and the next resolver. Post-grant crawl also starts after a delay.
        for index, event in enumerate(events):
            if event.startswith("resolve:"):
                assert events[index - 1] == "new"
                if event != "resolve:1":
                    assert events[index - 3:index] == ["close", "sleep", "new"]
        if crawled:
            start = events.index("crawl:1")
            assert events[start - 3:start] == ["close", "sleep", "new"]
        assert len([item for item in catalog.list_items() if item.status == "completed"]) == len(crawled)
        return
    assert output.count("Grant-only results:") == 1
    summary = output.split("Grant-only results:")[1]
    assert "OK  最新作品1  第2話" in summary
    assert "旧名" not in summary
    records = [json.loads(line) for line in next((tmp_path / "metrics").glob("*.jsonl")).read_text(
        encoding="utf-8"
    ).splitlines()]
    results = [record for record in records if record["type"] == "grant_result"]
    assert len(results) == 3
    assert records[-1]["type"] == "batch_summary"
    assert results[0]["label"] == "最新作品1"
    assert results[0]["resource_consumed"] is True
    assert events[-1] == "disconnect"
    first = ["new", "resolve:1", "grant:1", "close"]
    assert events[:len(first)] == first
    if scenario == "limit":
        assert events == first + ["disconnect"]
        assert "未実行  最新作品2" in summary and "limit_reached" in summary
        assert results[1]["resource_consumed"] is None
        assert results[1]["source_id"] is None
    else:
        if scenario not in {"local_skip", "interrupted_wait"}:
            assert events[len(first):len(first) + 3] == ["sleep", "new", "resolve:2"]
        if scenario in {"unavailable", "missing", "local_skip"}:
            assert "grant:2" not in events
            assert results[1]["source_id"] is None
            assert "NG  最新作品2  第1話" not in summary
        if fatal:
            assert "resolve:3" not in events
            assert "未実行  最新作品3" in summary and "stopped" in summary
            expected = (
                "OK" if scenario == "consumed_failure"
                else "未実行" if scenario == "interrupted_wait" else "NG"
            )
            assert expected + "  最新作品2" in summary
            if scenario == "interrupted_wait":
                assert "resolve:2" not in events
            assert results[1]["resource_consumed"] is (True if scenario == "consumed_failure" else None)
        else:
            assert "OK  最新作品3" in summary
            if scenario != "local_skip":
                assert events.index("grant:1") < events.index("resolve:2")
            assert events[-6:] == [
                "sleep", "new", "resolve:3", "grant:3", "close", "disconnect"
            ]
            status = "OK" if scenario == "success" else "SKIP" if scenario == "local_skip" else "NG"
            assert status + "  最新作品2" in summary
    assert catalog.list_artifacts() == []
    assert all(item.status == "pending" for item in catalog.list_items())


def test_deferred_grant_grouping_rejects_missing_work_identity() -> None:
    with pytest.raises(cli.BatchPlanningError, match="work_id"):
        group_grant_candidates([SimpleNamespace(work_id=None)])


@pytest.mark.parametrize("mode", ["work_ticket", "all", "normal_resolver"])
async def test_work_cooldown_skips_other_chapters_before_creating_a_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: str,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="work", title="作品"))
    for chapter_id in ("11", "12"):
        item = catalog.create_item(ItemInput(), work_id=work.id)
        source = catalog.create_source(
            SourceInput(site="zeblack", external_id=chapter_id, access_mode="quota",
                        discovery_key="target"), item_id=item.id,
        )
        catalog.create_source_target(SourceTargetInput(backend="web", locator=(
            f"https://zebrack-comic.shueisha.co.jp/title/1/chapter/{chapter_id}/viewer"
        )), source_id=source.id)
    policies = SitePolicyRegistry()
    policies.register("zeblack", ZeblackSitePolicy)
    before = BatchPlanner(catalog, policies).plan(site="zeblack").candidates
    consumed_at = datetime.now(UTC)
    catalog.record_quota_access_with_resource_state(
        before[0].source_id, work_id=work.id, site="zeblack", resource="work_ticket",
        consumed_at=consumed_at, access_granted_until=consumed_at + timedelta(hours=71),
    )
    executor = BatchExecutor(catalog, policies, AdapterRegistry())
    watchlist_path = tmp_path / "watchlist.yaml"
    WatchlistService(watchlist_path).add(
        key="target", work_key="work", site="zeblack",
        url="https://zebrack-comic.shueisha.co.jp/title/1/chapter/list", label="label",
    )

    class Session:
        @classmethod
        async def connect(cls, _endpoint):
            return cls()

        async def new_page(self):
            pytest.fail("Cooldown must not create a site Page")

        async def close(self):
            pass

    monkeypatch.setattr(cli, "BrowserSession", Session)
    monkeypatch.setattr(cli, "BatchExecutor", lambda *_args: executor)
    monkeypatch.setattr(cli, "BatchMetricsWriter", lambda *_args, **kwargs: BatchMetricsWriter(
        tmp_path / "metrics", **kwargs
    ))
    if mode == "normal_resolver":
        remaining = [item for item in BatchPlanner(catalog, policies).plan(site="zeblack").candidates
                     if item.consumes_quota]
        assert await cli._resolve_access_resource_candidates(
            Session(), executor, remaining, resource="work_ticket"
        ) == []
    else:
        args = cli._parser().parse_args([
            "batch", "run", "--site", "zeblack", "--grant-only", mode,
            "--catalog", str(tmp_path / "catalog.sqlite"), "--watchlist", str(watchlist_path),
            "--env-file", str(tmp_path / "missing.env"),
        ])
        await cli._run_batch_run(args)
    output = capsys.readouterr().out
    assert "SKIP" in output and "work_ticket_cooldown" in output and "次回確認可能" in output
    assert executor.grant_only_skip_reason(before[1], now=consumed_at + timedelta(hours=23)) is None


@pytest.mark.parametrize("watchlist_state", ["missing", "reused_key"])
def test_grant_report_falls_back_to_catalog_when_watchlist_identity_does_not_match(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], watchlist_state: str,
) -> None:
    from screenshot_crawler.batch.grants import GrantOnlyReport

    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="original", title="Catalog作品"))
    item = catalog.create_item(ItemInput(), work_id=work.id)
    source = catalog.create_source(
        SourceInput(site="zeblack", external_id="123", discovery_key="target"), item_id=item.id
    )
    watchlist_path = tmp_path / "watchlist.yaml"
    if watchlist_state == "reused_key":
        WatchlistService(watchlist_path).add(
            key="target", work_key="different-work", site="zeblack",
            url="https://example.test", label="別作品名",
        )
    candidate = SimpleNamespace(
        work_id=work.id, source_id=source.id, quota_resource="resource_x", site="zeblack", metadata={}
    )
    metrics = BatchMetricsWriter(tmp_path / "metrics", site="zeblack")
    try:
        report = GrantOnlyReport(catalog, watchlist_path, metrics)
        report.prepare([candidate], "resource_x")
        report.finish(reason="stopped")
    finally:
        metrics.close()
    output = capsys.readouterr().out
    assert "未実行  Catalog作品 [Catalog名]" in output
    assert "別作品名" not in output
