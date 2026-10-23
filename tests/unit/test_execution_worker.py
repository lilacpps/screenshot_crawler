import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.batch.naming import archive_metadata_for_catalog
from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.core.packaging import archive_stem
from screenshot_crawler.execution_worker import (
    _request_cdp_endpoint,
    _required_fingerprint,
    _run,
    _validated_resources,
    _validated_selection,
)
from screenshot_crawler.management.execution import (
    ExecutionPlanService,
    JobExecutionRequest,
    _effective_endpoint_hash,
    execution_request_payload,
)
from screenshot_crawler.management.inventory import default_policy_registry
from screenshot_crawler.watchlist.service import WatchlistService


def test_worker_endpoint_resolution_uses_explicit_then_transient_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRAWLER_CDP_ENDPOINT_OVERRIDE", "http://inherited.invalid")
    assert _request_cdp_endpoint({"cdp_endpoint": "http://explicit.invalid"}) == "http://explicit.invalid"
    assert _request_cdp_endpoint({}) == "http://inherited.invalid"
    monkeypatch.delenv("CRAWLER_CDP_ENDPOINT_OVERRIDE")
    assert _request_cdp_endpoint({}) is None


def test_confirmed_request_payload_is_json_safe_and_preserves_selection() -> None:
    request = JobExecutionRequest(
        action="grant_only",
        selected_keys=frozenset({"key-b", "key-a"}),
        sites=("mangaone",),
        keys_by_site=(("mangaone", ("key-a", "key-b")),),
        resources_by_site=(("mangaone", "work_ticket"),),
        plan_fingerprint="fingerprint",
    )
    payload = execution_request_payload(request)
    assert json.loads(json.dumps(payload)) == {
        **payload,
        "selected_keys": ["key-a", "key-b"],
        "sites": ["mangaone"],
        "keys_by_site": {"mangaone": ["key-a", "key-b"]},
        "resources_by_site": {"mangaone": "work_ticket"},
    }
    assert _validated_selection(payload) == (
        ("key-a", "key-b"),
        {"mangaone": ("key-a", "key-b")},
    )
    assert _required_fingerprint(payload) == "fingerprint"
    assert _validated_resources(payload, {"mangaone": ("key-a", "key-b")}) == {
        "mangaone": "work_ticket"
    }


def test_worker_rejects_missing_confirmation_fingerprint() -> None:
    with pytest.raises(RuntimeError, match="confirmation fingerprint"):
        _required_fingerprint({})


def test_worker_rejects_site_selection_drift() -> None:
    with pytest.raises(RuntimeError, match="does not match selected_keys"):
        _validated_selection(
            {
                "selected_keys": ["key-a"],
                "sites": ["mangaone"],
                "keys_by_site": {"mangaone": ["key-b"]},
            }
        )


def test_worker_runs_multi_site_request_with_per_site_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from screenshot_crawler.catalog import CatalogService

    catalog_path = tmp_path / "catalog.sqlite"
    CatalogService(catalog_path)
    calls = []
    monkeypatch.setattr(
        "screenshot_crawler.execution_worker._batch_policy_registry",
        lambda: object(),
    )
    monkeypatch.setattr(
        "screenshot_crawler.execution_worker._aggregate_fingerprint",
        lambda request, policies: "confirmed",
    )

    async def fake_run(args, catalog):
        calls.append((args.site, tuple(args.selected_keys), args.grant_only))

    monkeypatch.setattr("screenshot_crawler.cli._run_batch_run_locked", fake_run)
    request = {
        "action": "grant_only",
        "selected_keys": ["a", "b"],
        "sites": ["magapoke", "mangaone"],
        "keys_by_site": {"magapoke": ["a"], "mangaone": ["b"]},
        "resources_by_site": {
            "magapoke": "work_ticket",
            "mangaone": "all",
        },
        "catalog_path": str(catalog_path),
        "watchlist_path": str(tmp_path / "watchlist.yaml"),
        "plan_fingerprint": "confirmed",
    }
    asyncio.run(_run(request))
    assert calls == [("magapoke", ("a",), "work_ticket"), ("mangaone", ("b",), "all")]


def test_worker_does_not_treat_incomplete_discovery_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from screenshot_crawler.catalog import CatalogService
    from screenshot_crawler.management.models import InventorySnapshot
    from screenshot_crawler.watchlist.service import WatchlistService

    catalog_path = tmp_path / "catalog.sqlite"
    CatalogService(catalog_path)
    watchlist_path = tmp_path / "watchlist.yaml"
    WatchlistService(watchlist_path).add(
        key="key-a",
        work_key="work-a",
        site="mangaone",
        url="https://example.invalid/a",
        label="A",
    )
    preview = SimpleNamespace(blockers=(), fingerprint="confirmed")
    monkeypatch.setattr("screenshot_crawler.execution_worker.InventoryService.load", lambda *args, **kwargs: InventorySnapshot.__new__(InventorySnapshot))
    monkeypatch.setattr("screenshot_crawler.execution_worker.ExecutionPlanService.preview", lambda *args, **kwargs: preview)
    monkeypatch.setattr("screenshot_crawler.execution_worker._discovery_registry", lambda: object())
    monkeypatch.setattr("screenshot_crawler.execution_worker.read_env_file", lambda path: {})
    async def incomplete(*args, **kwargs):
        return SimpleNamespace(complete=False, stopped_reason="incomplete")
    monkeypatch.setattr("screenshot_crawler.execution_worker._discover_target", incomplete)
    request = {
        "action": "discover",
        "selected_keys": ["key-a"],
        "sites": ["mangaone"],
        "keys_by_site": {"mangaone": ["key-a"]},
        "catalog_path": str(catalog_path),
        "watchlist_path": str(watchlist_path),
        "plan_fingerprint": "confirmed",
    }
    with pytest.raises(RuntimeError, match="Discovery incomplete"):
        asyncio.run(_run(request))


@pytest.mark.parametrize(
    "blocker",
    [
        "Scope/Watchlist state is stale",
        "Unsupported access resource",
        "重大なZIP衝突",
    ],
)
def test_worker_batch_preflight_blocks_before_site_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blocker: str
) -> None:
    from screenshot_crawler.catalog import CatalogService

    catalog_path = tmp_path / "catalog.sqlite"
    CatalogService(catalog_path)
    monkeypatch.setattr(
        "screenshot_crawler.execution_worker._batch_policy_registry",
        lambda: object(),
    )
    monkeypatch.setattr(
        "screenshot_crawler.management.execution.ExecutionPlanService.preview_batch",
        lambda *args, **kwargs: SimpleNamespace(
            blockers=(blocker,), fingerprint="ignored"
        ),
    )
    entered = []

    async def forbidden_run(args, catalog):
        entered.append(args.site)

    monkeypatch.setattr("screenshot_crawler.cli._run_batch_run_locked", forbidden_run)
    request = {
        "action": "grant_only",
        "selected_keys": ["key-a"],
        "sites": ["mangaone"],
        "keys_by_site": {"mangaone": ["key-a"]},
        "resources_by_site": {"mangaone": "unsupported"},
        "catalog_path": str(catalog_path),
        "watchlist_path": str(tmp_path / "watchlist.yaml"),
        "plan_fingerprint": "ignored",
    }
    with pytest.raises(RuntimeError, match="preflight blocked"):
        asyncio.run(_run(request))
    assert entered == []


def test_worker_skips_disabled_discover_before_browser_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from screenshot_crawler.catalog import CatalogService
    from screenshot_crawler.watchlist.service import WatchlistService

    catalog_path = tmp_path / "catalog.sqlite"
    CatalogService(catalog_path)
    watchlist_path = tmp_path / "watchlist.yaml"
    WatchlistService(watchlist_path).add(
        key="disabled-key",
        work_key="work-a",
        site="mangaone",
        url="https://example.invalid/a",
        label="A",
        enabled=False,
    )
    monkeypatch.setattr(
        "screenshot_crawler.execution_worker.InventoryService.load",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "screenshot_crawler.execution_worker.ExecutionPlanService.preview",
        lambda *args, **kwargs: SimpleNamespace(blockers=(), fingerprint="confirmed"),
    )
    monkeypatch.setattr(
        "screenshot_crawler.execution_worker._discover_target",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("browser entered")),
    )
    request = {
        "action": "discover",
        "selected_keys": ["disabled-key"],
        "sites": ["mangaone"],
        "keys_by_site": {"mangaone": ["disabled-key"]},
        "catalog_path": str(catalog_path),
        "watchlist_path": str(watchlist_path),
        "plan_fingerprint": "confirmed",
    }
    asyncio.run(_run(request))


def test_execution_preview_rejects_discover_when_all_selected_keys_disabled(
    tmp_path: Path,
) -> None:
    """A disabled-only Discover selection must fail closed at confirmation."""

    from screenshot_crawler.management.inventory import InventoryService
    from tools.gui_sample import create_sample

    db, watchlist = create_sample(tmp_path / "inputs")
    runtime = tmp_path / "inputs" / "sample-runtime.yaml"
    snapshot = InventoryService().load(db, watchlist, runtime_path=runtime)
    preview = ExecutionPlanService().preview(
        snapshot,
        ["sample-0003"],
        action="discover",
        mode="full",
        runtime_path=str(runtime),
    )

    assert not preview.can_confirm
    assert any("at least one enabled" in blocker for blocker in preview.blockers)


def test_worker_rejects_all_disabled_discover_before_browser_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The subprocess boundary enforces the same disabled-only safety gate."""

    from screenshot_crawler.catalog import CatalogService
    from screenshot_crawler.management.inventory import InventoryService
    from screenshot_crawler.watchlist.service import WatchlistService

    catalog_path = tmp_path / "catalog.sqlite"
    CatalogService(catalog_path).initialize()
    watchlist_path = tmp_path / "watchlist.yaml"
    WatchlistService(watchlist_path).add(
        key="disabled-key",
        work_key="work-a",
        site="mangaone",
        url="https://example.invalid/a",
        label="A",
        enabled=False,
    )
    runtime_path = tmp_path / "runtime.yaml"
    runtime_path.write_text("sites: {}\n", encoding="utf-8")
    snapshot = InventoryService().load(
        catalog_path, watchlist_path, runtime_path=runtime_path
    )
    preview = ExecutionPlanService().preview(
        snapshot,
        ["disabled-key"],
        action="discover",
        mode="full",
        runtime_path=str(runtime_path),
    )
    monkeypatch.setattr(
        "screenshot_crawler.execution_worker._discover_target",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("browser entered")
        ),
    )
    request = {
        "action": "discover",
        "mode": "full",
        "selected_keys": ["disabled-key"],
        "sites": ["mangaone"],
        "keys_by_site": {"mangaone": ["disabled-key"]},
        "catalog_path": str(catalog_path),
        "watchlist_path": str(watchlist_path),
        "runtime_path": str(runtime_path),
        "plan_fingerprint": preview.fingerprint,
    }
    with pytest.raises(RuntimeError, match="changed after confirmation"):
        asyncio.run(_run(request))


def _isolated_sample_request(tmp_path: Path) -> tuple[dict[str, object], Path, Path, Path, Path]:
    from tools.gui_sample import create_sample

    db, watchlist = create_sample(tmp_path / "inputs")
    runtime = tmp_path / "inputs" / "sample-runtime.yaml"
    env_file = tmp_path / "inputs" / "sample.env"
    env_file.write_text("CRAWLER_CDP_ENDPOINT=http://127.0.0.1:9222\n", encoding="utf-8")
    output_root = tmp_path / "batch"
    library_dir = tmp_path / "Books"
    metrics_root = tmp_path / "metrics"
    preview = ExecutionPlanService().preview_batch(
        str(db),
        str(watchlist),
        default_policy_registry(),
        site="mangaone",
        selected_keys=["sample-0004"],
        runtime_path=str(runtime),
        env_file=str(env_file),
        output_root=str(output_root),
        library_dir=str(library_dir),
        metrics_root=str(metrics_root),
    )
    assert not preview.blockers
    request = {
        "action": "batch",
        "selected_keys": ["sample-0004"],
        "sites": ["mangaone"],
        "keys_by_site": {"mangaone": ["sample-0004"]},
        "catalog_path": str(db),
        "watchlist_path": str(watchlist),
        "runtime_path": str(runtime),
        "env_file": str(env_file),
        "output_root": str(output_root),
        "library_dir": str(library_dir),
        "metrics_root": str(metrics_root),
        "plan_fingerprint": preview.fingerprint,
    }
    return request, db, watchlist, runtime, env_file


@pytest.mark.parametrize("mutation", ["watchlist", "runtime", "env", "catalog"])
def test_worker_rejects_real_input_drift_before_site_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    request, db, watchlist, runtime, env_file = _isolated_sample_request(tmp_path)
    if mutation == "watchlist":
        WatchlistService(watchlist).set_enabled("sample-0004", False)
    elif mutation == "runtime":
        runtime.write_text("sites:\n  mangaone: {}\n", encoding="utf-8")
    elif mutation == "env":
        env_file.write_text("CRAWLER_CDP_ENDPOINT=http://127.0.0.1:9333\n", encoding="utf-8")
    else:
        CatalogService(db).update_source_external_state(
            "mangaone", "53", access_mode="unknown"
        )

    monkeypatch.setattr(
        "screenshot_crawler.cli._run_batch_run_locked",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("site entered")),
    )
    with pytest.raises(RuntimeError, match="Catalog/Watchlist changed after confirmation"):
        asyncio.run(_run(request))


def test_worker_rejects_real_zip_collision_before_site_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, db, watchlist, _runtime, _env_file = _isolated_sample_request(tmp_path)
    catalog = CatalogService(db)
    planner = BatchPlanner(
        catalog,
        default_policy_registry(),
        watchlist=WatchlistService(watchlist),
        library_dir=tmp_path / "Books",
    )
    candidate = planner.plan(
        site="mangaone", selected_keys=["sample-0004"]
    ).candidates[0]
    item = catalog.get_item(candidate.item_id)
    work = catalog.get_work(item.work_id)
    source = catalog.get_source(candidate.source_id)
    metadata = archive_metadata_for_catalog(work, item, source)
    stem, title, genre, _order, _author = archive_stem(
        metadata,
        artifact_prefix=candidate.artifact_prefix,
        artifact_disambiguator=candidate.artifact_disambiguator,
    )
    archive_path = tmp_path / "Books" / genre / title / f"{stem}.zip"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_bytes(b"synthetic collision")
    monkeypatch.setattr(
        "screenshot_crawler.cli._run_batch_run_locked",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("site entered")),
    )
    from screenshot_crawler.batch import BatchPlanningError

    with pytest.raises(BatchPlanningError, match="Candidate output already exists"):
        asyncio.run(_run(request))


def test_missing_env_file_is_treated_as_empty_for_worker_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, _db, _watchlist, _runtime, env_file = _isolated_sample_request(tmp_path)
    env_file.unlink()
    monkeypatch.setattr(
        "screenshot_crawler.execution_worker._aggregate_fingerprint",
        lambda request, policies: request["plan_fingerprint"],
    )
    monkeypatch.setattr(
        "screenshot_crawler.cli._run_batch_run_locked",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("site entered")),
    )
    with pytest.raises(AssertionError, match="site entered"):
        asyncio.run(_run(request))


def test_endpoint_identity_hash_tracks_effective_process_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing_env = tmp_path / "missing.env"
    monkeypatch.setenv("CRAWLER_CDP_ENDPOINT", "http://127.0.0.1:9222")
    first = _effective_endpoint_hash(
        "mangaone", env_file=str(missing_env), cdp_endpoint=None
    )
    monkeypatch.setenv("CRAWLER_CDP_ENDPOINT", "http://127.0.0.1:9333")
    second = _effective_endpoint_hash(
        "mangaone", env_file=str(missing_env), cdp_endpoint=None
    )
    assert first != second
