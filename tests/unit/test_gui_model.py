"""Qt-offscreen contract tests for the P1 inventory projection."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QAbstractItemModelTester, QSignalSpy
from PySide6.QtWidgets import QApplication

from screenshot_crawler.gui.model import InventoryTreeModel, StatusFilter, ViewMode
from screenshot_crawler.management.models import (
    InventoryCounts,
    InventorySnapshot,
    InventorySummary,
    KeyInventory,
)
from screenshot_crawler.watchlist.models import WatchlistTarget


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture(autouse=True)
def dispose_qt_windows_on_gui_thread(qt_app):
    """Do not let a later Python worker collect closed QWidget cycles."""
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent
    yield
    for window in qt_app.topLevelWidgets():
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def _snapshot() -> InventorySnapshot:
    keys = []
    summaries = {}
    for number, site in enumerate(("bookwalker", "mangaone"), start=1):
        summary = InventorySummary(
            InventoryCounts(total_assigned=number + 2, completed=number - 1, direct=1, quota=1, paid=1),
            "synced",
            (),
            "2026-10-23T10:00:00+09:00",
            (f"wk-{number}",),
            (number,),
        )
        key = KeyInventory(
            f"wk-{number}",
            WatchlistTarget(f"wk-{number}", "same-work", site, "https://example.invalid", f"Key {number}", archive_order=number),
            "same-work",
            site,
            "同じ作品",
            f"Key {number}",
            summary,
        )
        keys.append(key)
        summaries[("site", site)] = summary
        summaries[("pair", site, "same-work")] = summary
    summaries[("work", "same-work")] = InventorySummary(
        InventoryCounts(total_assigned=7, completed=1, direct=2, quota=2, paid=2),
        "synced",
        (),
        None,
        ("wk-1", "wk-2"),
        (1, 2),
    )
    return InventorySnapshot(
        loaded_at=datetime.now(UTC),
        catalog_path="catalog.sqlite",
        watchlist_path="watchlist.yaml",
        keys=tuple(keys),
        summaries=summaries,
        items={},
        sources={},
        source_targets={},
        classifications={},
        latest_runs={},
        artifacts={},
        archive_positions={},
        resources={},
        grants=(),
        load_seconds=0.01,
    )


def test_same_work_is_projected_both_ways_and_selection_survives(qt_app):
    model = InventoryTreeModel(_snapshot())
    assert model.rowCount() == 2
    model.set_view_mode(ViewMode.WORK)
    assert model.rowCount() == 1
    work = model.index(0, 0)
    assert model.rowCount(work) == 2
    model.setData(work, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.checked_keys == {"wk-1", "wk-2"}
    model.set_search("mangaone")
    assert model.checked_keys == {"wk-1", "wk-2"}
    model.set_search("")
    model.set_view_mode(ViewMode.SITE)
    assert model.checked_keys == {"wk-1", "wk-2"}


def test_parent_tri_state_and_filter_keep_hidden_selection(qt_app):
    model = InventoryTreeModel(_snapshot())
    site = model.index(0, 0)
    work = model.index(0, 0, site)
    key = model.index(0, 0, work)
    model.setData(key, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.check_state(work) == Qt.CheckState.Checked
    other_site = model.index(1, 0)
    other_work = model.index(0, 0, other_site)
    model.setData(other_work, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.checked_keys == {"wk-1", "wk-2"}
    model.set_search("does-not-exist")
    assert model.rowCount() == 0
    assert model.checked_keys == {"wk-1", "wk-2"}


def test_numeric_columns_and_stale_counts_are_safe(qt_app):
    snapshot = _snapshot()
    stale = snapshot.keys[0]
    stale_summary = InventorySummary(
        InventoryCounts(total_assigned=2, completed=1, direct=1), "stale", ("missing proof",), None, stale.summary.key_ids, stale.summary.source_ids
    )
    snapshot = replace(
        snapshot,
        keys=(KeyInventory(stale.identity, stale.target, stale.work_key, stale.site, stale.title, stale.label, stale_summary), snapshot.keys[1]),
        summaries={**snapshot.summaries, ("site", stale.site): stale_summary},
    )
    model = InventoryTreeModel(snapshot)
    assert "~" in model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole)
    model.sort(2, Qt.SortOrder.DescendingOrder)
    assert model.rowCount() == 2


def test_qt_model_contract(qt_app):
    model = InventoryTreeModel(_snapshot())
    tester = QAbstractItemModelTester(model, QAbstractItemModelTester.FailureReportingMode.Warning)
    assert tester is not None
    assert model.rowCount(model.index(0, 1)) == 0
    assert not model.index(0, 0, model.index(0, 1)).isValid()


def test_check_selection_emits_valid_signal(qt_app):
    model = InventoryTreeModel(_snapshot())
    spy = QSignalSpy(model.checkedKeysChanged)
    model.setData(model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert spy.count() == 1
    assert set(spy.at(0)[0])


@pytest.mark.parametrize("field", ["external", "skipped"])
def test_terminal_external_or_skipped_is_not_unfinished(qt_app, field):
    counts = InventoryCounts(total_assigned=2, **{field: 2})
    summary = InventorySummary(counts, "synced", (), None, ("k",), (1,))
    key = KeyInventory("k", WatchlistTarget("k", "w", "site", "u", "k"), "w", "site", "w", "k", summary)
    snapshot = replace(
        _snapshot(),
        keys=(key,),
        summaries={("site", "site"): summary, ("work", "w"): summary, ("pair", "site", "w"): summary},
    )
    model = InventoryTreeModel(snapshot)
    model.set_status_filter(StatusFilter.UNFINISHED)
    assert model.rowCount() == 0


def _multi_key_snapshot():
    snapshot = _snapshot()
    first, second = snapshot.keys
    third_summary = replace(
        first.summary, key_ids=("wk-3",), counts=InventoryCounts(total_assigned=10, direct=10)
    )
    third = replace(
        first, identity="wk-3", label="最初に並ばないラベル", summary=third_summary,
        target=replace(first.target, key="wk-3", label="最初に並ばないラベル", archive_order=None),
    )
    first = replace(
        first, target=replace(first.target, archive_order=None),
        summary=replace(first.summary, counts=InventoryCounts(total_assigned=2, direct=2)),
    )
    second = replace(second, target=replace(second.target, archive_order=None))
    return replace(snapshot, keys=(third, first, second))


def test_partial_parent_hidden_descendants_and_file_order(qt_app):
    model = InventoryTreeModel(_multi_key_snapshot())
    model.set_view_mode(ViewMode.WORK)
    work = model.index(0, 0)
    site = model.index(0, 0, work)
    assert [model.node_for_index(model.index(row, 0, site)).key_identity
            for row in range(model.rowCount(site))] == ["wk-3", "wk-1"]
    key = model.node_by_key_identity("wk-1")
    model.setData(model.index_for_node(key.node_id), Qt.CheckState.Checked,
                  Qt.ItemDataRole.CheckStateRole)
    assert model.check_state(work) == Qt.CheckState.PartiallyChecked
    model.set_search("wk-1")
    assert model.checked_keys == {"wk-1"}
    model.setData(model.index_for_node("work:same-work"), Qt.CheckState.Checked,
                  Qt.ItemDataRole.CheckStateRole)
    assert model.checked_keys == {"wk-1", "wk-2", "wk-3"}
    model.set_search("")
    assert model.check_state(model.index(0, 0)) == Qt.CheckState.Checked
    model.set_view_mode(ViewMode.SITE)
    assert model.checked_keys == {"wk-1", "wk-2", "wk-3"}


def test_numeric_2_before_10_and_focus_cleanup(qt_app):
    snapshot = _multi_key_snapshot()
    model = InventoryTreeModel(snapshot)
    first = model.node_by_key_identity("wk-1")
    model.focus_node(first)
    model.set_checked_keys({"wk-1"})
    model.sort(2, Qt.SortOrder.AscendingOrder)
    site = model.index(0, 0)
    work = model.index(0, 0, site)
    assert [model.node_for_index(model.index(row, 0, work)).key_identity
            for row in range(model.rowCount(work))] == ["wk-1", "wk-3"]
    assert model.focused_node_id == first.node_id
    removed = QSignalSpy(model.selectionRemoved)
    model.set_snapshot(replace(snapshot, keys=tuple(k for k in snapshot.keys if k.identity != "wk-1")))
    assert model.focused_node_id is None
    assert model.checked_keys == set()
    assert removed.count() == 1 and set(removed.at(0)[0]) == {"wk-1"}


def test_work_child_site_counts_are_pair_counts(qt_app, tmp_path):
    from screenshot_crawler.management.inventory import InventoryService
    from tools.gui_sample import create_sample
    inputs = create_sample(tmp_path / "sample")
    snapshot = InventoryService().load(*inputs, runtime_path="missing-runtime")
    model = InventoryTreeModel(snapshot)
    model.set_view_mode(ViewMode.WORK)
    for work in model.root.children:
        for site in work.children:
            assert model.summary_for(site) == snapshot.summaries[("pair", site.site, work.work_key)]


def test_mouse_checkbox_is_independent_of_detail_and_sort_focus(qt_app):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

    from screenshot_crawler.gui.main_window import MainWindow

    window = MainWindow("unused", "unused", auto_load=False)
    window.set_snapshot(_multi_key_snapshot())
    window.mode_combo.setCurrentIndex(1)
    window.show()
    window.tree.expandAll()
    qt_app.processEvents()
    model, tree = window.model, window.tree
    first, other = model.node_by_key_identity("wk-1"), model.node_by_key_identity("wk-3")
    model.focus_node(first)
    tree.setCurrentIndex(model.index_for_node(first.node_id))
    other_index = model.index_for_node(other.node_id)
    option = QStyleOptionViewItem()
    tree.itemDelegate().initStyleOption(option, other_index)
    option.rect = tree.visualRect(other_index)
    check_rect = tree.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, tree)
    assert check_rect.isValid()
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, check_rect.center())
    assert model.checked_keys == {"wk-3"}
    assert model.focused_node_id == first.node_id
    assert window.detail.current_key.identity == "wk-1"
    rect = tree.visualRect(other_index)
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(rect.right() - 5, rect.center().y()))
    assert model.focused_node_id == other.node_id
    assert model.checked_keys == {"wk-3"}
    header = tree.header()
    QTest.mouseClick(
        header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        QPoint(header.sectionViewportPosition(2) + header.sectionSize(2) // 2, 10),
    )
    assert model.node_for_index(tree.currentIndex()).key_identity == "wk-3"
    assert window.detail.current_key.identity == "wk-3"
    window.mode_combo.setCurrentIndex(0)
    assert model.node_for_index(tree.currentIndex()).key_identity == "wk-3"
    window.close()

