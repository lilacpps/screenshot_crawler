"""Qt-free, bounded reduction of one management job for GUI views."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from screenshot_crawler.management.jobs import sanitize_text


@dataclass(frozen=True, slots=True)
class JobContext:
    site: str | None = None
    key: str | None = None
    item_id: int | None = None
    source_id: int | None = None
    resource: str | None = None
    phase: str | None = None


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    site: str
    state: str
    observed_attempts: int
    success_count: int
    failed_count: int
    skipped_count: int
    unknown_count: int


@dataclass(frozen=True, slots=True)
class DiscoverKeyResult:
    site: str
    key: str
    status: str
    observed: int | None = None
    new: int | None = None
    known: int | None = None
    complete: bool | None = None
    stopped_reason: str | None = None
    warnings: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BatchSummary:
    site: str
    status: str
    metrics_status: str
    metrics_path: str | None
    planned_skips: int | None = None
    execution_skips: int | None = None
    candidates_started: int | None = None
    candidates_completed: int | None = None
    candidates_failed: int | None = None
    elapsed: float | None = None
    stop_reason: str | None = None
    http_requests: int | None = None
    retries: int | None = None
    challenges: int | None = None
    metrics_omitted: bool = False
    candidates_skipped: int | None = None


@dataclass(frozen=True, slots=True)
class GrantResult:
    site: str | None
    work_id: int | None
    label: str | None
    resource: str | None
    status: str
    reason: str | None
    resource_consumed: bool | None
    outcome: str
    item_id: int | None = None
    source_id: int | None = None


@dataclass(frozen=True, slots=True)
class Problem:
    severity: str
    event_type: str
    reason: str
    context: JobContext = JobContext()


@dataclass(frozen=True, slots=True)
class JobResult:
    job_id: str
    action: str
    mode: str | None
    state: str
    elapsed: float | None
    current: JobContext
    tasks: tuple[TaskResult, ...]
    discover: tuple[DiscoverKeyResult, ...]
    batches: tuple[BatchSummary, ...]
    grants: tuple[GrantResult, ...]
    problems: tuple[Problem, ...]
    event_cursor: int
    event_page_complete: bool
    grant_facts_omitted: int = 0


@dataclass(slots=True)
class _EventSession:
    job_id: str
    cursor: int = 0
    events: dict[int, dict[str, Any]] | None = None
    semantic: dict[tuple[Any, ...], dict[str, Any]] | None = None
    semantic_problems: deque[dict[str, Any]] | None = None
    semantic_problem_sequences: set[int] | None = None
    current_event: dict[str, Any] | None = None
    grant_facts_omitted: int = 0
    semantic_grant_count: int = 0

    def __post_init__(self) -> None:
        self.events = {}
        self.semantic = {}
        self.semantic_problems = deque()
        self.semantic_problem_sequences = set()


@dataclass(slots=True)
class _MetricsState:
    path: Path | None
    status: str
    offset: int = 0
    pending: bytes = b""
    site: str | None = None
    run_id: str | None = None
    start_seen: bool = False
    summary: dict[str, Any] | None = None
    planned_skips: int = 0
    execution_skips: int = 0
    saw_skip: bool = False
    grants: dict[tuple[Any, ...], dict[str, Any]] | None = None
    failed_candidates: list[dict[str, Any]] | None = None
    candidate_results: list[dict[str, Any]] | None = None
    records_seen: int = 0
    records_omitted: int = 0
    identity: tuple[int, int, int] | None = None

    def __post_init__(self) -> None:
        self.grants = {}
        self.failed_candidates = []
        self.candidate_results = []


class JobResultPresenter:
    """Reduce only structured DB/metrics evidence into immutable DTOs."""

    def __init__(self, store: Any, *, event_page_size: int = 500, latest_event_size: int = 100, max_event_memory: int = 10_000, metrics_max_line_bytes: int = 64 * 1024, metrics_max_read: int = 64 * 1024, metrics_max_records: int = 2_000) -> None:
        self.store = store
        self.event_page_size = max(1, min(int(event_page_size), 500))
        self.latest_event_size = max(1, min(int(latest_event_size), 200))
        self.max_event_memory = max(100, int(max_event_memory))
        self.metrics_max_line_bytes = max(256, int(metrics_max_line_bytes))
        self.metrics_max_read = max(1024, int(metrics_max_read))
        self.metrics_max_records = max(100, int(metrics_max_records))
        self._session: _EventSession | None = None
        self._metrics: dict[tuple[str, str], _MetricsState] = {}
        self._event_page_complete = False
        self.max_grant_facts = 2_000
        self._selected_scope: set[tuple[str, str]] = set()
        self._task_scope: set[str] = set()

    def reset(self, job_id: str | None = None) -> None:
        self._session = _EventSession(job_id) if job_id else None
        self._metrics = {}
        self._selected_scope = set()
        self._task_scope = set()

    def present(self, job_id: str) -> JobResult:
        if self._session is None or self._session.job_id != job_id:
            self.reset(job_id)
        assert self._session is not None
        row = self.store.get_job(job_id)
        tasks = tuple(self.store.list_tasks(job_id))
        request = self._request_payload(job_id)
        requested_keys = request.get("keys_by_site")
        if not isinstance(requested_keys, dict):
            requested_keys = {}
        self._selected_scope = {
            (_text(site), _text(key))
            for site, keys in requested_keys.items()
            if isinstance(keys, (list, tuple))
            for key in keys
        }
        self._task_scope = {_text(task["task_id"]) for task in tasks}
        self._read_events(job_id)
        events = self._event_view()
        task_results = tuple(self._task_result(task) for task in tasks)
        action = _text(row["action"])
        mode = _text(request.get("mode")) or next((_text(task["mode"]) for task in tasks if task["mode"]), None)
        metrics = self._read_task_metrics(request, tasks, events)
        return JobResult(job_id=job_id, action=action, mode=mode, state=_text(row["state"]), elapsed=_elapsed(row), current=_current_context(events), tasks=task_results, discover=self._discover(request, tasks, events, action), batches=self._batches(tasks, metrics) if action in {"batch", "grant_only"} else (), grants=self._grants(tasks, events, metrics) if action in {"batch", "grant_only"} else (), problems=self._problems(events, metrics, tasks, action), event_cursor=self._session.cursor, event_page_complete=self._event_page_complete, grant_facts_omitted=self._session.grant_facts_omitted)

    def _read_events(self, job_id: str) -> None:
        assert self._session is not None
        list_after = getattr(self.store, "list_events_after", None)
        page = tuple(list_after(job_id, after_sequence=self._session.cursor, limit=self.event_page_size)) if callable(list_after) else tuple(self.store.list_events(job_id, limit=self.event_page_size))
        for row in page:
            event = dict(row)
            sequence = _sequence(event)
            self._remember_event(event, allow_grant_overflow_count=True)
            self._session.cursor = max(self._session.cursor, sequence)
        self._event_page_complete = len(page) < self.event_page_size
        latest_reader = getattr(self.store, "list_events_latest", None)
        if callable(latest_reader):
            for row in latest_reader(job_id, limit=self.latest_event_size):
                event = dict(row)
                self._remember_event(event, allow_grant_overflow_count=False)

    def _remember_event(self, event: dict[str, Any], *, allow_grant_overflow_count: bool) -> None:
        assert self._session is not None and self._session.semantic is not None
        event_type = _text(event.get("event_type"))
        site = _optional_text(event.get("site"))
        key = _optional_text(event.get("key_identity"))
        if event_type in {"grant_confirmed", "grant_unknown"} and self._selected_scope and site not in {value[0] for value in self._selected_scope}:
            return
        if event_type in {"task_started", "candidate_started", "candidate_finished", "grant_confirmed", "grant_unknown"} and (self._session.current_event is None or _sequence(event) >= _sequence(self._session.current_event)):
            self._session.current_event = event
        if event_type in {"candidate_started", "candidate_finished", "discovery_result"}:
            semantic_key = ((event_type, site, key) if not self._selected_scope or (site or "", key or "") in self._selected_scope else ("current", event_type, site))
        elif event_type in {"grant_confirmed", "grant_unknown"}:
            semantic_key = ("grant", site, event.get("item_id"), key, event.get("resource"), event_type)
            if semantic_key not in self._session.semantic and self._session.semantic_grant_count >= self.max_grant_facts:
                if allow_grant_overflow_count:
                    self._session.grant_facts_omitted += 1
                return
        elif event_type in {"metrics_started", "batch_finished", "task_started"}:
            if self._task_scope and _optional_text(event.get("task_id")) not in self._task_scope:
                return
            semantic_key = (event_type, event.get("task_id"), site)
        else:
            semantic_key = None
        if semantic_key is None:
            if event_type not in {"warning", "error", "task_failed", "process_exited", "grant_unknown"} and _text(event.get("result")) not in {"failed", "unknown", "cancelled"}:
                return
            assert self._session.semantic_problems is not None
            assert self._session.semantic_problem_sequences is not None
            sequence = _sequence(event)
            if sequence in self._session.semantic_problem_sequences:
                return
            self._session.semantic_problems.append(event)
            self._session.semantic_problem_sequences.add(sequence)
            while len(self._session.semantic_problems) > self.max_event_memory:
                removed = self._session.semantic_problems.popleft()
                self._session.semantic_problem_sequences.discard(_sequence(removed))
            return
        prior = self._session.semantic.get(semantic_key)
        if prior is None or _sequence(event) >= _sequence(prior):
            self._session.semantic[semantic_key] = event
            if prior is None and semantic_key[0] == "grant":
                self._session.semantic_grant_count += 1

    def _event_view(self) -> tuple[dict[str, Any], ...]:
        assert self._session is not None and self._session.events is not None
        merged = {}
        for event in (self._session.semantic or {}).values():
            merged.setdefault(_sequence(event), event)
        for event in (self._session.semantic_problems or ()):
            merged.setdefault(_sequence(event), event)
        if self._session.current_event is not None:
            merged.setdefault(_sequence(self._session.current_event), self._session.current_event)
        return tuple(sorted(merged.values(), key=_sequence))

    def _request_payload(self, job_id: str) -> dict[str, Any]:
        try:
            payload = self.store.request_for(job_id)
        except Exception:  # noqa: BLE001
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _task_result(task: Any) -> TaskResult:
        return TaskResult(task_id=_text(task["task_id"]), site=_text(task["site"]), state=_text(task["state"]), observed_attempts=_integer(task["observed_attempts"], 0), success_count=_integer(task["success_count"], 0), failed_count=_integer(task["failed_count"], 0), skipped_count=_integer(task["skipped_count"], 0), unknown_count=_integer(task["unknown_count"], 0))

    def _discover(self, request: dict[str, Any], tasks: tuple[Any, ...], events: tuple[dict[str, Any], ...], action: str) -> tuple[DiscoverKeyResult, ...]:
        if action != "discover":
            return ()
        keys_by_site = request.get("keys_by_site")
        if not isinstance(keys_by_site, dict):
            keys_by_site = {}
            for task in tasks:
                try:
                    values = json.loads(str(task["selected_keys_json"]))
                except (TypeError, ValueError, json.JSONDecodeError):
                    values = []
                if isinstance(values, list):
                    keys_by_site[_text(task["site"])] = values
        output: list[DiscoverKeyResult] = []
        for site, values in keys_by_site.items():
            if not isinstance(values, (list, tuple)):
                continue
            for raw_key in values:
                key = _text(raw_key)
                matching = [event for event in events if _text(event.get("site")) == _text(site) and _text(event.get("key_identity")) == key]
                finished = _latest(matching, "candidate_finished")
                started = _latest(matching, "candidate_started")
                detail = _latest(matching, "discovery_result")
                payload = _payload(detail)
                warnings = tuple(_text(value) for value in payload.get("warnings", ()) if value is not None)
                error = _optional_text(payload.get("error"))
                if finished is None:
                    status = "unknown" if started is not None or not self._event_page_complete else "unstarted"
                elif _text(finished.get("result")) == "succeeded":
                    status = "success"
                elif _text(finished.get("reason")).lower() == "disabled":
                    status = "disabled"
                elif _text(finished.get("result")) == "skipped":
                    status = "disabled" if "disabled" in _text(finished.get("reason")).lower() else "unknown"
                else:
                    status = "failed"
                output.append(DiscoverKeyResult(site=_text(site), key=key, status=status, observed=_optional_integer(payload.get("observed")), new=_optional_integer(payload.get("new")), known=_optional_integer(payload.get("known")), complete=_optional_bool(payload.get("complete")), stopped_reason=_optional_text(payload.get("stopped_reason")), warnings=warnings, error=error))
        return tuple(output)

    def _read_task_metrics(self, request: dict[str, Any], tasks: tuple[Any, ...], events: tuple[dict[str, Any], ...]) -> dict[str, _MetricsState]:
        paths: dict[str, str | None] = {_text(task["task_id"]): None for task in tasks}
        for event in events:
            if _text(event.get("event_type")) not in {"metrics_started", "batch_finished"}:
                continue
            task_id = _text(event.get("task_id"))
            task = next((item for item in tasks if _text(item["task_id"]) == task_id), None)
            if task is None or _text(event.get("site")) != _text(task["site"]):
                continue
            candidate = _payload(event).get("metrics_path")
            if task_id and isinstance(candidate, str) and candidate:
                paths[task_id] = candidate
        output: dict[str, _MetricsState] = {}
        for task in tasks:
            task_id = _text(task["task_id"])
            site = _text(task["site"])
            path_value = paths.get(task_id)
            cache_key = (site, path_value or "")
            state = self._metrics.get(cache_key)
            if state is None:
                path, status = _authorized_metrics_path(path_value, request.get("metrics_root"))
                state = _MetricsState(path, status, site=site)
                self._metrics[cache_key] = state
            if state.path is not None:
                _advance_metrics(state, max_read=self.metrics_max_read, max_line_bytes=self.metrics_max_line_bytes, max_records=self.metrics_max_records)
            output[task_id] = state
        return output

    def _batches(self, tasks: tuple[Any, ...], metrics: dict[str, _MetricsState]) -> tuple[BatchSummary, ...]:
        output: list[BatchSummary] = []
        for task in tasks:
            site = _text(task["site"])
            state = metrics[_text(task["task_id"])]
            summary = state.summary
            path = _safe_path(str(state.path) if state.path else None)
            if summary is None:
                planned = state.planned_skips if state.saw_skip else None
                execution = state.execution_skips if state.saw_skip else None
                status = "unknown" if state.status != "complete" else "partial"
                output.append(BatchSummary(site, status, state.status, path, planned, execution))
                continue
            stop_reason = _optional_text(summary.get("stop_reason"))
            summary_skipped = _optional_integer(summary.get("candidates_skipped"))
            explicit_zero = state.status == "complete" and summary_skipped == 0
            planned = (state.planned_skips if state.saw_skip else 0) if explicit_zero else (state.planned_skips if state.saw_skip else None)
            execution = (state.execution_skips if state.saw_skip else 0) if explicit_zero else (state.execution_skips if state.saw_skip else None)
            status = "no_candidates" if stop_reason == "no_candidates" and state.status == "complete" else ("complete" if state.status == "complete" else "partial")
            output.append(BatchSummary(site=site, status=status, metrics_status=state.status, metrics_path=path, planned_skips=planned, execution_skips=execution, candidates_started=_optional_integer(summary.get("candidates_started")), candidates_completed=_optional_integer(summary.get("candidates_completed")), candidates_failed=_optional_integer(summary.get("candidates_failed")), elapsed=_optional_float(summary.get("elapsed")), stop_reason=stop_reason, http_requests=_optional_integer(summary.get("http_requests_total")), retries=_optional_integer(summary.get("retry_count")), challenges=_optional_integer(summary.get("challenge_count")), metrics_omitted=state.records_omitted > 0, candidates_skipped=summary_skipped))
        return tuple(output)

    def _grants(self, tasks: tuple[Any, ...], events: tuple[dict[str, Any], ...], metrics: dict[str, _MetricsState]) -> tuple[GrantResult, ...]:
        output: dict[tuple[Any, ...], GrantResult] = {}
        report_index: dict[tuple[Any, ...], list[GrantResult]] = {}
        for task in tasks:
            site = _text(task["site"])
            state = metrics[_text(task["task_id"])]
            candidate_index = _candidate_index(state.candidate_results or ())
            for record in (state.grants or {}).values():
                consumed = _optional_bool(record.get("resource_consumed"))
                status = _text(record.get("status")) or "unknown"
                candidates = _indexed_candidate_matches(record, candidate_index)
                report = GrantResult(site=site, work_id=_optional_integer(record.get("work_id")), label=_optional_text(record.get("label")), resource=_optional_text(record.get("resource")), status=status, reason=_optional_text(record.get("reason")), resource_consumed=consumed, outcome=_grant_outcome(record, consumed, status, candidates), item_id=_optional_integer(record.get("item_id")), source_id=_optional_integer(record.get("source_id")))
                output[(site, record.get("work_id"), record.get("resource"))] = report
                _index_grant_report(report, report_index)
        for event in events:
            event_type = _text(event.get("event_type"))
            if event_type not in {"grant_confirmed", "grant_unknown"}:
                continue
            site = _optional_text(event.get("site"))
            resource = _optional_text(event.get("resource"))
            item_id = _optional_integer(event.get("item_id"))
            source_id = _optional_integer(event.get("source_id"))
            key = (site, None, resource, item_id, source_id)
            if any(_grant_report_matches(report, site, resource, item_id, source_id) for report in _indexed_grant_reports(report_index, site, resource, item_id, source_id)):
                continue
            output[key] = GrantResult(site=site, work_id=None, label=None, resource=resource, status="confirmed" if event_type == "grant_confirmed" else "unknown", reason=_optional_text(event.get("reason")), resource_consumed=_optional_bool(event.get("resource_consumed")), outcome="confirmed" if event_type == "grant_confirmed" else "unknown", item_id=item_id, source_id=source_id)
        return tuple(output.values())

    def _problems(self, events: tuple[dict[str, Any], ...], metrics: dict[str, _MetricsState], tasks: tuple[Any, ...], action: str) -> tuple[Problem, ...]:
        problems: list[Problem] = []
        for event in events:
            event_type = _text(event.get("event_type"))
            result = _text(event.get("result"))
            if event_type == "process_exited" and result in {"", "succeeded", "success"}:
                continue
            payload = _payload(event) if event_type == "discovery_result" else {}
            has_discovery_problem = bool(payload.get("error") or payload.get("warnings"))
            if event_type not in {"warning", "error", "task_failed", "process_exited", "grant_unknown"} and result not in {"failed", "unknown", "cancelled"} and not has_discovery_problem:
                continue
            context = JobContext(site=_optional_text(event.get("site")), key=_optional_text(event.get("key_identity")), item_id=_optional_integer(event.get("item_id")), source_id=_optional_integer(event.get("source_id")), resource=_optional_text(event.get("resource")), phase=_optional_text(event.get("phase")))
            reason = _optional_text(event.get("reason")) or result or event_type
            severity = "error" if result in {"failed", "unknown", "cancelled"} or event_type in {"error", "task_failed"} else "warning"
            if not (event_type == "discovery_result" and has_discovery_problem):
                problems.append(Problem(severity, event_type, reason, context))
            if event_type == "discovery_result":
                for detail_type, detail in (("discovery_error", payload.get("error")), ("discovery_warning", payload.get("warnings"))):
                    values = detail if isinstance(detail, list) else [detail]
                    for value in values:
                        if value:
                            problems.append(Problem("error" if detail_type == "discovery_error" else "warning", detail_type, _text(value), context))
        for task in tasks:
            state = metrics[_text(task["task_id"])]
            candidate_index = _candidate_index(state.candidate_results or ())
            if state.status in {"invalid", "scope_invalid"}:
                problems.append(Problem("warning", "metrics", f"metrics unavailable: {state.status}", JobContext(site=state.site)))
            elif state.status == "partial":
                problems.append(Problem("warning", "metrics", "metrics are still partial", JobContext(site=state.site)))
            elif state.status == "missing" and action in {"batch", "grant_only"} and state.path is not None:
                problems.append(Problem("warning", "metrics", "expected metrics file is missing", JobContext(site=state.site)))
            for candidate in state.failed_candidates or ():
                problems.append(Problem("error", "metrics_candidate_failed", _optional_text(candidate.get("stop_reason")) or _optional_text(candidate.get("error_message")) or "candidate failed", JobContext(site=state.site, item_id=_optional_integer(candidate.get("item_id")), source_id=_optional_integer(candidate.get("source_id")), resource=_optional_text(candidate.get("resource")))))
            for grant in (state.grants or {}).values():
                consumed = _optional_bool(grant.get("resource_consumed"))
                status = _text(grant.get("status")).lower()
                if status in {"ok", "success", "confirmed"} and consumed is None:
                    problems.append(Problem("warning", "grant_result", "resource consumption is unknown", JobContext(site=state.site, source_id=_optional_integer(grant.get("source_id")), resource=_optional_text(grant.get("resource")))))
                if consumed is True and _grant_outcome(grant, True, status, _indexed_candidate_matches(grant, candidate_index)) == "postprocess_unknown":
                    reason = _optional_text(grant.get("reason")) or "post-processing outcome is unknown after consumption"
                    problems.append(Problem("warning", "grant_result", reason, JobContext(site=state.site, source_id=_optional_integer(grant.get("source_id")), resource=_optional_text(grant.get("resource")))))
        if len(problems) > 100:
            problems = problems[-99:]
            problems.insert(0, Problem("warning", "problems", "latest 99 structured problems shown; older problems omitted"))
        return tuple(problems)


def _authorized_metrics_path(path_value: str | None, root_value: Any) -> tuple[Path | None, str]:
    if not path_value or not root_value:
        return None, "missing" if not path_value else "invalid"
    try:
        root = Path(str(root_value)).resolve()
        candidate = Path(path_value)
        path = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        path.relative_to(root)
    except (OSError, ValueError):
        return None, "invalid"
    return (path, "missing") if not path.is_file() else (path, "partial")


def _advance_metrics(state: _MetricsState, *, max_read: int, max_line_bytes: int, max_records: int) -> None:
    assert state.path is not None
    try:
        stat = state.path.stat()
        identity = (int(stat.st_dev), int(stat.st_ino), int(getattr(stat, "st_birthtime_ns", 0)))
        if state.status in {"invalid", "scope_invalid"} and state.identity == identity and stat.st_size >= state.offset:
            return
        if state.identity is not None and (identity != state.identity or stat.st_size < state.offset):
            state.offset = 0
            state.pending = b""
            state.run_id = None
            state.start_seen = False
            state.summary = None
            state.planned_skips = state.execution_skips = 0
            state.saw_skip = False
            state.grants = {}
            state.failed_candidates = []
            state.candidate_results = []
            state.records_seen = 0
            state.records_omitted = 0
            state.status = "partial"
        state.identity = identity
        with state.path.open("rb") as stream:
            stream.seek(state.offset)
            chunk = stream.read(max_read)
            state.offset = stream.tell()
    except FileNotFoundError:
        _mark_unusable(state, "missing")
        state.offset = 0
        state.pending = b""
        state.identity = None
        state.start_seen = False
        return
    except OSError:
        _mark_unusable(state, "invalid")
        return
    data = state.pending + chunk
    lines = data.split(b"\n")
    state.pending = lines.pop() if data and not data.endswith(b"\n") else b""
    if len(state.pending) > max_line_bytes:
        _mark_unusable(state, "invalid")
        return
    for raw in lines:
        if len(raw) > max_line_bytes:
            _mark_unusable(state, "invalid")
            return
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            _mark_unusable(state, "invalid")
            return
        if not isinstance(record, dict):
            _mark_unusable(state, "invalid")
            return
        state.records_seen += 1
        record_site = _optional_text(record.get("site"))
        record_run = _optional_text(record.get("run_id"))
        if not state.start_seen:
            if record.get("type") != "batch" or record.get("event") != "start" or record_site != state.site or not record_run:
                _mark_unusable(state, "scope_invalid")
                return
            state.run_id = record_run
            state.start_seen = True
        elif (record_site is not None and record_site != state.site) or (record_run is not None and record_run != state.run_id):
            _mark_unusable(state, "scope_invalid")
            return
        kind = record.get("type")
        if kind == "batch_summary":
            state.summary = record
        elif kind == "candidate" and record.get("event") == "result":
            result = _text(record.get("result"))
            if state.candidate_results is not None:
                state.candidate_results.append(record)
                if len(state.candidate_results) > max_records:
                    state.candidate_results.pop(0)
                    state.records_omitted += 1
            if result == "skipped":
                state.saw_skip = True
                if record.get("start_time") is None and not record.get("access_strategy"):
                    state.planned_skips += 1
                else:
                    state.execution_skips += 1
            elif result == "failed" and state.failed_candidates is not None:
                state.failed_candidates.append(record)
                if len(state.failed_candidates) > max_records:
                    state.failed_candidates.pop(0)
                    state.records_omitted += 1
        elif kind == "grant_result" and state.grants is not None:
            state.grants[(record.get("work_id"), record.get("resource"))] = record
            if len(state.grants) > max_records:
                state.grants.pop(next(iter(state.grants)))
                state.records_omitted += 1
    at_eof = len(chunk) < max_read
    state.status = "complete" if state.summary is not None and not state.pending and at_eof else ("partial" if state.start_seen else "scope_invalid")


def _mark_unusable(state: _MetricsState, status: str) -> None:
    state.status = status
    state.summary = None
    state.planned_skips = 0
    state.execution_skips = 0
    state.saw_skip = False
    state.grants = {}
    state.failed_candidates = []
    state.candidate_results = []


def _grant_report_matches(report: GrantResult, site: str | None, resource: str | None, item_id: int | None, source_id: int | None) -> bool:
    if report.site != site or report.work_id is None or report.resource != resource:
        return False
    identities: list[bool] = []
    if report.source_id is not None and source_id is not None:
        identities.append(report.source_id == source_id)
    if report.item_id is not None and item_id is not None:
        identities.append(report.item_id == item_id)
    return bool(identities) and all(identities)


def _index_grant_report(report: GrantResult, index: dict[tuple[Any, ...], list[GrantResult]]) -> None:
    if report.site is None or report.resource is None:
        return
    if report.item_id is not None:
        index.setdefault((report.site, report.resource, "item_id", report.item_id), []).append(report)
    if report.source_id is not None:
        index.setdefault((report.site, report.resource, "source_id", report.source_id), []).append(report)


def _indexed_grant_reports(index: dict[tuple[Any, ...], list[GrantResult]], site: str | None, resource: str | None, item_id: int | None, source_id: int | None) -> tuple[GrantResult, ...]:
    candidates: list[GrantResult] = []
    seen: set[int] = set()
    for field, value in (("item_id", item_id), ("source_id", source_id)):
        if value is None:
            continue
        for report in index.get((site, resource, field, value), ()):
            identity = id(report)
            if identity not in seen:
                candidates.append(report)
                seen.add(identity)
    return tuple(candidates)


def _candidate_index(candidates: Iterable[dict[str, Any]]) -> dict[tuple[str, Any], list[dict[str, Any]]]:
    index: dict[tuple[str, Any], list[dict[str, Any]]] = {}
    for candidate in candidates:
        for field in ("item_id", "source_id"):
            value = _optional_text(candidate.get(field))
            if value is not None:
                index.setdefault((field, value), []).append(candidate)
    return index


def _indexed_candidate_matches(record: dict[str, Any], index: dict[tuple[str, Any], list[dict[str, Any]]]) -> tuple[dict[str, Any], ...]:
    candidates: list[dict[str, Any]] = []
    seen: set[int] = set()
    for field in ("item_id", "source_id"):
        value = _optional_text(record.get(field))
        if value is None:
            continue
        for candidate in index.get((field, value), ()):
            identity = id(candidate)
            if identity not in seen and _failure_matches(record, candidate):
                candidates.append(candidate)
                seen.add(identity)
    candidates.sort(key=_sequence)
    return tuple(candidates)


def _grant_outcome(record: dict[str, Any], consumed: bool | None, status: str, candidates: Iterable[dict[str, Any]]) -> str:
    normalized = status.lower()
    if consumed is not True or normalized not in {"ok", "success", "confirmed"}:
        return normalized
    matching = [candidate for candidate in candidates if _failure_matches(record, candidate)]
    latest = matching[-1] if matching else None
    if latest is not None and _text(latest.get("result")) == "failed":
        return "consumed_but_postprocess_failed"
    if latest is not None and _text(latest.get("result")) in {"completed", "succeeded"}:
        return normalized
    return "postprocess_unknown"


def _failure_matches(grant: dict[str, Any], failure: dict[str, Any]) -> bool:
    strong_match = False
    for field in ("item_id", "source_id", "resource"):
        left = _optional_text(grant.get(field))
        right = _optional_text(failure.get(field))
        if left is not None and right is not None and left != right:
            return False
        if field in {"item_id", "source_id"} and left is not None and right is not None:
            strong_match = True
    return strong_match


def _current_context(events: Iterable[dict[str, Any]]) -> JobContext:
    candidates = [event for event in events if _text(event.get("event_type")) in {"task_started", "candidate_started", "candidate_finished", "grant_confirmed", "grant_unknown"}]
    event = max(candidates, key=_sequence, default={})
    event_type = _text(event.get("event_type"))
    payload = _payload(event)
    return JobContext(site=_optional_text(event.get("site")) or _optional_text(payload.get("site")), key=None if event_type == "task_started" else _optional_text(event.get("key_identity")), item_id=None if event_type == "task_started" else _optional_integer(event.get("item_id")), source_id=None if event_type == "task_started" else _optional_integer(event.get("source_id")), resource=None if event_type == "task_started" else _optional_text(event.get("resource")), phase=_optional_text(event.get("phase")))


def _latest(events: Iterable[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    return max((event for event in events if _text(event.get("event_type")) == event_type), key=_sequence, default=None)


def _payload(event: dict[str, Any] | None) -> dict[str, Any]:
    value = event.get("payload_json") if event else None
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value)) if value else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sequence(value: Any) -> int:
    try:
        return int(value.get("sequence", 0))
    except (AttributeError, TypeError, ValueError):
        return 0


def _elapsed(row: Any) -> float | None:
    try:
        started = datetime.fromisoformat(str(row["started_at"]))
        ended_value = row["ended_at"]
        ended = datetime.fromisoformat(str(ended_value)) if ended_value else datetime.now(UTC)
        return max(0.0, (ended - started).total_seconds())
    except (KeyError, TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return sanitize_text(str(value)) if value is not None else ""


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    return None


def _safe_path(value: str | None) -> str | None:
    return sanitize_text(value) if value else None


__all__ = ["BatchSummary", "DiscoverKeyResult", "GrantResult", "JobContext", "JobResult", "JobResultPresenter", "Problem", "TaskResult"]
