"""Persistent P3 job queue and structured event storage.

The management database is deliberately separate from the crawler Catalog.  It
contains GUI/operator state only; worker processes append JSONL events and the
GUI imports those events idempotently while it polls the child process.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from screenshot_crawler.management.execution import (
    JobExecutionRequest,
    execution_request_payload,
)

SCHEMA_VERSION = 1
TERMINAL_JOB_STATES = frozenset(
    {"succeeded", "partial", "failed", "cancelled", "interrupted"}
)
ACTIVE_JOB_STATES = frozenset({"planning", "running"})


class ManagementSchemaError(RuntimeError):
    """The management DB is missing or uses an unsupported schema."""


class JobStateError(RuntimeError):
    """A requested queue transition is unsafe or invalid."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_URL_USERINFO = re.compile(r"(https?://)[^/@\s]+@", re.IGNORECASE)
_SECRET_QUERY = re.compile(
    r"([?&](?:token|access_token|api[_-]?key|password|secret|cookie)=[^&#\s]*)",
    re.IGNORECASE,
)
_AUTH_HEADER = re.compile(r"(Authorization\s*:\s*(?:Bearer|Basic)\s+)[^\s]+", re.IGNORECASE)


def sanitize_text(value: str) -> str:
    """Remove common credential forms from worker diagnostics and logs."""

    value = _URL_USERINFO.sub(r"\1<redacted>@", value)
    value = _SECRET_QUERY.sub(
        lambda match: match.group(1).split("=", 1)[0] + "=<redacted>", value
    )
    return _AUTH_HEADER.sub(r"\1<redacted>", value)


def _redact(value: Any, *, key: str = "") -> Any:
    lowered = key.lower()
    if lowered == "cdp_endpoint":
        return None
    if any(secret in lowered for secret in ("token", "password", "cookie", "secret")):
        return "<redacted>"
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {str(name): _redact(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, key=key) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class JobEvent:
    job_id: str
    event_type: str
    phase: str | None = None
    task_id: str | None = None
    site: str | None = None
    key: str | None = None
    work_key: str | None = None
    item_id: int | None = None
    source_id: int | None = None
    resource: str | None = None
    result: str | None = None
    resource_consumed: bool | None = None
    reason: str | None = None
    error_type: str | None = None
    payload: dict[str, Any] | None = None
    event_id: str | None = None
    sequence: int | None = None

    def as_dict(self, *, sequence: int, observed_at: str | None = None) -> dict[str, Any]:
        return {
            "event_id": self.event_id or f"{self.job_id}:{sequence}",
            "sequence": sequence,
            "job_id": self.job_id,
            "task_id": self.task_id,
            "site": self.site,
            "observed_at": observed_at or _now(),
            "event_type": self.event_type,
            "phase": self.phase,
            "key": self.key,
            "work_key": self.work_key,
            "item_id": self.item_id,
            "source_id": self.source_id,
            "resource": self.resource,
            "result": self.result,
            "resource_consumed": self.resource_consumed,
            "reason": sanitize_text(self.reason) if self.reason is not None else None,
            "error_type": self.error_type,
            "payload": _redact(self.payload or {}),
        }


class JsonlEventSink:
    """Append-only worker event file with safe sequence allocation."""

    def __init__(self, path: str | Path, job_id: str) -> None:
        self.path = Path(path)
        self.job_id = job_id
        self._lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sequence = self._last_complete_sequence()

    def _last_complete_sequence(self) -> int:
        if not self.path.is_file():
            return 0
        last = 0
        with self.path.open("rb") as stream:
            for raw in stream:
                if not raw.endswith(b"\n"):
                    break
                try:
                    value = json.loads(raw)
                    last = max(last, int(value.get("sequence", 0)))
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue
        return last

    def emit(self, event: JobEvent | str, **fields: Any) -> dict[str, Any]:
        if isinstance(event, str):
            event = JobEvent(self.job_id, event, **fields)
        with self._lock:
            self._sequence += 1
            value = event.as_dict(sequence=self._sequence)
            with self.path.open("ab") as stream:
                stream.write((_json(value) + "\n").encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            return value


def read_complete_jsonl(path: str | Path) -> tuple[dict[str, Any], ...]:
    """Read complete event lines and ignore a partial trailing line."""

    target = Path(path)
    if not target.is_file():
        return ()
    events: list[dict[str, Any]] = []
    with target.open("rb") as stream:
        for raw in stream:
            if not raw.endswith(b"\n"):
                break
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
    return tuple(events)


class JobStore:
    """Single-writer-friendly SQLite store for GUI job metadata."""

    def __init__(self, path: str | Path = "output/management/management.sqlite") -> None:
        self.path = Path(path)
        self._lock = RLock()
        self._event_offsets: dict[str, int] = {}

    @property
    def logs_root(self) -> Path:
        return self.path.parent / "logs"

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.is_file()
        try:
            connection = sqlite3.connect(self.path)
        except sqlite3.Error as exc:
            raise ManagementSchemaError(f"management DB is not a SQLite database: {self.path}") from exc
        with connection:
            connection.row_factory = sqlite3.Row
            if exists:
                try:
                    row = connection.execute(
                        "SELECT schema_version FROM management_meta LIMIT 1"
                    ).fetchone()
                except sqlite3.Error as exc:
                    raise ManagementSchemaError(
                        f"management DB schema is invalid: {self.path}"
                    ) from exc
                if row is None or int(row[0]) != SCHEMA_VERSION:
                    raise ManagementSchemaError(
                        f"unsupported management DB schema in {self.path}"
                    )
                return
            connection.executescript(
                """
                CREATE TABLE management_meta(schema_version INTEGER NOT NULL);
                INSERT INTO management_meta(schema_version) VALUES (1);
                CREATE TABLE jobs(
                    job_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    selected_keys_json TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    planned_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    worker_pid INTEGER,
                    worker_start_token TEXT,
                    heartbeat_at TEXT,
                    original_job_id TEXT,
                    summary_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE job_tasks(
                    task_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    site TEXT NOT NULL,
                    selected_keys_json TEXT NOT NULL,
                    resource TEXT,
                    mode TEXT,
                    limit_count INTEGER,
                    state TEXT NOT NULL,
                    planned_attempts INTEGER NOT NULL DEFAULT 0,
                    observed_attempts INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    unknown_count INTEGER NOT NULL DEFAULT 0,
                    metrics_path TEXT,
                    stdout_path TEXT,
                    stderr_path TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    UNIQUE(job_id, site)
                );
                CREATE TABLE job_events(
                    event_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    sequence INTEGER NOT NULL,
                    task_id TEXT,
                    site TEXT,
                    observed_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    phase TEXT,
                    key_identity TEXT,
                    work_key TEXT,
                    item_id INTEGER,
                    source_id INTEGER,
                    resource TEXT,
                    result TEXT,
                    resource_consumed INTEGER,
                    reason TEXT,
                    error_type TEXT,
                    payload_json TEXT NOT NULL,
                    UNIQUE(job_id, sequence)
                );
                CREATE INDEX idx_jobs_state ON jobs(state);
                CREATE INDEX idx_task_job ON job_tasks(job_id);
                CREATE INDEX idx_events_job_seq ON job_events(job_id, sequence);
                """
            )

    def backup_to(self, destination: str | Path) -> Path:
        """Create a one-shot management DB backup without overwriting files."""

        self.initialize()
        target = Path(destination)
        if target.exists():
            raise FileExistsError(f"refusing to overwrite management backup: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source = self._connect()
        try:
            backup = sqlite3.connect(target)
            try:
                source.backup(backup)
                backup.commit()
            finally:
                backup.close()
        finally:
            source.close()
        return target

    def _connect(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise ManagementSchemaError(f"management DB is not initialized: {self.path}")
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def create_job(
        self,
        request: JobExecutionRequest,
        *,
        management_root: str | Path | None = None,
        original_job_id: str | None = None,
    ) -> tuple[str, tuple[str, ...]]:
        self.initialize()
        job_id = str(uuid.uuid4())
        root = Path(management_root) if management_root else self.path.parent
        job_dir = root / "logs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        payload = _redact(execution_request_payload(request))
        now = _now()
        tasks = tuple(sorted(request.sites))
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO jobs(job_id, action, selected_keys_json, request_json,
                   planned_fingerprint, state, requested_at, confirmed_at, original_job_id)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (job_id, request.action, _json(sorted(request.selected_keys)), _json(payload),
                 request.plan_fingerprint, "queued", now, now, original_job_id),
            )
            for site in tasks:
                keys = dict(request.keys_by_site).get(site, ())
                resource = dict(request.resources_by_site).get(site, request.resource)
                task_id = f"{job_id}:{site}"
                connection.execute(
                    """INSERT INTO job_tasks(task_id, job_id, site, selected_keys_json,
                       resource, mode, limit_count, state, metrics_path, stdout_path, stderr_path)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (task_id, job_id, site, _json(list(keys)), resource, request.mode,
                     request.limit, "not_started", str(Path(request.metrics_root or root / "metrics") / site),
                     str(job_dir / "stdout.log"), str(job_dir / "stderr.log")),
                )
        return job_id, tasks

    def request_for(self, job_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT request_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return json.loads(row[0])

    def job_dir(self, job_id: str) -> Path:
        return self.logs_root / job_id

    def set_worker_identity(self, job_id: str, *, pid: int, token: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET worker_pid=?, worker_start_token=?, heartbeat_at=?, state='running' WHERE job_id=? AND state='queued'",
                (pid, token, _now(), job_id),
            )

    def heartbeat(self, job_id: str, *, token: str) -> bool:
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE jobs SET heartbeat_at=? WHERE job_id=? AND worker_start_token=? AND state IN ('planning','running')",
                (_now(), job_id, token),
            )
        return result.rowcount == 1

    def record_worker_heartbeat(self, job_id: str, *, token: str, observed_at: str) -> bool:
        """Persist the timestamp written by the worker, never GUI wall time."""

        with self._connect() as connection:
            result = connection.execute(
                "UPDATE jobs SET heartbeat_at=? WHERE job_id=? AND worker_start_token=? AND state IN ('planning','running')",
                (observed_at, job_id, token),
            )
        return result.rowcount == 1

    def set_state(self, job_id: str, state: str, *, summary: dict[str, Any] | None = None) -> None:
        if state not in {"queued", "planning", "running", *TERMINAL_JOB_STATES}:
            raise JobStateError(f"unknown job state: {state}")
        ended = _now() if state in TERMINAL_JOB_STATES else None
        with self._connect() as connection:
            if summary is None:
                connection.execute(
                    "UPDATE jobs SET state=?, ended_at=COALESCE(?, ended_at) WHERE job_id=?",
                    (state, ended, job_id),
                )
            else:
                connection.execute(
                    "UPDATE jobs SET state=?, summary_json=?, ended_at=COALESCE(?, ended_at) WHERE job_id=?",
                    (state, _json(_redact(summary)), ended, job_id),
                )

    def set_task_state(self, task_id: str, state: str) -> None:
        ended = _now() if state in TERMINAL_JOB_STATES else None
        with self._connect() as connection:
            connection.execute(
                "UPDATE job_tasks SET state=?, started_at=COALESCE(started_at, ?), ended_at=COALESCE(?, ended_at) WHERE task_id=?",
                (state, _now() if state in {"planning", "running"} else None, ended, task_id),
            )

    def append_event(self, value: JobEvent | dict[str, Any]) -> bool:
        if isinstance(value, JobEvent):
            if value.sequence is None:
                with self._connect() as connection:
                    row = connection.execute(
                        "SELECT COALESCE(MAX(sequence),0) FROM job_events WHERE job_id=?",
                        (value.job_id,),
                    ).fetchone()
                sequence = int(row[0]) + 1
            else:
                sequence = value.sequence
            value = value.as_dict(sequence=sequence)
        event_id = str(value.get("event_id") or "")
        job_id = str(value.get("job_id") or "")
        if not event_id or not job_id:
            raise ValueError("event requires event_id and job_id")
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                """SELECT event_id, job_id, sequence, event_type, result,
                          resource_consumed, reason, payload_json
                   FROM job_events
                   WHERE event_id=? OR (job_id=? AND sequence=?)""",
                (event_id, job_id, int(value.get("sequence", 0))),
            ).fetchone()
            if existing is not None:
                incoming_payload = _json(_redact(value.get("payload") or {}))
                same = (
                    existing["event_id"] == event_id
                    and existing["job_id"] == job_id
                    and int(existing["sequence"]) == int(value.get("sequence", 0))
                    and existing["event_type"] == str(value.get("event_type") or "unknown")
                    and existing["result"] == value.get("result")
                    and existing["resource_consumed"] == (
                        None
                        if value.get("resource_consumed") is None
                        else int(bool(value["resource_consumed"]))
                    )
                    and existing["reason"] == value.get("reason")
                    and existing["payload_json"] == incoming_payload
                )
                if same:
                    return False
                raise JobStateError(
                    f"conflicting event identity or sequence for job {job_id}: {event_id}"
                )
            cursor = connection.execute(
                """INSERT INTO job_events(
                   event_id, job_id, sequence, task_id, site, observed_at, event_type,
                   phase, key_identity, work_key, item_id, source_id, resource,
                   result, resource_consumed, reason, error_type, payload_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, job_id, int(value.get("sequence", 0)), value.get("task_id"), value.get("site"),
                 str(value.get("observed_at") or _now()), str(value.get("event_type") or "unknown"),
                 value.get("phase"), value.get("key"), value.get("work_key"), value.get("item_id"),
                 value.get("source_id"), value.get("resource"), value.get("result"),
                 None if value.get("resource_consumed") is None else int(bool(value["resource_consumed"])),
                 sanitize_text(str(value.get("reason"))) if value.get("reason") is not None else None,
                 value.get("error_type"), _json(_redact(value.get("payload") or {}))),
            )
            if cursor.rowcount == 1 and value.get("task_id"):
                task_id = value["task_id"]
                event_type = value.get("event_type")
                result = value.get("result")
                task_row = connection.execute(
                    "SELECT state FROM job_tasks WHERE task_id=?", (task_id,)
                ).fetchone()
                task_state = task_row["state"] if task_row is not None else None
                if event_type == "task_started":
                    if task_state not in TERMINAL_JOB_STATES:
                        connection.execute(
                            "UPDATE job_tasks SET state='running', started_at=COALESCE(started_at, ?) WHERE task_id=?",
                            (_now(), task_id),
                        )
                elif event_type == "candidate_started":
                    connection.execute(
                        "UPDATE job_tasks SET observed_attempts=observed_attempts+1 WHERE task_id=?",
                        (task_id,),
                    )
                elif event_type == "candidate_finished":
                    column = {
                        "succeeded": "success_count",
                        "failed": "failed_count",
                        "skipped": "skipped_count",
                    }.get(str(result))
                    if column is not None:
                        connection.execute(
                            f"UPDATE job_tasks SET {column}={column}+1 WHERE task_id=?",
                            (task_id,),
                        )
                elif event_type == "grant_unknown":
                    connection.execute(
                        "UPDATE job_tasks SET unknown_count=unknown_count+1 WHERE task_id=?",
                        (task_id,),
                    )
                elif event_type in {"task_finished", "task_failed"}:
                    state = {
                        "succeeded": "succeeded",
                        "cancelled": "cancelled",
                    }.get(str(result), "failed")
                    if task_state not in TERMINAL_JOB_STATES:
                        connection.execute(
                            "UPDATE job_tasks SET state=?, ended_at=? WHERE task_id=?",
                            (state, _now(), task_id),
                        )
                if event_type in {"metrics_started", "batch_finished"}:
                    payload = value.get("payload") or {}
                    metrics_path = payload.get("metrics_path") if isinstance(payload, dict) else None
                    if isinstance(metrics_path, str) and metrics_path:
                        connection.execute(
                            "UPDATE job_tasks SET metrics_path=? WHERE task_id=?",
                            (metrics_path, task_id),
                        )
        return cursor.rowcount == 1

    def import_events(self, job_id: str, *, max_events: int = 500) -> int:
        """Import a bounded complete-line batch from the worker append log."""

        inserted = 0
        path = self.job_dir(job_id) / "events.jsonl"
        offset = self._event_offsets.get(job_id, 0)
        values: list[dict[str, Any]] = []
        next_offset = offset
        if path.is_file():
            with path.open("rb") as stream:
                stream.seek(offset)
                while len(values) < max_events:
                    line_start = stream.tell()
                    raw = stream.readline()
                    if not raw or not raw.endswith(b"\n"):
                        next_offset = line_start
                        break
                    next_offset = stream.tell()
                    try:
                        value = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict):
                        values.append(value)
                else:
                    next_offset = stream.tell()
        self._event_offsets[job_id] = next_offset
        for value in values:
            if value.get("job_id") != job_id:
                continue
            inserted += int(self.append_event(value))
        return inserted

    def events_pending(self, job_id: str) -> bool:
        path = self.job_dir(job_id) / "events.jsonl"
        try:
            return path.stat().st_size > self._event_offsets.get(job_id, 0)
        except OSError:
            return False

    def request_cancel(self, job_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET cancel_requested=1 WHERE job_id=? AND state IN ('queued','planning','running')",
                (job_id,),
            )
        self.job_dir(job_id).mkdir(parents=True, exist_ok=True)
        sentinel = self.job_dir(job_id) / "cancel.request"
        temporary = sentinel.with_suffix(".tmp")
        temporary.write_text(_now(), encoding="utf-8")
        os.replace(temporary, sentinel)

    def cancel_requested(self, job_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT cancel_requested FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return bool(row and row[0]) or (self.job_dir(job_id) / "cancel.request").is_file()

    def mark_interrupted(self, job_id: str, *, reason: str = "worker identity unavailable") -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE job_tasks
                   SET state='interrupted', ended_at=?, unknown_count=unknown_count+1
                   WHERE job_id=? AND state IN ('planning','running')""",
                (_now(), job_id),
            )
        self.set_state(job_id, "interrupted", summary={"reason": reason, "resource_consumed": None})
        self.append_event(JobEvent(
            job_id,
            "process_exited",
            result="interrupted",
            reason=reason,
            resource_consumed=None,
            event_id=f"{job_id}:controller:interrupted",
            sequence=-4,
        ))

    def get_job(self, job_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return row

    def list_jobs(self, *, limit: int = 100) -> tuple[sqlite3.Row, ...]:
        with self._connect() as connection:
            return tuple(connection.execute(
                "SELECT * FROM jobs ORDER BY requested_at DESC LIMIT ?", (limit,)
            ).fetchall())

    def list_tasks(self, job_id: str) -> tuple[sqlite3.Row, ...]:
        with self._connect() as connection:
            return tuple(connection.execute(
                "SELECT * FROM job_tasks WHERE job_id=? ORDER BY site", (job_id,)
            ).fetchall())

    def list_events(self, job_id: str, *, limit: int = 500) -> tuple[sqlite3.Row, ...]:
        with self._connect() as connection:
            return tuple(connection.execute(
                "SELECT * FROM job_events WHERE job_id=? ORDER BY sequence LIMIT ?", (job_id, limit)
            ).fetchall())

    def terminal_event_summary(self, job_id: str) -> dict[str, Any]:
        """Reduce terminal facts in SQL without loading an unbounded event log."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_type, result, task_id FROM job_events WHERE job_id=?",
                (job_id,),
            ).fetchall()
            expected = connection.execute(
                "SELECT COUNT(*) FROM job_tasks WHERE job_id=?", (job_id,)
            ).fetchone()[0]
        finished = {
            row["task_id"] for row in rows
            if row["event_type"] == "task_finished"
            and row["result"] == "succeeded"
            and row["task_id"]
        }
        return {
            "expected_tasks": int(expected),
            "finished_tasks": len(finished),
            "has_success": bool(finished),
            "has_failure": any(
                row["event_type"] == "task_failed"
                or (row["event_type"] == "process_exited" and row["result"] not in {None, "succeeded"})
                for row in rows
            ),
            "job_succeeded": any(
                row["event_type"] == "job_finished" and row["result"] == "succeeded"
                for row in rows
            ),
            "process_succeeded": any(
                row["event_type"] == "process_exited" and row["result"] == "succeeded"
                for row in rows
            ),
        }

    def queued_jobs(self) -> tuple[sqlite3.Row, ...]:
        with self._connect() as connection:
            return tuple(connection.execute(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY requested_at, job_id"
            ).fetchall())


__all__ = [
    "ACTIVE_JOB_STATES",
    "SCHEMA_VERSION",
    "TERMINAL_JOB_STATES",
    "JobEvent",
    "JobStateError",
    "JobStore",
    "JsonlEventSink",
    "ManagementSchemaError",
    "read_complete_jsonl",
    "sanitize_text",
]
