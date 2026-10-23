import asyncio
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from screenshot_crawler.management.execution import JobExecutionRequest
from screenshot_crawler.management.job_controller import JobController
from screenshot_crawler.management.job_worker import run_job
from screenshot_crawler.management.jobs import (
    JobEvent,
    JobStateError,
    JobStore,
    JsonlEventSink,
    ManagementSchemaError,
    read_complete_jsonl,
    sanitize_text,
)
from screenshot_crawler.management.process_identity import process_is_alive, process_start_identity


def _request() -> JobExecutionRequest:
    return JobExecutionRequest(
        action="batch",
        selected_keys=frozenset({"key-a", "key-b"}),
        sites=("mangaone", "magapoke"),
        keys_by_site=(("mangaone", ("key-a",)), ("magapoke", ("key-b",))),
        runtime_path="runtime.yaml",
        env_file=".env",
        output_root="output/batch",
        library_dir="output/Books",
        metrics_root="output/metrics",
        plan_fingerprint="confirmed",
    )


def test_management_db_schema_and_job_tasks_are_separate(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    store.initialize()
    job_id, sites = store.create_job(_request())
    assert sites == ("magapoke", "mangaone")
    row = store.get_job(job_id)
    assert row["state"] == "queued"
    assert [task["site"] for task in store.list_tasks(job_id)] == ["magapoke", "mangaone"]
    assert not (tmp_path / "catalog.sqlite").exists()


def test_management_schema_mismatch_is_rejected_without_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "management.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE management_meta(schema_version INTEGER)")
        connection.execute("INSERT INTO management_meta VALUES (999)")
    with pytest.raises(ManagementSchemaError):
        JobStore(path).initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT schema_version FROM management_meta").fetchone()[0] == 999


def test_management_backup_is_one_shot_and_refuses_overwrite(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    store.initialize()
    store.create_job(_request())
    backup = store.backup_to(tmp_path / "backup" / "management.sqlite")
    assert backup.is_file()
    with pytest.raises(FileExistsError):
        store.backup_to(backup)


def test_jsonl_partial_tail_and_duplicate_import_are_safe(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    store.initialize()
    job_id, _ = store.create_job(_request())
    sink = JsonlEventSink(store.job_dir(job_id) / "events.jsonl", job_id)
    event = sink.emit(JobEvent(job_id, "candidate_finished", result="succeeded"))
    with (store.job_dir(job_id) / "events.jsonl").open("ab") as stream:
        stream.write(b'{"event_id":"incomplete"')
    assert len(read_complete_jsonl(store.job_dir(job_id) / "events.jsonl")) == 1
    assert store.import_events(job_id) == 1
    assert store.import_events(job_id) == 0
    assert store.list_events(job_id)[0]["event_id"] == event["event_id"]


def test_event_import_is_bounded_and_resumes_from_byte_offset(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    store.initialize()
    job_id, _ = store.create_job(_request())
    sink = JsonlEventSink(store.job_dir(job_id) / "events.jsonl", job_id)
    for sequence in range(700):
        sink.emit(JobEvent(job_id, "diagnostic", payload={"n": sequence}))
    assert store.import_events(job_id, max_events=500) == 500
    assert len(store.list_events(job_id, limit=1000)) == 500
    assert store.import_events(job_id, max_events=500) == 200
    assert len(store.list_events(job_id, limit=1000)) == 700
    assert store.import_events(job_id, max_events=500) == 0


def test_terminal_summary_scans_beyond_gui_event_page_limit(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    store.initialize()
    job_id, _ = store.create_job(_request())
    sink = JsonlEventSink(store.job_dir(job_id) / "events.jsonl", job_id)
    task_id = f"{job_id}:mangaone"
    sink.emit(JobEvent(job_id, "task_started", task_id=task_id, site="mangaone"))
    for index in range(1200):
        sink.emit(JobEvent(job_id, "diagnostic", task_id=task_id, site="mangaone", payload={"n": index}))
    sink.emit(JobEvent(job_id, "task_finished", task_id=task_id, site="mangaone", result="succeeded"))
    sink.emit(JobEvent(job_id, "job_finished", result="succeeded"))
    sink.emit(JobEvent(job_id, "process_exited", result="succeeded"))
    while store.events_pending(job_id):
        store.import_events(job_id, max_events=500)
    summary = store.terminal_event_summary(job_id)
    assert summary["finished_tasks"] == 1
    assert summary["job_succeeded"] and summary["process_succeeded"]


def test_event_import_updates_task_progress_once(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    store.initialize()
    job_id, _ = store.create_job(_request())
    sink = JsonlEventSink(store.job_dir(job_id) / "events.jsonl", job_id)
    task_id = f"{job_id}:mangaone"
    sink.emit(JobEvent(job_id, "task_started", task_id=task_id, site="mangaone"))
    sink.emit(JobEvent(job_id, "candidate_started", task_id=task_id, site="mangaone"))
    sink.emit(JobEvent(job_id, "candidate_finished", task_id=task_id, site="mangaone", result="succeeded"))
    sink.emit(JobEvent(job_id, "task_finished", task_id=task_id, site="mangaone", result="succeeded"))
    assert store.import_events(job_id) == 4
    assert store.import_events(job_id) == 0
    task = next(item for item in store.list_tasks(job_id) if item["task_id"] == task_id)
    assert task["state"] == "succeeded"
    assert task["observed_attempts"] == 1
    assert task["success_count"] == 1


def test_out_of_order_task_started_cannot_regress_terminal_state(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    store.initialize()
    job_id, _ = store.create_job(_request())
    task_id = f"{job_id}:mangaone"
    store.append_event(JobEvent(job_id, "task_finished", task_id=task_id, site="mangaone", result="succeeded"))
    store.append_event(JobEvent(job_id, "task_started", task_id=task_id, site="mangaone"))
    task = next(item for item in store.list_tasks(job_id) if item["task_id"] == task_id)
    assert task["state"] == "succeeded"


def test_metrics_event_updates_task_path_and_no_candidates_reason(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    store.initialize()
    job_id, _ = store.create_job(_request())
    sink = JsonlEventSink(store.job_dir(job_id) / "events.jsonl", job_id)
    task_id = f"{job_id}:mangaone"
    sink.emit(JobEvent(
        job_id,
        "task_started",
        task_id=task_id,
        site="mangaone",
    ))
    metrics_path = str(tmp_path / "metrics" / "20261024-mangaone.jsonl")
    sink.emit(JobEvent(
        job_id,
        "metrics_started",
        task_id=task_id,
        site="mangaone",
        payload={"metrics_path": metrics_path},
    ))
    sink.emit(JobEvent(
        job_id,
        "task_finished",
        task_id=task_id,
        site="mangaone",
        result="succeeded",
        reason="no_candidates",
        payload={"metrics_path": metrics_path, "candidate_count": 0},
    ))
    assert store.import_events(job_id) == 3
    task = next(item for item in store.list_tasks(job_id) if item["task_id"] == task_id)
    assert task["metrics_path"] == metrics_path
    events = store.list_events(job_id)
    assert events[-1]["reason"] == "no_candidates"


def test_event_payload_redacts_secret_like_fields(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    store.initialize()
    job_id, _ = store.create_job(_request())
    store.append_event(JobEvent(job_id, "warning", payload={"token": "secret-value", "safe": "ok"}))
    payload = store.list_events(job_id)[0]["payload_json"]
    assert "secret-value" not in payload
    assert "<redacted>" in payload


def test_event_text_sanitizes_credentials_in_reason_and_payload(tmp_path: Path) -> None:
    value = "https://user:pass@example.test/path?token=abc Authorization: Bearer xyz"
    assert "pass" not in sanitize_text(value)
    assert "abc" not in sanitize_text(value)
    assert "xyz" not in sanitize_text(value)
    store = JobStore(tmp_path / "management.sqlite")
    store.initialize()
    job_id, _ = store.create_job(_request())
    store.append_event(JobEvent(job_id, "error", reason=value, payload={"detail": value}))
    event = store.list_events(job_id)[0]
    assert "pass" not in (event["reason"] + event["payload_json"])
    assert "abc" not in (event["reason"] + event["payload_json"])
    assert "xyz" not in (event["reason"] + event["payload_json"])


def test_worker_log_copy_sanitizes_stream_text() -> None:
    source = io.StringIO("Authorization: Bearer xyz https://u:p@example.test/?token=abc\n")
    target = io.StringIO()
    errors: list[BaseException] = []
    JobController._copy_log(source, target, errors)
    assert not errors
    assert "xyz" not in target.getvalue()
    assert "abc" not in target.getvalue()
    assert "u:p" not in target.getvalue()


def test_conflicting_event_identity_is_rejected(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    store.initialize()
    job_id, _ = store.create_job(_request())
    event = JobEvent(job_id, "warning", event_id=f"{job_id}:event", sequence=1, reason="first")
    assert store.append_event(event)
    assert not store.append_event(event)
    with pytest.raises(JobStateError):
        store.append_event(
            JobEvent(job_id, "warning", event_id=f"{job_id}:event", sequence=1, reason="changed")
        )


def test_job_controller_does_not_auto_start_queued_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable="python")
    job_id = controller.queue(_request())
    assert store.get_job(job_id)["state"] == "queued"
    assert controller.process is None
    controller.close()


def test_queued_cancel_is_not_started_and_force_stop_is_interrupted(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable="python")
    queued_id = controller.queue(_request())
    store.request_cancel(queued_id)
    assert controller.start_next() is None
    assert store.get_job(queued_id)["state"] == "cancelled"

    active_id = controller.queue(_request())

    class FakeProcess:
        pid = 1001
        returncode = None

        def kill(self) -> None:
            self.returncode = -9

        def wait(self, timeout: float | None = None) -> int:
            return -9

        def poll(self) -> int:
            return self.returncode

    controller.process = FakeProcess()  # type: ignore[assignment]
    controller.active_job_id = active_id
    controller.force_stop()
    assert store.get_job(active_id)["state"] == "interrupted"
    assert json.loads(store.get_job(active_id)["summary_json"])["resource_consumed"] is None
    controller.close()


def test_only_one_controller_can_own_a_management_db(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    first = JobController(store, python_executable="python")
    with pytest.raises(RuntimeError, match="already owns"):
        JobController(store, python_executable="python")
    first.close()


def test_management_lease_blocks_separate_process_and_recovers_after_exit(tmp_path: Path) -> None:
    path = tmp_path / "management.sqlite"
    script = (
        "import sys,time; "
        "from screenshot_crawler.management.jobs import JobStore; "
        "from screenshot_crawler.management.job_controller import JobController; "
        "c=JobController(JobStore(sys.argv[1]), python_executable=sys.executable); "
        "print('ready', flush=True); time.sleep(30)"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        with pytest.raises(RuntimeError, match="already owns"):
            JobController(JobStore(path), python_executable=sys.executable)
    finally:
        child.terminate()
        child.wait(timeout=10)
    recovered = None
    for _ in range(20):
        try:
            recovered = JobController(JobStore(path), python_executable=sys.executable)
            break
        except RuntimeError:
            time.sleep(0.05)
    assert recovered is not None
    recovered.close()


def test_process_liveness_probe_is_nondestructive_for_live_child() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    try:
        assert process_is_alive(child.pid)
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=10)


def test_controller_runs_real_worker_subprocess_and_imports_failure_events(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable=sys.executable)
    job_id = controller.queue(_request())
    assert controller.start_next() == job_id
    deadline = time.monotonic() + 20
    state = None
    while time.monotonic() < deadline:
        state = controller.poll()
        if state is not None:
            break
        time.sleep(0.05)
    assert state == "failed"
    store.import_events(job_id)
    assert any(event["event_type"] == "process_exited" for event in store.list_events(job_id))
    identity = json.loads((store.job_dir(job_id) / "worker.identity").read_text(encoding="utf-8"))
    assert identity["token"].startswith("worker-")
    assert identity["start_identity"]
    heartbeat = json.loads(
        (store.job_dir(job_id) / "worker.heartbeat.json").read_text(encoding="utf-8")
    )
    assert heartbeat["token"] == identity["token"]
    assert heartbeat["observed_at"]
    assert (store.job_dir(job_id) / "stdout.log").is_file()
    controller.close()


def test_finished_worker_with_partial_event_tail_is_interrupted(tmp_path: Path) -> None:
    """A crash during JSONL append must never spin or become success."""

    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable=sys.executable)
    job_id = controller.queue(_request())
    token = "worker-partial-tail"
    job_dir = store.job_dir(job_id)
    job_dir.joinpath("worker.identity").write_text(
        json.dumps({
            "pid": os.getpid(),
            "token": token,
            "start_identity": process_start_identity(os.getpid()),
        }),
        encoding="utf-8",
    )
    job_dir.joinpath("events.jsonl").write_bytes(b'{"job_id":"' + job_id.encode() + b'"')

    class FinishedProcess:
        pid = os.getpid()
        returncode = 0

        def poll(self) -> int:
            return self.returncode

    controller.process = FinishedProcess()  # type: ignore[assignment]
    controller.active_job_id = job_id
    controller.worker_token = token
    assert controller.poll() == "interrupted"
    assert store.get_job(job_id)["state"] == "interrupted"
    controller.close()


def test_supervision_db_failure_stops_live_worker_via_filesystem_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable=sys.executable)
    job_id = controller.queue(_request())

    class LiveProcess:
        pid = os.getpid()
        returncode = None

        def poll(self) -> int | None:
            return self.returncode

    live_process = LiveProcess()
    controller.process = live_process  # type: ignore[assignment]
    controller.active_job_id = job_id
    controller.worker_token = "worker-db-failure"

    def fail_import(*args: object, **kwargs: object) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "import_events", fail_import)
    assert controller.poll() is None
    assert (store.job_dir(job_id) / "cancel.request").is_file()
    assert (store.job_dir(job_id) / "supervision-error.json").is_file()
    # Recovery of SQLite must not turn the already-unverified worker into
    # success after it exits.
    live_process.returncode = 0
    assert controller.poll() == "interrupted"
    assert store.get_job(job_id)["state"] == "interrupted"
    controller.close()


def test_finished_worker_with_undrained_log_reader_is_unverified(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable=sys.executable)
    job_id = controller.queue(_request())
    token = "worker-undrained-log"
    job_dir = store.job_dir(job_id)
    job_dir.joinpath("worker.identity").write_text(
        json.dumps({
            "pid": os.getpid(), "token": token,
            "start_identity": process_start_identity(os.getpid()),
        }), encoding="utf-8",
    )

    class FinishedProcess:
        pid = os.getpid()
        returncode = 0

        def poll(self) -> int:
            return 0

    class UndrainedThread:
        def join(self, timeout: float | None = None) -> None:
            return None

        def is_alive(self) -> bool:
            return True

    controller.process = FinishedProcess()  # type: ignore[assignment]
    controller.active_job_id = job_id
    controller.worker_token = token
    controller._log_threads = (UndrainedThread(), UndrainedThread())  # type: ignore[assignment]
    controller._log_handles = (io.StringIO(), io.StringIO())
    assert controller.poll() == "interrupted"
    assert store.get_job(job_id)["state"] == "interrupted"
    controller.close()


def test_start_gate_failure_kills_child_and_marks_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable=sys.executable)
    job_id = controller.queue(_request())
    original_write_gate = controller._write_gate

    def fail_go(path: Path, value: str) -> None:
        if value == "go":
            raise OSError("synthetic gate failure")
        original_write_gate(path, value)

    class FakeProcess:
        pid = os.getpid()
        returncode = None
        stdout = io.StringIO()
        stderr = io.StringIO()

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

        def wait(self, timeout: float | None = None) -> int:
            self.returncode = -9
            return -9

    fake = FakeProcess()
    popen_kwargs: dict[str, object] = {}
    monkeypatch.setenv("CRAWLER_CDP_ENDPOINT_OVERRIDE", "http://inherited.invalid")
    def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
        popen_kwargs.update(kwargs)
        return fake
    monkeypatch.setattr(
        "screenshot_crawler.management.job_controller.subprocess.Popen",
        fake_popen,
    )
    monkeypatch.setattr(controller, "_write_gate", fail_go)
    with pytest.raises(OSError, match="gate failure"):
        controller.start_job(job_id)
    assert fake.returncode == -9
    assert "CRAWLER_CDP_ENDPOINT_OVERRIDE" not in popen_kwargs["env"]  # type: ignore[operator]
    assert controller.process is None
    assert store.get_job(job_id)["state"] == "interrupted"
    controller.close()


def test_worker_writes_structured_success_and_unknown_cancel_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = JobStore(tmp_path / "management.sqlite")
    store.initialize()
    job_id, _ = store.create_job(_request())
    payload = store.request_for(job_id)
    async def fake_run(request, *, event_sink, cancel_check):
        event_sink("task_started", payload={"site": "mangaone"})
        event_sink("candidate_started", site="mangaone", key="key-a")
        event_sink("candidate_finished", site="mangaone", key="key-a", result="succeeded")
        event_sink("task_finished", payload={"site": "mangaone"}, result="succeeded")

    monkeypatch.setattr("screenshot_crawler.management.job_worker._run", fake_run)
    assert asyncio.run(
        run_job(
            job_id,
            payload,
            worker_token="worker-token",
            job_dir=store.job_dir(job_id),
        )
    ) == 0
    store.import_events(job_id)
    assert store.list_events(job_id)[-1]["event_type"] == "process_exited"
    assert store.list_events(job_id)[-1]["result"] == "succeeded"
    assert store.list_tasks(job_id)[1]["state"] == "succeeded"

    cancelled_id, _ = store.create_job(_request())
    store.request_cancel(cancelled_id)

    async def cancelled_run(request, *, event_sink, cancel_check):
        if cancel_check():
            raise WorkerCancelled("cooperative stop requested")

    from screenshot_crawler.execution_worker import WorkerCancelled

    monkeypatch.setattr("screenshot_crawler.management.job_worker._run", cancelled_run)
    assert asyncio.run(
        run_job(
            cancelled_id,
            store.request_for(cancelled_id),
            worker_token="worker-token",
            job_dir=store.job_dir(cancelled_id),
        )
    ) == 0
    store.import_events(cancelled_id)
    assert any(event["event_type"] == "job_finished" for event in store.list_events(cancelled_id))
