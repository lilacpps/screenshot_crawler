"""Focused tests for the lightweight GUI-to-worker execution contract."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from screenshot_crawler.execution_worker import _run
from screenshot_crawler.management.execution import ExecutionPlanService
from screenshot_crawler.watchlist.models import WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService


def _watchlist(path: Path, *, key: str = "key-a", site: str = "mangaone") -> None:
    WatchlistService(path).apply_edit([
        WatchlistTarget(
            key=key,
            work_key="work-a",
            site=site,
            url="https://example.invalid/work-a",
            label="Work A",
        )
    ])


def _request(tmp_path: Path, *, action: str = "batch") -> dict[str, object]:
    watchlist = tmp_path / "watchlist.yaml"
    _watchlist(watchlist)
    runtime = tmp_path / "runtime.yaml"
    runtime.write_text("sites: {}\n", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text("CRAWLER_CDP_ENDPOINT=http://127.0.0.1:9222\n", encoding="utf-8")
    request: dict[str, object] = {
        "action": action,
        "mode": "full" if action == "discover" else None,
        "selected_keys": ["key-a"],
        "sites": ["mangaone"],
        "keys_by_site": {"mangaone": ["key-a"]},
        "resources_by_site": {"mangaone": "all"} if action == "grant_only" else {},
        "catalog_path": str(tmp_path / "catalog.sqlite"),
        "watchlist_path": str(watchlist),
        "runtime_path": str(runtime),
        "env_file": str(env),
        "output_root": str(tmp_path / "output"),
        "library_dir": str(tmp_path / "Books"),
        "metrics_root": str(tmp_path / "metrics"),
        "fingerprint_kind": "inputs-v1",
    }
    request["plan_fingerprint"] = ExecutionPlanService().input_fingerprint(request)
    return request


def test_inputs_fingerprint_ignores_catalog_bytes_but_signs_runtime_and_watchlist(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    catalog = Path(str(request["catalog_path"]))
    catalog.write_bytes(b"catalog-version-one")
    first = ExecutionPlanService().input_fingerprint(request)
    catalog.write_bytes(b"catalog-version-two")
    assert ExecutionPlanService().input_fingerprint(request) == first

    WatchlistService(request["watchlist_path"]).update_target("key-a", enabled=False)
    changed_watchlist = ExecutionPlanService().input_fingerprint(request)
    assert changed_watchlist != first

    Path(str(request["runtime_path"])).write_text("sites: {mangaone: {}}\n", encoding="utf-8")
    assert ExecutionPlanService().input_fingerprint(request) != changed_watchlist


def test_inputs_fingerprint_uses_worker_defaults_when_paths_are_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    request = _request(tmp_path)
    explicit = dict(request)
    explicit["catalog_path"] = "catalog.sqlite"
    explicit["watchlist_path"] = "watchlist.yaml"
    explicit["runtime_path"] = "crawler.yaml"
    explicit["env_file"] = ".env"
    explicit["output_root"] = "output/batch"
    explicit["library_dir"] = "output/Books"
    explicit["metrics_root"] = "output/metrics"
    omitted = {
        key: value for key, value in explicit.items()
        if key not in {
            "catalog_path", "watchlist_path", "runtime_path", "env_file",
            "output_root", "library_dir", "metrics_root",
        }
    }
    assert ExecutionPlanService().input_fingerprint(omitted) == (
        ExecutionPlanService().input_fingerprint(explicit)
    )


@pytest.mark.parametrize("action,enabled", [("batch", True), ("batch", False), ("discover", True)])
def test_inputs_worker_skips_inventory_and_legacy_plan_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str, enabled: bool
) -> None:
    request = _request(tmp_path, action=action)
    if not enabled:
        WatchlistService(request["watchlist_path"]).update_target("key-a", enabled=False)
        request["plan_fingerprint"] = ExecutionPlanService().input_fingerprint(request)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "screenshot_crawler.execution_worker.InventoryService.load",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Inventory reload")),
    )
    monkeypatch.setattr(
        "screenshot_crawler.execution_worker.ExecutionPlanService.preview",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy preview")),
    )
    monkeypatch.setattr(
        "screenshot_crawler.execution_worker._aggregate_fingerprint",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("batch preview")),
    )
    async def fake_batch(args, catalog):
        calls.append(("batch", args.site))

    async def fake_discover(**kwargs):
        calls.append(("discover", kwargs["target"].key))
        return type("Result", (), {
            "target_key": "key-a", "mode": "full", "observed_count": 1,
            "new_count": 1, "known_count": 0, "complete": True,
            "stopped_reason": "exhausted", "warnings": (), "error": None,
        })()

    monkeypatch.setattr("screenshot_crawler.cli._run_batch_run_locked", fake_batch)
    monkeypatch.setattr("screenshot_crawler.execution_worker._discover_target", fake_discover)
    if action == "discover":
        monkeypatch.setattr("screenshot_crawler.cli._discovery_registry", lambda: object())
    asyncio.run(_run(request))
    assert calls == [(action, "mangaone" if action == "batch" else "key-a")]


def test_inputs_worker_rejects_config_drift_and_key_site_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    Path(str(request["runtime_path"])).write_text("changed: true\n", encoding="utf-8")
    monkeypatch.setattr(
        "screenshot_crawler.cli._run_batch_run_locked",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("site entered")),
    )
    with pytest.raises(RuntimeError, match="changed after confirmation"):
        asyncio.run(_run(request))

    request = _request(tmp_path)
    request["keys_by_site"] = {"magapoke": ["key-a"]}
    request["sites"] = ["magapoke"]
    request["plan_fingerprint"] = ExecutionPlanService().input_fingerprint(request)
    with pytest.raises(RuntimeError, match="changed site"):
        asyncio.run(_run(request))


def test_inputs_worker_rejects_unsupported_grant_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path, action="grant_only")
    request["resources_by_site"] = {"mangaone": "unsupported"}
    request["plan_fingerprint"] = ExecutionPlanService().input_fingerprint(request)

    class Policy:
        def grant_only_supported_access_resources(self):
            return ("all",)

        def validate_grant_only_resource(self, resource):
            raise RuntimeError(f"unsupported: {resource}")

    class Policies:
        def create(self, site):
            return Policy()

    monkeypatch.setattr("screenshot_crawler.execution_worker._batch_policy_registry", lambda: Policies())
    with pytest.raises(RuntimeError, match="unsupported"):
        asyncio.run(_run(request))


def test_persisted_request_keeps_fingerprint_kind(tmp_path: Path) -> None:
    from screenshot_crawler.management.execution import JobExecutionRequest
    from screenshot_crawler.management.jobs import JobStore

    store = JobStore(tmp_path / "management.sqlite")
    request = JobExecutionRequest(
        action="batch",
        selected_keys=frozenset({"key-a"}),
        sites=("mangaone",),
        keys_by_site=(("mangaone", ("key-a",)),),
        fingerprint_kind="inputs-v1",
        plan_fingerprint="inputs-v1:abc",
    )
    job_id, _ = store.create_job(request)
    assert store.request_for(job_id)["fingerprint_kind"] == "inputs-v1"


def test_legacy_worker_keeps_omitted_optional_paths_for_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = {
        "action": "batch",
        "selected_keys": ["key-a"],
        "sites": ["mangaone"],
        "keys_by_site": {"mangaone": ["key-a"]},
        "catalog_path": str(tmp_path / "catalog.sqlite"),
        "watchlist_path": str(tmp_path / "watchlist.yaml"),
        "plan_fingerprint": "legacy-confirmed",
    }
    seen: list[dict[str, object]] = []
    monkeypatch.setattr(
        "screenshot_crawler.execution_worker._aggregate_fingerprint",
        lambda current, policies: (seen.append(current) or "legacy-confirmed"),
    )
    async def fake_batch(args, catalog):
        return None

    monkeypatch.setattr("screenshot_crawler.cli._run_batch_run_locked", fake_batch)
    asyncio.run(_run(request))
    assert seen == [request]
