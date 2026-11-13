"""Qt worker/UI and real Chromium metadata contracts, synthetic inputs only."""

import json
from time import monotonic

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from screenshot_crawler.gui.catalog_repair import CatalogRepairDialog
from screenshot_crawler.maintenance.hanayume_repair import IdentityObservation, load_analysis
from screenshot_crawler.site_adapters.hanayume.repair_probe import (
    METADATA_DOCUMENT,
    ProbeLimits,
    ProbeResult,
    probe_identities,
)


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def wait(app, predicate):
    deadline = monotonic() + 15
    while monotonic() < deadline and not predicate():
        app.processEvents()
        QTest.qWait(10)
    assert predicate()


@pytest.fixture
def dialog(hanayume_repair_inputs, qt_app):
    x = hanayume_repair_inputs
    view = CatalogRepairDialog(x.catalog.path, x.watchlist)
    view.show()
    wait(qt_app, lambda: view.analysis is not None and view.task is None)
    yield view
    wait(qt_app, lambda: view.task is None)
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_compare_manual_annotation_clear_and_export(dialog, hanayume_repair_inputs, qt_app, monkeypatch, tmp_path):
    x, d = hanayume_repair_inputs, dialog
    paths = [x.catalog.path, x.watchlist, x.archive]
    before = [p.read_bytes() for p in paths]
    assert d.old_table.rowCount() == d.new_table.rowCount() == 1
    assert d.old_table.item(0, 4).text() == "completed"
    assert d.new_table.item(0, 4).text() == "pending"
    assert "2 ZIP / 2 Run" in d.old_table.item(0, 5).text()
    before_links = d.analysis.links
    d.edit_buttons[0].click()
    assert "指定できませんでした" in d.edit_feedback.text()
    assert d.analysis.links == before_links
    for decision in ("mapped", "hold", "reacquire"):
        d.old_table.selectRow(0)
        d.new_table.selectRow(0)
        d.reason.setText("" if decision == "mapped" else "目視確認用メモ")
        d.edit_buttons[("mapped", "hold", "reacquire").index(decision)].click()
        assert d.analysis.links[0].decision == decision
        assert "反映しました" in d.edit_feedback.text()
        assert [i.row() for i in d.links.selectionModel().selectedRows()] == [0]
    d.links.selectRow(0)
    assert d.selected_ids(d.old_table) == (x.old.id,)
    assert "手動note" in d.details.toPlainText()
    out = tmp_path / "review.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(out), "JSON"))
    d.save_button.click()
    wait(qt_app, lambda: d.task is None)
    report = json.loads(out.read_text("utf-8"))
    assert report["analysis"]["links"][0]["decision"] == "reacquire"
    d.save_button.click()
    wait(qt_app, lambda: d.task is None)
    assert "解析できませんでした" in d.status.text()
    d.links.selectRow(0)
    d.unlink_button.click()
    assert not d.analysis.links
    d.search.setText("no-matching-source")
    assert d.old_table.rowCount() == d.new_table.rowCount() == 0
    d.search.clear()
    assert d.old_table.rowCount() == 1
    assert [p.read_bytes() for p in paths] == before


def test_split_selection_and_probe_result(dialog, hanayume_repair_inputs, qt_app, monkeypatch):
    x, d = hanayume_repair_inputs, dialog
    source, _, _ = x.add(102, "第1話②", available=True)
    d.load_work()
    wait(qt_app, lambda: d.task is None)
    d.old_table.selectRow(0)
    d._select_row(d.new_table, 0)
    d._select_row(d.new_table, 1)
    d.reason.setText("分割候補")
    d.edit_link("hold")
    assert d.analysis.links[0].shape == "1対2"
    d.links.selectRow(0)
    assert set(d.selected_ids(d.new_table)) == {x.new.id, source.id}
    seen = []

    async def fake_probe(analysis, limits, cancelled, progress):
        seen.append(limits)
        progress("fake progress")
        return ProbeResult((IdentityObservation(x.old.id, x.new.id, "strict API", 42),), 2, 1, 1, "完了")

    monkeypatch.setattr("screenshot_crawler.gui.catalog_repair._probe", fake_probe)
    d.api_button.click()
    wait(qt_app, lambda: d.task is None)
    assert seen[0].max_old_ids == 100 and seen[0].interval == 2
    assert d.offset.value() == 1
    assert d.analysis.links[0].decision == "hold"  # manual intent wins
    assert d.analysis.observations


def test_busy_close_and_failure_recovery(dialog, monkeypatch):
    tasks = []
    monkeypatch.setattr(QThreadPool, "start", lambda self, task: tasks.append(task))
    dialog.api_button.click()
    assert tasks and not dialog.load_button.isEnabled()
    assert not dialog.close() and dialog.cancelled.is_set()
    dialog.failed("endpoint unavailable")
    assert dialog.api_button.isEnabled() and dialog.analysis is not None
    assert "endpoint unavailable" in dialog.status.text()


@pytest.mark.parametrize("label", ["第4話", "其ノ四", "#4.5", "♭004", "episode.04"])
def test_full_part_labels_display_as_three_separate_guesses(dialog, hanayume_repair_inputs, qt_app, label):
    x, d = hanayume_repair_inputs, dialog
    x.catalog.update_item_metadata(x.old.item_id, order_label=f"{label}①")
    x.catalog.update_item_metadata(x.new.item_id, order_label=f"{label}①")
    for number, part in ((2, "②"), (3, "③")):
        x.add(number, f"{label}{part}", available=False)
        x.add(number + 100, f"{label}{part}", available=True)
    d.load_work()
    wait(qt_app, lambda: d.task is None)
    assert d.links.rowCount() == 3
    for row in range(3):
        assert d.links.item(row, 0).text() == "1対1"
        assert "ラベル一致で1対1推測" in d.links.item(row, 1).text()
        d.links.selectRow(row)
        assert len(d.selected_ids(d.old_table)) == len(d.selected_ids(d.new_table)) == 1
    assert "ラベル・話番号で1対1推測: 3" in d.summary_label.text()


def test_manual_result_scrolls_to_selected_group(dialog, hanayume_repair_inputs, qt_app):
    x, d = hanayume_repair_inputs, dialog
    for episode in range(2, 32):
        x.add(episode, f"第{episode}話", available=False)
        x.add(episode + 100, f"第{episode}話", available=True)
    d.load_work()
    wait(qt_app, lambda: d.task is None)
    d.links.scrollToTop()
    d.old_table.selectRow(0)
    d.new_table.selectRow(0)
    assert not d.reason.text()
    d.edit_buttons[0].click()
    row = d.links.rowCount() - 1
    assert d.analysis.links[row].decision == "mapped"
    assert "手動指定 / 対応メモ" in d.links.item(row, 1).text()
    assert [i.row() for i in d.links.selectionModel().selectedRows()] == [row]
    assert d.links.viewport().rect().intersects(d.links.visualItemRect(d.links.item(row, 0)))
    assert d.selected_ids(d.old_table) == (x.old.id,)
    assert d.selected_ids(d.new_table) == (x.new.id,)


@pytest.mark.parametrize("fault", [None, "new_index", "429"])
async def test_real_browser_metadata_fetch_and_network_allowlist(hanayume_repair_inputs, fault):
    from playwright.async_api import async_playwright

    x = hanayume_repair_inputs
    analysis = load_analysis(x.catalog.path, x.watchlist, x.work.work_key)
    calls, aborts = [], []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()

            class SyntheticTransport:
                @property
                def url(self):
                    return page.url

                async def route(self, pattern, guard):
                    async def handle(actual):
                        class GuardedRoute:
                            request = actual.request

                            async def abort(self):
                                aborts.append(actual.request.url)
                                await actual.abort()

                            async def continue_(self):
                                url = actual.request.url
                                calls.append(url)
                                if url == METADATA_DOCUMENT:
                                    await actual.fulfill(body="User-agent: *\n", content_type="text/plain")
                                    return
                                eid = f"{101:013x}"
                                index = 43 if fault == "new_index" and url.endswith(eid) else 42
                                payload = {"episode": {"id": eid, "indexId": index,
                                    "series": {"id": x.native_work}, "access": {"episodeId": eid},
                                    "summary": {"id": eid, "indexId": index}}}
                                await actual.fulfill(status=429 if fault == "429" else 200,
                                    json=payload)
                        await guard(GuardedRoute())
                    await page.route(pattern, handle)

                async def goto(self, *args, **kwargs):
                    return await page.goto(*args, **kwargs)

                async def evaluate(self, *args):
                    return await page.evaluate(*args)

            result = await probe_identities(SyntheticTransport(), analysis, ProbeLimits(interval=0.5))
            assert len([o for o in result.observations if o.new_source_id]) == (1 if fault is None else 0)
            assert result.requests == (1 if fault == "429" else 2)
            await page.evaluate("""async () => {
                await fetch('/api/checkout/rental', {method:'POST'}).catch(() => {});
                await fetch('/episodes/0000000000001').catch(() => {});
            }""")
            assert len(aborts) == 2
            assert calls[0] == METADATA_DOCUMENT
            assert all('/api/episodes/' in url for url in calls[1:])
        finally:
            await browser.close()
