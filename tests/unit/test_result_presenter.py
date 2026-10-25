import json

from screenshot_crawler.management.execution import JobExecutionRequest
from screenshot_crawler.management.jobs import JobEvent, JobStore
from screenshot_crawler.management.result_presenter import JobResultPresenter


def _request(action: str, *, metrics_root=None, keys=("key-a", "key-b")):
    return JobExecutionRequest(
        action=action,
        selected_keys=frozenset(keys),
        sites=("mangaone",),
        keys_by_site=(("mangaone", keys),),
        metrics_root=str(metrics_root) if metrics_root else None,
        plan_fingerprint="fixture",
    )


def _job(store: JobStore, request: JobExecutionRequest) -> str:
    job_id, _ = store.create_job(request)
    return job_id


def test_presenter_uses_keyset_pages_and_preserves_unknown_discovery(tmp_path):
    store = JobStore(tmp_path / "management.sqlite")
    job_id = _job(store, _request("discover"))
    task_id = f"{job_id}:mangaone"
    store.set_task_state(task_id, "running")
    store.append_event(JobEvent(job_id, "candidate_started", task_id=task_id, site="mangaone", key="key-a"))
    store.append_event(JobEvent(
        job_id, "discovery_result", task_id=task_id, site="mangaone", key="key-a",
        result="succeeded", payload={
            "target": "key-a", "observed": 3, "new": 2, "known": 1,
            "complete": True, "stopped_reason": None, "warnings": [],
        },
    ))
    store.append_event(JobEvent(job_id, "candidate_finished", task_id=task_id, site="mangaone", key="key-a", result="succeeded"))
    store.append_event(JobEvent(job_id, "candidate_started", task_id=task_id, site="mangaone", key="key-b"))
    presenter = JobResultPresenter(store, event_page_size=2, latest_event_size=1)
    first = presenter.present(job_id)
    second = presenter.present(job_id)
    assert first.event_cursor == 2
    assert not first.event_page_complete
    assert second.event_cursor == 4
    results = {(item.site, item.key): item for item in second.discover}
    assert results[("mangaone", "key-a")].status == "success"
    assert results[("mangaone", "key-a")].new == 2
    assert results[("mangaone", "key-b")].status == "unknown"
    assert second.current.key == "key-b"
    assert second.state == "queued"
    assert not any(problem.event_type == "metrics" for problem in second.problems)


def test_presenter_reports_missing_expected_batch_metrics_only(tmp_path):
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    store = JobStore(tmp_path / "management.sqlite")
    job_id = _job(store, _request("batch", metrics_root=metrics_root))
    task_id = f"{job_id}:mangaone"
    store.append_event(JobEvent(
        job_id, "metrics_started", task_id=task_id, site="mangaone",
        payload={"metrics_path": str(metrics_root / "mangaone.jsonl")},
    ))
    result = JobResultPresenter(store).present(job_id)
    assert result.batches[0].metrics_status == "missing"
    assert any(problem.event_type == "metrics" and "missing" in problem.reason for problem in result.problems)


def test_presenter_batch_aggregates_metrics_skips_and_latest_grants(tmp_path):
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    store = JobStore(tmp_path / "management.sqlite")
    job_id = _job(store, _request("batch", metrics_root=metrics_root))
    task_id = f"{job_id}:mangaone"
    metrics_path = metrics_root / "mangaone.jsonl"
    records = [
        {"type": "batch", "event": "start", "site": "mangaone", "run_id": "run-1"},
        {"type": "candidate", "event": "result", "result": "skipped", "start_time": None},
        {"type": "candidate", "event": "result", "result": "skipped", "start_time": None, "access_strategy": "direct"},
        {"type": "candidate", "event": "result", "result": "skipped", "start_time": "2026-01-01T00:00:00+00:00", "access_strategy": "direct"},
        {"type": "grant_result", "work_id": 4, "label": "old", "resource": "ticket", "status": "NG", "reason": "old", "resource_consumed": False},
        {"type": "grant_result", "work_id": 4, "label": "new", "resource": "ticket", "item_id": 4, "source_id": 8, "status": "OK", "reason": "postprocess failed https://user:pass@example.test/?token=secret Authorization: Bearer topsecret", "resource_consumed": True},
        {"type": "grant_result", "work_id": 5, "label": "pending", "resource": "ticket", "source_id": 9, "status": "OK", "reason": "awaiting result", "resource_consumed": True},
        {"type": "candidate", "event": "result", "site": "mangaone", "item_id": 4, "source_id": 8, "resource": "ticket", "result": "failed", "stop_reason": "postprocess failed"},
        {"type": "batch_summary", "candidates_started": 2, "candidates_completed": 1, "candidates_failed": 0, "elapsed": 1.5, "stop_reason": None, "http_requests_total": 5, "retry_count": 1, "challenge_count": 0},
    ]
    metrics_path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    store.append_event(JobEvent(
        job_id, "metrics_started", task_id=task_id, site="mangaone",
        payload={"metrics_path": str(metrics_path)},
    ))
    store.append_event(JobEvent(
        job_id, "grant_confirmed", task_id=task_id, site="mangaone",
        resource="ticket", item_id=4, source_id=8, resource_consumed=True,
    ))
    presenter = JobResultPresenter(store)
    result = presenter.present(job_id)
    assert result.batches[0].planned_skips == 1
    assert result.batches[0].execution_skips == 2
    assert result.batches[0].candidates_started == 2
    assert result.batches[0].http_requests == 5
    assert len(result.grants) == 2
    assert sum(grant.item_id == 4 and grant.source_id == 8 for grant in result.grants) == 1
    new_grant = next(grant for grant in result.grants if grant.label == "new")
    pending_grant = next(grant for grant in result.grants if grant.label == "pending")
    assert new_grant.outcome == "consumed_but_postprocess_failed"
    assert pending_grant.outcome == "postprocess_unknown"
    assert "secret" not in (new_grant.reason or "")
    assert "topsecret" not in (new_grant.reason or "")
    assert "<redacted>" in (new_grant.reason or "")


def test_presenter_rejects_invalid_metrics_without_promoting_state(tmp_path):
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    store = JobStore(tmp_path / "management.sqlite")
    job_id = _job(store, _request("batch", metrics_root=metrics_root))
    task_id = f"{job_id}:mangaone"
    outside = tmp_path / "outside.jsonl"
    outside.write_text("not-json\n", encoding="utf-8")
    store.append_event(JobEvent(
        job_id, "metrics_started", task_id=task_id, site="mangaone",
        payload={"metrics_path": str(outside)},
    ))
    store.set_state(job_id, "failed", summary={"success": False})
    result = JobResultPresenter(store).present(job_id)
    assert result.state == "failed"
    assert result.batches[0].metrics_status == "invalid"
    assert any(problem.event_type == "metrics" for problem in result.problems)


def test_presenter_rejects_metrics_site_scope_mismatch(tmp_path):
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    store = JobStore(tmp_path / "management.sqlite")
    job_id = _job(store, _request("batch", metrics_root=metrics_root))
    task_id = f"{job_id}:mangaone"
    metrics_path = metrics_root / "mangaone.jsonl"
    metrics_path.write_text(
        json.dumps({"type": "batch", "event": "start", "site": "other-site", "run_id": "r"}) + "\n"
        + json.dumps({"type": "batch_summary", "stop_reason": "no_candidates"}) + "\n",
        encoding="utf-8",
    )
    store.append_event(JobEvent(job_id, "metrics_started", task_id=task_id, site="mangaone", payload={"metrics_path": str(metrics_path)}))
    result = JobResultPresenter(store).present(job_id)
    assert result.batches[0].metrics_status == "scope_invalid"
    assert result.batches[0].status == "unknown"


def test_presenter_keeps_same_work_and_resource_separate_per_site(tmp_path):
    from screenshot_crawler.management.execution import JobExecutionRequest

    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    store = JobStore(tmp_path / "management.sqlite")
    request = JobExecutionRequest(
        action="grant_only", selected_keys=frozenset({"a", "b"}), sites=("mangaone", "bookwalker"),
        keys_by_site=(("mangaone", ("a",)), ("bookwalker", ("b",))), metrics_root=str(metrics_root),
        plan_fingerprint="fixture",
    )
    job_id, _ = store.create_job(request)
    for site, source_id in (("mangaone", 1), ("bookwalker", 2)):
        path = metrics_root / f"{site}.jsonl"
        path.write_text("\n".join((
            json.dumps({"type": "batch", "event": "start", "site": site, "run_id": site}),
            json.dumps({"type": "grant_result", "work_id": 7, "label": site, "resource": "ticket", "source_id": source_id, "status": "OK", "resource_consumed": False}),
            json.dumps({"type": "batch_summary", "stop_reason": "no_candidates"}),
        )) + "\n", encoding="utf-8")
        store.append_event(JobEvent(job_id, "metrics_started", task_id=f"{job_id}:{site}", site=site, payload={"metrics_path": str(path)}))
    result = JobResultPresenter(store).present(job_id)
    assert {(grant.site, grant.work_id) for grant in result.grants} == {("mangaone", 7), ("bookwalker", 7)}


def test_presenter_direct_grant_fallback_requires_matching_site_and_strong_identity(tmp_path):
    from screenshot_crawler.management.execution import JobExecutionRequest

    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    store = JobStore(tmp_path / "management.sqlite")
    request = JobExecutionRequest(
        action="batch", selected_keys=frozenset({"a", "b"}), sites=("mangaone", "bookwalker"),
        keys_by_site=(("mangaone", ("a",)), ("bookwalker", ("b",))), metrics_root=str(metrics_root),
        plan_fingerprint="fixture",
    )
    job_id, _ = store.create_job(request)
    path = metrics_root / "mangaone.jsonl"
    path.write_text("\n".join((
        json.dumps({"type": "batch", "event": "start", "site": "mangaone", "run_id": "r"}),
        json.dumps({"type": "grant_result", "work_id": 7, "label": "report", "resource": "ticket", "item_id": 4, "source_id": 8, "status": "OK", "resource_consumed": False}),
        json.dumps({"type": "batch_summary", "candidates_skipped": 0}),
    )) + "\n", encoding="utf-8")
    store.append_event(JobEvent(job_id, "metrics_started", task_id=f"{job_id}:mangaone", site="mangaone", payload={"metrics_path": str(path)}))
    direct = (
        ("mangaone", "ticket", 4, 8),
        ("mangaone", "other", 4, 8),
        ("mangaone", "ticket", 4, 9),
        ("mangaone", "ticket", 9, 8),
        ("bookwalker", "ticket", 4, 8),
    )
    for index, (site, resource, item_id, source_id) in enumerate(direct):
        store.append_event(JobEvent(job_id, "grant_confirmed", task_id=f"{job_id}:{site}", site=site, item_id=item_id, source_id=source_id, resource=resource, resource_consumed=False, reason=f"direct-{index}"))
    result = JobResultPresenter(store).present(job_id)
    assert sum(grant.work_id is None for grant in result.grants) == 4
    assert any(grant.site == "bookwalker" for grant in result.grants)
    assert any(grant.resource == "other" for grant in result.grants)


def test_presenter_grant_overflow_is_stable_across_latest_window_rereads(tmp_path):
    store = JobStore(tmp_path / "management.sqlite")
    job_id = _job(store, _request("grant_only", keys=("key-a",)))
    task_id = f"{job_id}:mangaone"
    for work_id in (1, 2):
        store.append_event(JobEvent(job_id, "grant_confirmed", task_id=task_id, site="mangaone", key="key-a", item_id=work_id, source_id=work_id, resource="ticket", resource_consumed=False))
    presenter = JobResultPresenter(store, event_page_size=10)
    presenter.max_grant_facts = 1
    first = presenter.present(job_id)
    second = presenter.present(job_id)
    assert first.grant_facts_omitted == 1
    assert second.grant_facts_omitted == first.grant_facts_omitted
    assert second.current.item_id == 2


def test_presenter_default_limits_handle_50k_events_and_keep_live_context(tmp_path):
    """Bulk fixture proves bounded keyset reduction without dropping latest context."""
    store = JobStore(tmp_path / "management.sqlite")
    job_id = _job(store, _request("grant_only", keys=("key-a",)))
    task_id = f"{job_id}:mangaone"
    rows = [
        (
            f"{job_id}:grant:{index}", job_id, index, task_id, "mangaone",
            "2026-10-25T00:00:00+00:00", "grant_confirmed", None, "key-a",
            None, index, index, "ticket", "succeeded", 0, None, None, "{}",
        )
        for index in range(1, 50_001)
    ]
    with store._connect() as connection:
        connection.executemany(
            """INSERT INTO job_events(
               event_id, job_id, sequence, task_id, site, observed_at, event_type,
               phase, key_identity, work_key, item_id, source_id, resource,
               result, resource_consumed, reason, error_type, payload_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    presenter = JobResultPresenter(store)
    calls = 0
    result = presenter.present(job_id)
    while not result.event_page_complete:
        result = presenter.present(job_id)
        calls += 1
        assert calls <= 110
    assert result.event_cursor == 50_000
    assert result.current.item_id == 50_000
    assert result.grant_facts_omitted == 48_000
    assert len(result.grants) == 2_000
    assert result.current.source_id == 50_000


def test_presenter_uses_latest_candidate_result_for_replan(tmp_path):
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    store = JobStore(tmp_path / "management.sqlite")
    job_id = _job(store, _request("grant_only", metrics_root=metrics_root))
    task_id = f"{job_id}:mangaone"
    metrics_path = metrics_root / "mangaone.jsonl"
    records = [
        {"type": "batch", "event": "start", "site": "mangaone", "run_id": "r"},
        {"type": "candidate", "event": "result", "item_id": 4, "source_id": 8, "resource": "ticket", "result": "failed"},
        {"type": "grant_result", "work_id": 4, "resource": "ticket", "source_id": 8, "status": "OK", "resource_consumed": True},
        {"type": "candidate", "event": "result", "item_id": 4, "source_id": 8, "resource": "ticket", "result": "completed"},
        {"type": "grant_result", "work_id": 4, "resource": "ticket", "source_id": 8, "status": "OK", "resource_consumed": True},
        {"type": "batch_summary", "stop_reason": None},
    ]
    metrics_path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    store.append_event(JobEvent(job_id, "metrics_started", task_id=task_id, site="mangaone", payload={"metrics_path": str(metrics_path)}))
    result = JobResultPresenter(store).present(job_id)
    assert result.grants[0].outcome == "ok"


def test_presenter_direct_grant_event_is_minimal_and_tri_state(tmp_path):
    store = JobStore(tmp_path / "management.sqlite")
    job_id = _job(store, _request("grant_only", keys=("key-a",)))
    task_id = f"{job_id}:mangaone"
    store.append_event(JobEvent(
        job_id, "grant_confirmed", task_id=task_id, site="mangaone", key="key-a",
        item_id=12, source_id=8, resource="ticket", resource_consumed=True,
    ))
    store.append_event(JobEvent(
        job_id, "grant_unknown", task_id=task_id, site="mangaone", key="key-a",
        item_id=12, source_id=8, resource="ticket", resource_consumed=None,
        reason="confirmation unavailable",
    ))
    result = JobResultPresenter(store).present(job_id)
    assert len(result.grants) == 1
    assert result.grants[0].status == "unknown"
    assert result.grants[0].work_id is None
    assert result.grants[0].resource_consumed is None


def test_presenter_reads_partial_crlf_metrics_incrementally_and_restarts_on_recreate(tmp_path):
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    store = JobStore(tmp_path / "management.sqlite")
    job_id = _job(store, _request("batch", metrics_root=metrics_root))
    task_id = f"{job_id}:mangaone"
    metrics_path = metrics_root / "mangaone.jsonl"
    metrics_path.write_bytes(b'{"type":"batch","event":"start","site":"mangaone","run_id":"r"}\r\n')
    store.append_event(JobEvent(job_id, "metrics_started", task_id=task_id, site="mangaone", payload={"metrics_path": str(metrics_path)}))
    presenter = JobResultPresenter(store, metrics_max_read=32)
    first = presenter.present(job_id)
    assert first.batches[0].metrics_status == "partial"
    with metrics_path.open("ab") as stream:
        stream.write(b'{"type":"candidate","event":"result","result":"skipped","start_time":null}\r\n')
        stream.write(b'{"type":"batch_summary","candidates_started":0,"candidates_completed":0,"candidates_failed":0,"stop_reason":"no_candidates"}\r\n')
    second = presenter.present(job_id)
    assert second.batches[0].status == "no_candidates"
    assert second.batches[0].planned_skips == 1
    metrics_path.unlink()
    metrics_path.write_bytes(b'{"type":"batch","event":"start","site":"mangaone","run_id":"new"}\n{"type":"batch_summary","stop_reason":"no_candidates"}\n')
    third = presenter.present(job_id)
    assert third.batches[0].planned_skips is None
    assert third.batches[0].status == "no_candidates"
    metrics_path.unlink()
    fourth = presenter.present(job_id)
    assert fourth.batches[0].metrics_status == "missing"
    assert fourth.batches[0].status == "unknown"


def test_presenter_accepts_metrics_larger_than_total_cap_with_bounded_reads(tmp_path):
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    store = JobStore(tmp_path / "management.sqlite")
    job_id = _job(store, _request("batch", metrics_root=metrics_root))
    task_id = f"{job_id}:mangaone"
    metrics_path = metrics_root / "mangaone.jsonl"
    records = [{"type": "batch", "event": "start", "site": "mangaone", "run_id": "r"}]
    records.extend({"type": "access", "event": "request", "detail": "x" * 200} for _ in range(6000))
    records.append({"type": "batch_summary", "candidates_started": 0, "candidates_completed": 0, "candidates_failed": 0, "candidates_skipped": 0})
    metrics_path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    store.append_event(JobEvent(job_id, "metrics_started", task_id=task_id, site="mangaone", payload={"metrics_path": str(metrics_path)}))
    presenter = JobResultPresenter(store, metrics_max_read=4096)
    result = None
    for _ in range(400):
        result = presenter.present(job_id)
        if result.batches[0].metrics_status == "complete":
            break
    assert result is not None
    assert result.batches[0].metrics_status == "complete"
    assert result.batches[0].candidates_skipped == 0
    assert result.batches[0].planned_skips == 0
    assert result.batches[0].execution_skips == 0


def test_presenter_keeps_malformed_metrics_invalid_after_later_summary(tmp_path):
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    store = JobStore(tmp_path / "management.sqlite")
    job_id = _job(store, _request("batch", metrics_root=metrics_root))
    task_id = f"{job_id}:mangaone"
    metrics_path = metrics_root / "mangaone.jsonl"
    metrics_path.write_text(
        json.dumps({"type": "batch", "event": "start", "site": "mangaone", "run_id": "r"}) + "\n"
        + "{malformed\n",
        encoding="utf-8",
    )
    store.append_event(JobEvent(job_id, "metrics_started", task_id=task_id, site="mangaone", payload={"metrics_path": str(metrics_path)}))
    presenter = JobResultPresenter(store)
    first = presenter.present(job_id)
    assert first.batches[0].metrics_status == "invalid"
    with metrics_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"type": "batch_summary", "stop_reason": "failed"}) + "\n")
    second = presenter.present(job_id)
    assert second.batches[0].metrics_status == "invalid"
    assert second.batches[0].status == "unknown"
