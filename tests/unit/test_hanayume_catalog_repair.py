"""Repair analysis, identity API budgets, and immutable local inputs."""

import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest
import yaml

from screenshot_crawler.batch.planner import BatchPlanner
from screenshot_crawler.catalog import CatalogService, WorkInput
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.maintenance.hanayume_repair import (
    IdentityObservation,
    annotate,
    export_report,
    list_repair_works,
    load_analysis,
    unlink,
    validate_pair,
    with_observations,
)
from screenshot_crawler.management.catalog_reader import CatalogInventoryReader, InventoryLoadError
from screenshot_crawler.management.inventory import default_policy_registry
from screenshot_crawler.site_adapters.hanayume.repair_probe import (
    METADATA_DOCUMENT,
    ProbeLimits,
    probe_identities,
)
from screenshot_crawler.watchlist.service import WatchlistService


def load(inputs):
    return load_analysis(inputs.catalog.path, inputs.watchlist, inputs.work.work_key)


def test_complete_history_completed_new_and_zero_writes(hanayume_repair_inputs, monkeypatch, tmp_path):
    inputs = hanayume_repair_inputs
    inputs.history(inputs.new, inputs.new_target)
    inputs.catalog.set_item_status(inputs.new.item_id, "completed")
    paths = [inputs.catalog.path, inputs.watchlist, inputs.archive]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    normal = CatalogInventoryReader().read(inputs.catalog.path)
    assert len(normal.latest_runs) == len(normal.artifacts) == 2
    full = CatalogInventoryReader().read(inputs.catalog.path, include_history=True)
    assert len(full.latest_runs) == len(full.artifacts) == 4
    monkeypatch.setattr(CatalogService, "__init__", lambda *a, **k: pytest.fail("write-capable service"))
    analysis = load(inputs)
    assert analysis.old[0].item.item_title == "手動タイトル"
    assert analysis.old[0].item.note == "手動note"
    assert analysis.old[0].item.status == analysis.current[0].item.status == "completed"
    assert len(analysis.old[0].runs) == analysis.old[0].zip_count == 2
    assert len(analysis.current[0].runs) == 2
    assert analysis.summary()["新旧ZIP記録あり（旧Source数）"] == 1
    assert analysis.summary()["本文同一性証明済み"] == 0
    edited = annotate(analysis, (inputs.old.id,), (inputs.new.id,), "mapped", "人間の確認用メモ")
    assert edited.links[0].evidence == "manual"
    assert not unlink(edited, (0,)).links
    out = tmp_path / "report.json"
    export_report(edited, out)
    assert json.loads(out.read_text("utf-8"))["body_equality_proven"] is False
    with pytest.raises(FileExistsError):
        export_report(analysis, out)
    for path in paths:
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before[path]


@pytest.mark.parametrize("shape", ["split", "merge", "multiple_old_sources"])
def test_manual_shapes_do_not_complete_pending(hanayume_repair_inputs, shape):
    x = hanayume_repair_inputs
    old_ids, new_ids = [x.old.id], [x.new.id]
    if shape == "split":
        x.catalog.update_item_metadata(x.new.item_id, order_label="第1話①")
        source, _, _ = x.add(102, "第1話②", available=True)
        new_ids.append(source.id)
    else:
        if shape == "merge":
            x.catalog.update_item_metadata(x.old.item_id, order_label="第1話①")
        source, _, _ = x.add(2, "第1話②", available=False,
                              item=x.old_item if shape == "multiple_old_sources" else None)
        old_ids.append(source.id)
    analysis = load(x)
    assert any(len(l.old_ids) > 1 or len(l.new_ids) > 1 for l in analysis.links)
    for decision in ("mapped", "hold", "reacquire"):
        result = annotate(analysis, tuple(old_ids), tuple(new_ids), decision, "確認中")
        assert result.links[0].shape == ("1対2" if shape == "split" else "2対1")
        assert all(e.item.status == "pending" for e in result.current)
        assert result.summary()["本文同一性証明済み"] == 0


@pytest.mark.parametrize("fault", ["wrong_work", "wrong_key", "native_work", "url", "site", "same_side"])
def test_invalid_correspondence_rejected(hanayume_repair_inputs, fault):
    x = hanayume_repair_inputs
    if fault == "wrong_work":
        other = x.catalog.create_work(WorkInput(work_key="other", title="other"))
        foreign, _, _ = x.add(103, "第1話", available=True, parent=other)
        analysis, new_id = load(x), foreign.id
    else:
        analysis, new_id = load(x), x.new.id
        entry = analysis.current[0]
        if fault == "wrong_key":
            entry = replace(entry, source=replace(entry.source, discovery_key="other-key"))
        elif fault == "native_work":
            entry = replace(entry, source=replace(entry.source, external_id=f"bbbbbbbbbbbbb:{101:013x}"))
        elif fault == "url":
            entry = replace(entry, targets=(replace(entry.targets[0], locator="https://evil.test/episode"),))
        elif fault == "site":
            entry = replace(entry, source=replace(entry.source, site="other"))
        else:
            new_id = x.old.id
        analysis = replace(analysis, entries=(analysis.old[0], entry))
    with pytest.raises(ValueError):
        annotate(analysis, (x.old.id,), (new_id,), "mapped", "誤指定")


@pytest.mark.parametrize("config", ["scope", "order", "segments"])
def test_configuration_is_preserved_not_rewritten(hanayume_repair_inputs, config):
    x = hanayume_repair_inputs
    target = dict(x.target)
    if config == "scope":
        target["discovery_scope"] = {"from_url": target["url"],
                                      "excluded_external_ids": [x.old.external_id]}
    elif config == "order":
        target["archive_order"] = 1
    else:
        target["archive_segments"] = [{"order": 1, "start_external_id": x.old.external_id}]
    x.watchlist.write_text(yaml.safe_dump({"targets": [target]}), "utf-8")
    before = x.watchlist.read_bytes()
    result = load(x)
    assert result.targets
    assert x.watchlist.read_bytes() == before
    assert as_config(result.targets[0], config)


def as_config(target, config):
    return getattr(target, {"scope": "discovery_scope", "order": "archive_order",
                           "segments": "archive_segments"}[config])


def test_read_errors_and_stale_snapshot_tokens(hanayume_repair_inputs, tmp_path):
    x = hanayume_repair_inputs
    first = load(x)
    x.catalog.update_item_note(x.old.item_id, "concurrent edit")
    assert load(x).token != first.token
    x.watchlist.write_text(x.watchlist.read_text("utf-8") + "\n# revised\n", "utf-8")
    assert load(x).watchlist_revision != first.watchlist_revision
    with pytest.raises(InventoryLoadError):
        list_repair_works(tmp_path / "missing.sqlite")
    assert not (tmp_path / "missing.sqlite").exists()
    with sqlite3.connect(x.catalog.path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    with pytest.raises(InventoryLoadError, match="WAL"):
        load(x)


class FakeClock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value

    async def sleep(self, seconds):
        self.value += seconds


class FakePage:
    def __init__(self, work, mappings, *, fault=None, clock=None):
        self.work, self.mappings, self.fault = work, mappings, fault
        self.calls, self.times, self.clock = [], [], clock
        self.url = METADATA_DOCUMENT

    async def route(self, pattern, callback):
        self.guard = callback

    async def goto(self, url, **kwargs):
        assert url == METADATA_DOCUMENT
        return SimpleNamespace(status=200)

    async def evaluate(self, script, old_id):
        self.calls.append(old_id)
        self.times.append(self.clock() if self.clock else 0)
        episode = self.mappings.get(old_id, old_id)
        index = 42
        if self.fault == "new_index" and old_id not in self.mappings:
            index = 43
        work = "bbbbbbbbbbbbb" if self.fault == "foreign" else self.work
        result = {"status": int(self.fault) if str(self.fault).isdigit() else 200,
            "url": f"https://hanayume.com/api/episodes/{old_id}", "redirected": False,
            "payload": {"episode": {"id": episode, "indexId": index,
                "series": {"id": work}, "access": {"episodeId": episode},
                "summary": {"id": episode, "indexId": index}}}}
        if self.fault == "redirect":
            result["redirected"] = True
        if self.fault == "url":
            result["url"] += "?foreign=1"
        if self.fault == "malformed":
            result["payload"]["episode"]["access"]["episodeId"] = "bad"
        return result


@pytest.mark.parametrize("fault", [None, "foreign", "new_index", "redirect", "url", "malformed", "403", "429"])
async def test_api_identity_is_not_body_proof_and_rejects_conflicts(hanayume_repair_inputs, fault):
    x = hanayume_repair_inputs
    analysis = load(x)
    clock = FakeClock()
    page = FakePage(x.native_work, {f"{1:013x}": f"{101:013x}"}, fault=fault, clock=clock)
    result = await probe_identities(page, analysis, ProbeLimits(), clock=clock, sleep=clock.sleep)
    updated = with_observations(analysis, result.observations)
    assert updated.summary()["APIで1対1のID対応確認"] == (1 if fault is None else 0)
    assert updated.summary()["本文同一性証明済み"] == 0
    assert updated.current[0].item.status == "pending"
    if fault is None:
        assert result.requests == 2
        assert page.times[1] - page.times[0] >= 2
    if fault in ("403", "429"):
        assert result.requests == 1 and result.next_offset == 0
    blocked = []

    class Route:
        request = SimpleNamespace(method="POST", url="https://hanayume.com/api/checkout/rental")

        async def abort(self):
            blocked.append(True)

        async def continue_(self):
            pytest.fail("mutation allowed")

    await page.guard(Route())
    assert blocked


async def test_more_than_16_ids_budgets_offsets_and_partial_results(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    for number in range(2, 21):
        x.add(number, f"第{number}話", available=False)
    analysis = load(x)
    clock = FakeClock()
    page = FakePage(x.native_work, {f"{i:013x}": f"{101:013x}" for i in range(1, 21)}, clock=clock)
    result = await probe_identities(page, analysis, ProbeLimits(max_requests=50),
                                    clock=clock, sleep=clock.sleep)
    assert len(result.observations) == result.next_offset == 20
    assert result.requests == 21  # independent new API fetched once
    updated = with_observations(analysis, result.observations)
    assert updated.links[0].shape == "20対1"
    assert updated.summary()["APIで1対1のID対応確認"] == 0
    for limits, expected, stop in (
        (ProbeLimits(max_requests=1), 0, "件数"),
        (ProbeLimits(seconds=1), 0, "時間"),
        (ProbeLimits(offset=5, max_old_ids=2), 7, "完了"),
    ):
        clock = FakeClock()
        result = await probe_identities(page, analysis, limits, clock=clock, sleep=clock.sleep)
        assert result.next_offset == expected and stop in result.stop_reason
    result = await probe_identities(page, analysis, ProbeLimits(), cancelled=lambda: True)
    assert result.requests == 0 and result.next_offset == 0


def test_api_result_preserves_manual_override_and_unknown(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    analysis = annotate(load(x), (x.old.id,), (x.new.id,), "hold", "要確認")
    result = with_observations(analysis, (IdentityObservation(x.old.id, x.new.id, "API", 42),))
    assert result.links[0].decision == "hold" and len(result.observations) == 1
    with pytest.raises(ValueError):
        validate_pair(analysis, x.old.id, 99999)


def test_unknown_hold_new_only_reacquire_and_conflicting_api_indexes(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    analysis = load(x)
    held = annotate(analysis, (x.old.id,), (), "hold", "対応不明")
    assert held.links[0].new_ids == ()
    assert held.summary()["対応不明の旧Source"] == 1
    acquired = annotate(held, (), (x.new.id,), "reacquire", "現行構成を優先")
    assert acquired.summary()["明示的な再取得指定（新Source数）"] == 1
    old2, _, _ = x.add(2, "第2話", available=False)
    new2, _, _ = x.add(102, "第2話", available=True)
    result = with_observations(load(x), (
        IdentityObservation(x.old.id, x.new.id, "API", 42),
        IdentityObservation(old2.id, new2.id, "API", 42),
    ))
    assert result.summary()["APIで1対1のID対応確認"] == 0
    assert all(o.new_source_id is None and "矛盾" in o.reason for o in result.observations)


def test_circled_parts_match_the_base_episode_without_position_bridge(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    x.catalog.update_item_metadata(x.old.item_id, order_label="scene2⑤")
    x.catalog.update_item_metadata(x.new.item_id, order_label="scene2")
    x.add(2, "scene1", available=False)
    x.add(102, "scene1", available=True)
    result = load(x)
    assert len(result.links) == 2
    link = next(l for l in result.links if x.old.id in l.old_ids)
    assert link.new_ids == (x.new.id,)
    assert any("話数番号一致" in r for r in link.reasons)


def test_partial_manual_edit_keeps_other_candidates_and_batch_unchanged(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    old2, _, _ = x.add(2, "第1話", available=False)
    new2, _, _ = x.add(102, "第1話", available=True)
    planner = BatchPlanner(x.catalog, default_policy_registry(), watchlist=WatchlistService(x.watchlist))
    now = datetime(2026, 11, 11, tzinfo=JST)
    before = planner.plan(site="hanayume", now=now)
    assert len({c.item_id for c in before.candidates}) == len(before.candidates) == 2
    analysis = annotate(load(x), (x.old.id,), (x.new.id,), "mapped", "1対1として確認中")
    assert any(old2.id in link.old_ids and new2.id in link.new_ids for link in analysis.links)
    # Reread/reanalysis and manual review never change the standard planner.
    assert load(x).catalog_token == analysis.catalog_token
    assert planner.plan(site="hanayume", now=now) == before


def test_exact_part_labels_become_three_independent_guesses(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    x.catalog.update_item_metadata(x.old.item_id, order_label="scene4①")
    x.catalog.update_item_metadata(x.new.item_id, order_label="scene4①")
    pairs = {(x.old.id, x.new.id)}
    for number, part in ((2, "②"), (3, "③")):
        old, _, _ = x.add(number, f"scene4{part}", available=False)
        new, _, _ = x.add(106 - number, f"scene4{part}", available=True)
        pairs.add((old.id, new.id))
    paths = (x.catalog.path, x.watchlist, x.archive)
    before = [p.read_bytes() for p in paths]
    analysis = load(x)
    assert {(l.old_ids[0], l.new_ids[0]) for l in analysis.links} == pairs
    assert all(l.shape == "1対1" and l.evidence == "heuristic" and l.decision == "review"
               and l.match_rule == "label_number_unique" for l in analysis.links)
    assert analysis.summary()["ラベル・話番号で1対1推測"] == 3
    assert analysis.summary()["APIで1対1のID対応確認"] == 0
    assert analysis.summary()["本文同一性証明済み"] == 0
    assert all(e.item.status == "pending" for e in analysis.current)
    assert [p.read_bytes() for p in paths] == before


@pytest.mark.parametrize("side,count", [("old", 2), ("new", 2), ("new", 10)])
def test_duplicate_full_labels_remain_ambiguous_before_edge_cap(hanayume_repair_inputs, side, count):
    x = hanayume_repair_inputs
    for index in range(1, count):
        x.add(index + (101 if side == "new" else 1), "第1話", available=side == "new")
    analysis = load(x)
    assert analysis.summary()["ラベル・話番号で1対1推測"] == 0
    assert len(analysis.links) == 1 and analysis.links[0].shape != "1対1"


def test_api_overrides_label_guess_and_manual_overrides_both(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    other, _, _ = x.add(102, "第2話", available=True)
    initial = load(x)
    assert initial.links[0].new_ids == (x.new.id,)
    result = with_observations(initial, (IdentityObservation(x.old.id, other.id, "strict API", 42),))
    assert result.links[0].evidence == "api_identity" and result.links[0].new_ids == (other.id,)
    held = annotate(result, (x.old.id,), (x.new.id,), "hold", "ラベルとAPIが異なるため確認")
    result = with_observations(held, ())
    assert result.links[0].decision == "hold" and result.links[0].evidence == "manual"
    assert result.observations[0].new_source_id == other.id
