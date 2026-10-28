"""Isolated GUI E2E for replacing Magapoke episodes with Comic DAYS rows."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QDialog

from screenshot_crawler.archive_order import build_work_archive_position_plan
from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.discovery import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryAdapter,
    DiscoveryAdapterRegistry,
    DiscoveryIncompleteError,
    DiscoveryService,
)
from screenshot_crawler.discovery.listing import ListingPreview, ListingRow, listing_digest
from screenshot_crawler.gui.work_editor import WorkEditorDialog
from screenshot_crawler.site_adapters.comicdays.discovery import ComicDaysDiscoveryAdapter
from screenshot_crawler.site_policies import SitePolicyRegistry
from screenshot_crawler.site_policies.comicdays import ComicDaysSitePolicy
from screenshot_crawler.site_policies.magapoke import MagapokeSitePolicy
from screenshot_crawler.watchlist import WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService


class _Page:
    """A page-shaped object; both test adapters use synthetic listing loaders."""

    url = "https://example.invalid/synthetic"


class _Session:
    async def new_page(self):
        return _Page()

    async def close_page(self, _page):
        return None

    async def close(self):
        return None


def _records(site: str, *, count: int, ids: tuple[str, ...], url_prefix: str):
    return [
        DiscoveredRecord(
            item=DiscoveredItem(
                canonical_title="Synthetic Planetes",
                kind="episode",
                order_label=f"第{index + 1}話",
            ),
            source=DiscoveredSource(
                external_id=external_id,
                url=f"{url_prefix}{external_id}",
                access_mode="free",
                available=True,
                global_display_position=count - index,
            ),
        )
        for index, external_id in enumerate(ids)
    ]


class _FixedMagapokeDiscovery(DiscoveryAdapter):
    """Fixed complete listing with the same exclusion replay contract as Magapoke."""

    supports_bounded_discovery = True
    supports_exclusion_only_scope = True
    supports_exclusion_replay = True

    def __init__(self, records: list[DiscoveredRecord]):
        self.records = tuple(records)
        self.prepared = None

    def _preview(self, target: WatchlistTarget) -> ListingPreview:
        identity = "magapoke-title:synthetic"
        rows = tuple(
            ListingRow(
                external_id=record.source.external_id,
                url=record.source.url,
                site_position=record.source.global_display_position or 0,
                display_title=record.item.order_label or "",
                access_observation=record.source.access_mode,
                listing_identity=identity,
            )
            for record in self.records
        )
        return ListingPreview(
            site=target.site,
            target_key=target.key,
            target_url=target.url,
            listing_identity=identity,
            rows=rows,
            complete=True,
            observed_at=datetime.now(UTC),
            digest=listing_digest(identity, rows),
        )

    def _selected(self, target: WatchlistTarget) -> tuple[DiscoveredRecord, ...]:
        scope = target.discovery_scope
        if scope is None:
            return self.records
        ids = [record.source.external_id for record in self.records]
        urls = [record.source.url for record in self.records]
        first = urls.index(scope.from_url) if scope.from_url else 0
        last = urls.index(scope.through_url) if scope.through_url else len(ids) - 1
        if first > last:
            raise DiscoveryIncompleteError("fixed Magapoke scope boundaries were reversed")
        selected = self.records[first:last + 1]
        selected_ids = {record.source.external_id for record in selected}
        if not set(scope.excluded_external_ids).issubset(selected_ids):
            raise DiscoveryIncompleteError("fixed Magapoke exclusion was outside the scope")
        excluded = set(scope.excluded_external_ids)
        return tuple(record for record in selected if record.source.external_id not in excluded)

    async def preview_complete_listing(self, _page, target):
        return self._preview(target)

    async def prepare_exclusion_preview(self, _page, target):
        preview = self._preview(target)
        self._selected(target)  # Validate the same complete observation before replay.
        self.prepared = (target.key, target.discovery_scope, self.records)
        return preview

    async def iter_records(self, _page, target, mode):
        if target.discovery_scope and target.discovery_scope.excluded_external_ids:
            expected = (target.key, target.discovery_scope, self.records)
            if self.prepared != expected:
                raise DiscoveryIncompleteError("fixed Magapoke exclusion replay was not prepared")
            self.prepared = None
        selected = self._selected(target)
        if mode == "full":
            self.capture_complete_listing_inventory(
                target=target,
                all_records=list(self.records),
                selected_records=list(selected),
                listing_identity="magapoke-title:synthetic",
            )
        for record in selected:
            yield record


@pytest.fixture
def app(monkeypatch):
    from screenshot_crawler.core.browser import BrowserSession

    async def fake_connect(*_args, **_kwargs):
        return _Session()

    monkeypatch.setattr(BrowserSession, "connect", fake_connect)
    monkeypatch.setattr(
        "screenshot_crawler.core.browser.resolve_cdp_endpoint",
        lambda **_kwargs: "synthetic-cdp",
    )
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, WorkEditorDialog):
            widget.pool.waitForDone(10_000)
            instance.processEvents()
            widget.dirty = False
            widget.set_active_job(False)
            widget.close()
            widget.deleteLater()


def _wait_for(app: QApplication, predicate) -> None:
    deadline = time.monotonic() + 15
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


@pytest.mark.usefixtures("app")
def test_comicdays_replacement_isolated_gui_full_and_batch(app, tmp_path, monkeypatch):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    catalog.initialize()
    watchlist_path = tmp_path / "watchlist.yaml"
    watchlist_path.write_text("targets: []\n", encoding="utf-8")
    runtime_path = tmp_path / "runtime.yaml"
    runtime_path.write_text("{}\n", encoding="utf-8")
    archive = tmp_path / "existing.zip"
    archive.write_bytes(b"synthetic zip bytes")

    work = catalog.create_work(WorkInput(work_key="work", title="Synthetic Planetes"))
    mag_ids = tuple(str(number) for number in range(1, 27))
    mag_records = _records(
        "magapoke", count=26, ids=tuple(reversed(mag_ids)),
        url_prefix="https://pocket.shonenmagazine.com/title/123/episode/",
    )
    for number in range(1, 27):
        item = catalog.create_item(
            ItemInput(item_title=f"Magapoke {number}", kind="episode", order_label=f"第{number}話"),
            work_id=work.id,
        )
        source = catalog.create_source(
            SourceInput(
                site="magapoke", external_id=str(number), discovery_key="mag",
                access_mode="free", available=True, display_position=number,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(backend="web", locator=mag_records[26 - number].source.url),
            source_id=source.id,
        )
    history_source = catalog.find_source("magapoke", "26")
    assert history_source is not None
    history_target = catalog.list_source_targets(source_id=history_source.id)[0]
    history_run = catalog.create_crawl_run(
        item_id=history_source.item_id,
        source_id=history_source.id,
        target_id=history_target.id,
        access_strategy="direct",
    )
    before_source_ids = {
        (source.site, source.external_id): source.id for source in catalog.list_sources()
    }
    before_history_ids = [run.id for run in catalog.list_crawl_runs()]
    before_catalog = catalog.path.read_bytes()
    before_archive = archive.read_bytes()

    mag_target = WatchlistTarget(
        key="mag", work_key="work", site="magapoke",
        url="https://pocket.shonenmagazine.com/title/123/episode/26", label="Synthetic Planetes",
    )
    WatchlistService(watchlist_path).apply_edit((mag_target,))

    comic_ids = tuple(str(2000 + number) for number in range(1, 28))
    comic_records = _records(
        "comicdays", count=27, ids=tuple(reversed(comic_ids)),
        url_prefix="https://comic-days.com/episode/",
    )
    comic_adapter = ComicDaysDiscoveryAdapter()

    async def synthetic_comic_listing(_page, _target):
        return "series-synthetic", list(comic_records)

    monkeypatch.setattr(comic_adapter, "_load_complete_records", synthetic_comic_listing)
    mag_adapter = _FixedMagapokeDiscovery(mag_records)
    registry = DiscoveryAdapterRegistry()
    registry.register("magapoke", lambda: mag_adapter)
    registry.register("comicdays", lambda: comic_adapter)
    monkeypatch.setattr("screenshot_crawler.cli._discovery_registry", lambda: registry)

    editor = WorkEditorDialog(watchlist_path, catalog.path, runtime_path)
    editor.show()
    app.processEvents()

    from screenshot_crawler.gui.watchlist_editor import AddWatchlistKeyDialog

    def accept_new_site(dialog):
        dialog.key_edit.setText("comic")
        dialog.site_edit.setText("comicdays")
        dialog.url_edit.setText("https://comic-days.com/episode/2024")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(AddWatchlistKeyDialog, "exec", accept_new_site)
    assert editor.add_target()
    editor.fetch_listings()
    _wait_for(app, lambda: editor.task is None and not editor.fetch_queue)
    assert set(editor.draft.listings) == {"mag", "comic"}
    assert len(editor.draft.listings["comic"].rows) == 27

    editor.change(
        lambda: editor.draft.replace_range("mag", "24", "25", "comic", "2024", "2025")
    )
    requested = []
    editor.fullRequested.connect(requested.append)
    editor.preview_edit()
    _wait_for(app, lambda: editor.task is None)
    assert editor.preview is not None, editor.status.toPlainText()

    assert catalog.path.read_bytes() == before_catalog
    assert archive.read_bytes() == before_archive
    assert catalog.find_source("comicdays", "2024") is None

    editor.save_edit()
    _wait_for(app, lambda: editor.task is None)
    assert requested and set(requested[0][0]) == {"mag", "comic"}
    assert catalog.path.read_bytes() == before_catalog
    assert archive.read_bytes() == before_archive
    assert [run.id for run in catalog.list_crawl_runs()] == before_history_ids
    assert {
        (source.site, source.external_id): source.id for source in catalog.list_sources()
    } == before_source_ids

    saved = {target.key: target for target in WatchlistService(watchlist_path).list_targets()}
    comic_preview = awaitable_result(
        comic_adapter.preview_complete_listing(_Page(), saved["comic"])
    )
    assert len(comic_preview.rows) == 27

    discovery = DiscoveryService(catalog, registry)
    mag_result = asyncio.run(discovery.discover(_Page(), saved["mag"], "full"))
    comic_result = asyncio.run(discovery.discover(_Page(), saved["comic"], "full"))
    assert mag_result.complete is True
    assert mag_result.observed_count == 24
    assert comic_result.complete is True
    assert comic_result.observed_count == 2

    final_sources = catalog.list_sources()
    mag_source = {source.external_id: source for source in final_sources if source.site == "magapoke"}
    comic_source = {source.external_id: source for source in final_sources if source.site == "comicdays"}
    assert len(mag_source) == 26
    assert {key for key, source in mag_source.items() if source.acquisition_enabled} == {
        str(number) for number in range(1, 24)
    } | {"26"}
    assert set(comic_source) == {"2024", "2025"}
    assert all(source.acquisition_enabled for source in comic_source.values())

    plan = build_work_archive_position_plan(
        work,
        tuple(saved.values()),
        catalog.list_items(work_id=work.id),
        final_sources,
        provisional=True,
    )
    assert plan is not None
    ordered = [catalog.get_source(source_id) for source_id in plan.ordered_source_ids]
    assert [(source.site, source.external_id) for source in ordered[-3:]] == [
        ("comicdays", "2024"),
        ("comicdays", "2025"),
        ("magapoke", "26"),
    ]

    policies = SitePolicyRegistry()
    policies.register("magapoke", MagapokeSitePolicy)
    policies.register("comicdays", ComicDaysSitePolicy)
    planner = BatchPlanner(catalog, policies, watchlist=WatchlistService(watchlist_path))
    assert len(planner.plan(site="magapoke").candidates) == 24
    assert len(planner.plan(site="comicdays").candidates) == 2
    final_mag_source_ids = {
        (source.site, source.external_id): source.id
        for source in catalog.list_sources()
        if source.site == "magapoke"
    }
    assert final_mag_source_ids == before_source_ids
    assert history_run.id in {run.id for run in catalog.list_crawl_runs()}
    assert archive.read_bytes() == before_archive


def awaitable_result(awaitable):
    return asyncio.run(awaitable)
