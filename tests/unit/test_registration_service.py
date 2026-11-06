from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import yaml

from screenshot_crawler.catalog.job_lock import CatalogJobLock
from screenshot_crawler.management.catalog_reader import CatalogInventoryReader
from screenshot_crawler.registration.detail import accept_detail
from screenshot_crawler.registration.service import RegistrationService, retain_unsaved
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService
from tests.unit.test_registration_detail import URLS, add, detail, setup_batch


def yaml_section(preview, title):
    excerpt = preview.summary.split(f"【{title}】\n", 1)[1].split("\n【", 1)[0]
    # The final YAML section is followed by the human-readable Work summary.
    excerpt = excerpt.split("\n\n選択したWork", 1)[0]
    return yaml.safe_load(excerpt)["targets"]


def source(catalog, *, site="jumpplus", url=URLS["jumpplus"], owner="owner", work_key="other", external_id="4"):
    work = catalog.find_work(work_key) or catalog.create_work(work_key=work_key, title="既存作品")
    return catalog.create_discovered_item_source_target(work_id=work.id, item_input={"status": "completed"},
        source_input={"site": site, "external_id": external_id, "discovery_key": owner},
        web_target_input={"backend": "web", "target_key": "default", "locator": url})


def test_selected_set_single_apply_preserves_unselected_drafts_catalog_zip_and_comments(tmp_path, monkeypatch):
    batch, path, catalog = setup_batch(tmp_path)
    WatchlistService(path).apply_edit((WatchlistTarget("legacy", "legacy_work", "kadocomi",
        "https://comic-walker.com/detail/KC_004915_S", "既存", False),))
    path.write_text("# 人の注釈\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    batch.base, batch.revision = WatchlistService(path).read_snapshot()
    a, b = add(batch, "jumpplus", "first"), add(batch, "comicdays", "second")
    blocked = batch.add_resolution(3, "https://evil.test", batch.resolver.resolve("https://evil.test"))
    batch.select(b, False)
    batch.select(blocked, False)
    kept = batch.candidates[b]
    archive = tmp_path / "existing.zip"
    archive.write_bytes(b"isolated archive sentinel")
    original = catalog.path.read_bytes(), archive.read_bytes()
    service = RegistrationService(path, catalog.path)
    preview = service.preview(batch)
    assert "UNKNOWN" in preview.summary and "first-jumpplus" in preview.summary
    assert "second-comicdays" not in preview.summary
    planned = yaml_section(preview, "追加する項目")
    assert planned == [{"key": "first-jumpplus", "work_key": "first", "site": "jumpplus",
        "url": URLS["jumpplus"], "enabled": True, "label": "人工作品"}]
    assert "追加 1件 / 更新 0件 / 既存のまま 1件" in preview.summary
    calls = []
    apply = service.watchlist.apply_edit
    def count(*args, **kwargs):
        calls.append(True)
        return apply(*args, **kwargs)
    monkeypatch.setattr(service.watchlist, "apply_edit", count)
    result = service.save(batch, preview)
    assert result.verified and calls == [True]
    assert {target.key for target in WatchlistService(path).list_targets()} == {"legacy", "first-jumpplus"}
    assert path.read_text(encoding="utf-8").startswith("# 人の注釈\n")
    assert "label: 既存\n\n- key: first-jumpplus\n" in path.read_text(encoding="utf-8")
    actual = yaml.safe_load(path.read_text(encoding="utf-8"))["targets"]
    assert planned == [target for target in actual if target["key"] == "first-jumpplus"]
    assert original == (catalog.path.read_bytes(), archive.read_bytes())
    retain_unsaved(batch, result)
    assert batch.candidates[b] == kept and b in batch.works
    assert a not in batch.works and blocked in batch.works
    # Internal row IDs must not overwrite retained rows after partial save.
    c = batch.add_resolution(4, "https://shonenjumpplus.com/episode/99",
        batch.resolver.resolve("https://shonenjumpplus.com/episode/99"))
    assert c not in (a, b, blocked) and batch.candidates[b] == kept


def test_blocked_selected_aborts_every_work(tmp_path):
    batch, path, catalog = setup_batch(tmp_path)
    add(batch, "jumpplus", "first")
    batch.add_resolution(2, "https://evil.test", batch.resolver.resolve("https://evil.test"))
    before = path.read_bytes(), catalog.path.read_bytes()
    with pytest.raises(ValueError, match="blocked"):
        RegistrationService(path, catalog.path).preview(batch)
    assert before == (path.read_bytes(), catalog.path.read_bytes())


@pytest.mark.parametrize("change", ["watchlist", "catalog", "selection", "label", "url"])
def test_race_or_post_preview_edit_is_all_or_nothing(tmp_path, change):
    batch, path, catalog = setup_batch(tmp_path)
    a = add(batch, "jumpplus", "first")
    add(batch, "comicdays", "second")
    service = RegistrationService(path, catalog.path)
    preview = service.preview(batch)
    if change == "watchlist":
        WatchlistService(path).add(key="external", work_key="external", site="jumpplus",
            url="https://shonenjumpplus.com/episode/99", label="外部変更")
    elif change == "catalog":
        catalog.create_work(work_key="external", title="外部変更")
    elif change == "selection":
        batch.select(a, False)
    elif change == "label":
        batch.edit_candidate(a, label="変更")
    else:
        batch.candidates[a] = replace(batch.candidates[a], resolution=replace(
            batch.candidates[a].resolution, discovery_url="https://evil.test"))
    before = path.read_bytes(), catalog.path.read_bytes()
    with pytest.raises(ValueError):
        service.save(batch, preview)
    assert before == (path.read_bytes(), catalog.path.read_bytes())


@pytest.mark.parametrize("url,owner,work_key", [(URLS["jumpplus"], "owner", "other"),
    (URLS["jumpplus"], None, "other"), ("https://legacy.invalid/unknown", "removed", "other"),
    ("https://shonenjumpplus.com/episode/999", "first-jumpplus", "other")])
def test_real_catalog_source_target_ownership_guard(tmp_path, url, owner, work_key):
    batch, path, catalog = setup_batch(tmp_path)
    add(batch, "jumpplus", "first")
    source(catalog, url=url, owner=owner, work_key=work_key)
    before = path.read_bytes(), catalog.path.read_bytes()
    with pytest.raises(ValueError, match="Source|key"):
        RegistrationService(path, catalog.path).preview(batch)
    assert before == (path.read_bytes(), catalog.path.read_bytes())


@pytest.mark.parametrize("change_scope", [False, True])
def test_existing_work_addition_preserves_old_fields_and_saves_one_composed_proposal(tmp_path, change_scope):
    batch, path, catalog = setup_batch(tmp_path)
    old = WatchlistTarget("legacy_key", "legacy_work", "jumpplus", URLS["jumpplus"], "旧label", False,
        archive_order=7)
    watch = WatchlistService(path)
    watch.apply_edit((old,))
    batch.base, batch.revision = watch.read_snapshot()
    a = add(batch, "comicdays", "new")
    b = add(batch, "magapoke", "another")
    batch.assign(a, existing_work="legacy_work")
    batch.confirm(a)
    group = batch.candidates[a].group_id
    request, draft, _result = detail(batch, group)
    # The helper uses sequential order for new Works; preserve the old order
    # here and explicitly append the incoming source.
    updated_old = replace(old, discovery_scope=DiscoveryScope(excluded_external_ids=("1",))) if change_scope else old
    draft.update(updated_old)
    new = draft.members[1]
    draft.update(replace(new, archive_order=8))
    from screenshot_crawler.watchlist.work_edit import validate_work_snapshot
    result = validate_work_snapshot(draft, batch.catalog_snapshot, batch.revision)
    accept_detail(batch, request, result, {target.key for target in draft.members})
    service = RegistrationService(path, catalog.path)
    preview = service.preview(batch)
    planned = yaml_section(preview, "追加する項目")
    assert {target["key"] for target in planned} == {new.key, batch.candidates[b].key}
    if change_scope:
        assert yaml_section(preview, "既存項目の変更前")[0]["enabled"] is False
        assert "discovery_scope" not in yaml_section(preview, "既存項目の変更前")[0]
        updated = yaml_section(preview, "既存項目の変更後")
        assert updated[0]["discovery_scope"] == {"excluded_external_ids": ["1"]}
        assert updated[0]["archive_order"] == 7
    else:
        assert "既存項目の変更後】\n（なし）" in preview.summary
    saved = service.save(batch, preview)
    assert saved.verified
    assert WatchlistService(path).get(old.key) == updated_old
    actual = yaml.safe_load(path.read_text(encoding="utf-8"))["targets"]
    assert planned == [target for target in actual if target["key"] in {new.key, batch.candidates[b].key}]
    if change_scope:
        assert updated == [target for target in actual if target["key"] == old.key]
    assert {target.work_key for target in saved.targets} == {"legacy_work", batch.works[b].work_key}


def test_multiple_site_group_scope_segments_and_stale_proof(tmp_path, monkeypatch):
    batch, path, catalog = setup_batch(tmp_path)
    a, b = add(batch, "jumpplus", "work"), add(batch, "comicdays", "other")
    batch.assign(b, group_id=a)
    batch.confirm(b)
    request, draft, _result = detail(batch, a)
    draft.replace_range(draft.members[0].key, "2", "2", draft.members[1].key, "2", "2")
    from screenshot_crawler.watchlist.work_edit import validate_work_snapshot
    result = validate_work_snapshot(draft, batch.catalog_snapshot, batch.revision)
    accept_detail(batch, request, result, {target.key for target in draft.members})
    service = RegistrationService(path, catalog.path)
    preview = service.preview(batch)
    assert all(target.archive_segments is not None for target in preview.targets)
    planned = yaml_section(preview, "追加する項目")
    assert all("archive_segments" in target for target in planned)
    assert any("discovery_scope" in target for target in planned)
    assert "DiscoveryScope(" not in preview.summary and "ArchiveSegment(" not in preview.summary
    assert WatchlistService(path)._load_content(yaml.safe_dump({"targets": planned})) == list(preview.targets)
    import screenshot_crawler.registration.draft as module
    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(seconds=301)
    monkeypatch.setattr(module, "datetime", Later)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="needs_scope"):
        service.save(batch, preview)
    assert path.read_bytes() == before


def test_catalog_lock_and_atomic_replace_failure_leave_entire_set_unchanged(tmp_path, monkeypatch):
    batch, path, catalog = setup_batch(tmp_path)
    add(batch, "jumpplus", "first")
    add(batch, "comicdays", "second")
    service = RegistrationService(path, catalog.path)
    preview = service.preview(batch)
    before = path.read_bytes(), catalog.path.read_bytes()
    with CatalogJobLock(catalog.path), ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.save, batch, preview)
        with pytest.raises(RuntimeError, match="job"):
            future.result()
    def fail(_content):
        raise OSError("injected pre-replace failure")
    monkeypatch.setattr(service.watchlist, "_atomic_write", fail)
    with pytest.raises(OSError):
        service.save(batch, preview)
    assert before == (path.read_bytes(), catalog.path.read_bytes())


def test_readback_error_is_committed_unverified_not_rollback(tmp_path, monkeypatch):
    batch, path, catalog = setup_batch(tmp_path)
    add(batch, "jumpplus", "first")
    service = RegistrationService(path, catalog.path)
    preview = service.preview(batch)
    apply, read = service.watchlist.apply_edit, service.watchlist.read_snapshot
    committed = False
    def commit(*args, **kwargs):
        nonlocal committed
        result = apply(*args, **kwargs)
        committed = True
        return result
    def readback():
        if committed:
            raise OSError("synthetic readback")
        return read()
    monkeypatch.setattr(service.watchlist, "apply_edit", commit)
    monkeypatch.setattr(service.watchlist, "read_snapshot", readback)
    result = service.save(batch, preview)
    assert not result.verified and result.revision is None
    assert "保存済み" in result.message
    assert WatchlistService(path).get("first-jumpplus")
    with pytest.raises(ValueError):
        retain_unsaved(batch, result)


def test_missing_catalog_does_not_create_or_fallback(tmp_path):
    batch, path, _catalog = setup_batch(tmp_path)
    add(batch, "jumpplus", "work")
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(RuntimeError):
        RegistrationService(path, missing).preview(batch)
    assert not missing.exists()


def test_two_same_revision_savers_have_one_winner(tmp_path):
    batch, path, catalog = setup_batch(tmp_path)
    add(batch, "jumpplus", "work")
    service = RegistrationService(path, catalog.path)
    preview = service.preview(batch)
    def save():
        try:
            return RegistrationService(path, catalog.path).save(batch, preview).verified
        except (ValueError, RuntimeError):
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: save(), range(2))) == [False, True]
    assert len(WatchlistService(path).list_targets()) == 1


def test_ownership_display_cache_is_bound_to_snapshot_url_and_saved_identity(tmp_path, monkeypatch):
    batch, _path, catalog = setup_batch(tmp_path)
    row = add(batch, "jumpplus", "work")
    source(catalog, url="https://shonenjumpplus.com/episode/999")
    data = CatalogInventoryReader().read(catalog.path)
    calls, resolve = [], batch.resolver.resolve
    def count(url):
        calls.append(url)
        return resolve(url)
    monkeypatch.setattr(batch.resolver, "resolve", count)
    batch.prepare_ownership(data)
    first_count = len(calls)
    for _ in range(10):
        assert not batch.ownership_blockers(row, data)
    assert len(calls) == first_count  # GUI redraw does not reparse Catalog URLs.
    batch.retry(row, resolve("https://shonenjumpplus.com/episode/999"))
    assert batch.ownership_blockers(row, data)  # Candidate changed; cached ready cannot survive.
    changed = replace(data, targets=(replace(data.targets[0], locator="https://legacy.invalid/unknown"),))
    errors = batch.ownership_blockers(row, changed)
    assert errors and "未確定" in " / ".join(errors)
    assert len(calls) > first_count
