"""Incremental JSONL access metrics for one sequential Batch run."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from screenshot_crawler.batch.models import BatchCandidate, BatchSkipped
from screenshot_crawler.core.access_guard import AccessEvent

_SAFE_PART = re.compile(r"[^A-Za-z0-9_.-]+")


class BatchMetricsWriter:
    """Append and flush body-free request/candidate/batch observations."""

    def __init__(
        self,
        root: str | Path = "output/metrics",
        *,
        site: str,
        mode: str = "normal",
        run_id: str | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.site = site
        self.mode = mode
        self.run_id = run_id or uuid.uuid4().hex
        timestamp = datetime.now(UTC).astimezone().strftime("%Y%m%dT%H%M%S%f%z")
        safe_site = _safe_part(site, "site")
        safe_mode = _safe_part(mode, "mode")
        self.path = self.root / f"{timestamp}-{safe_site}-{safe_mode}-{self.run_id}.jsonl"
        self._stream = self.path.open("a", encoding="utf-8")
        self._started_at = datetime.now(UTC)
        self._started_monotonic = time.monotonic()
        self._current: dict[str, Any] | None = None
        self._current_start_time: datetime | None = None
        self._current_started_monotonic: float | None = None
        self._current_request_count = 0
        self._current_retry_count = 0
        self._finalized = False
        self._candidates_started = 0
        self._candidates_completed = 0
        self._candidates_failed = 0
        self._candidates_skipped = 0
        self._http_requests_total = 0
        self._http_403_count = 0
        self._http_429_count = 0
        self._http_5xx_count = 0
        self._challenge_count = 0
        self._captcha_count = 0
        self._retry_count = 0
        self._write(
            {
                "type": "batch",
                "event": "start",
                "site": self.site,
                "mode": self.mode,
                "run_id": self.run_id,
                "batch_start_time": self._started_at.isoformat(),
                "metrics_path": self.path.as_posix(),
            }
        )

    def record_planned_skips(self, skipped: Iterable[BatchSkipped]) -> None:
        for item in skipped:
            self._candidates_skipped += 1
            self._write(
                {
                    "type": "candidate",
                    "event": "result",
                    "run_id": self.run_id,
                    "item_id": item.item_id,
                    "source_id": item.source_id,
                    "start_time": None,
                    "elapsed": 0.0,
                    "request_count": 0,
                    "retry_count": 0,
                    "result": "skipped",
                    "stop_reason": item.reason,
                }
            )

    def start_candidate(self, candidate: BatchCandidate) -> None:
        if self._current is not None:
            raise RuntimeError("a metrics candidate is already active")
        self._current = {
            "item_id": getattr(candidate, "item_id", None),
            "source_id": getattr(candidate, "source_id", None),
            "target_id": getattr(candidate, "target_id", None),
            "access_strategy": getattr(candidate, "access_strategy", None),
            "resource": getattr(candidate, "quota_resource", None),
        }
        self._current_start_time = datetime.now(UTC)
        self._current_started_monotonic = time.monotonic()
        self._current_request_count = 0
        self._current_retry_count = 0
        self._candidates_started += 1
        self._write(
            {
                "type": "candidate",
                "event": "start",
                "run_id": self.run_id,
                **self._current,
                "start_time": self._current_start_time.isoformat(),
            }
        )

    def record_access_event(self, event: AccessEvent) -> None:
        if event.event_type == "request":
            self._http_requests_total += 1
            self._current_request_count += 1
            if event.status == 403:
                self._http_403_count += 1
            if event.status == 429:
                self._http_429_count += 1
            if event.status is not None and 500 <= event.status <= 599:
                self._http_5xx_count += 1
        elif event.event_type == "challenge":
            self._challenge_count += 1
        elif event.event_type == "captcha":
            self._captcha_count += 1
        self._write(
            {
                **event.as_dict(),
                "run_id": self.run_id,
                "item_id": self._current.get("item_id") if self._current else None,
                "source_id": self._current.get("source_id") if self._current else None,
            }
        )

    def finish_candidate(
        self,
        *,
        result: str,
        stop_reason: str | None,
        resource_consumed: bool | None = None,
        retry_count: int = 0,
    ) -> None:
        if self._current is None or self._current_started_monotonic is None:
            return
        elapsed = max(0.0, time.monotonic() - self._current_started_monotonic)
        self._current_retry_count = max(0, retry_count)
        self._retry_count += self._current_retry_count
        if result == "completed":
            self._candidates_completed += 1
        elif result == "failed":
            self._candidates_failed += 1
        elif result == "skipped":
            self._candidates_skipped += 1
        self._write(
            {
                "type": "candidate",
                "event": "result",
                "run_id": self.run_id,
                **self._current,
                "start_time": self._current_start_time.isoformat(),
                "elapsed": elapsed,
                "request_count": self._current_request_count,
                "retry_count": self._current_retry_count,
                "result": result,
                "stop_reason": stop_reason,
                "resource_consumed": resource_consumed,
            }
        )
        self._current = None
        self._current_start_time = None
        self._current_started_monotonic = None
        self._current_request_count = 0
        self._current_retry_count = 0

    def finish(self, *, stop_reason: str | None = None) -> None:
        if self._finalized:
            return
        if self._current is not None:
            self.finish_candidate(result="failed", stop_reason=stop_reason)
        ended_at = datetime.now(UTC)
        self._write(
            {
                "type": "batch_summary",
                "site": self.site,
                "mode": self.mode,
                "run_id": self.run_id,
                "batch_start_time": self._started_at.isoformat(),
                "batch_end_time": ended_at.isoformat(),
                "elapsed": max(0.0, time.monotonic() - self._started_monotonic),
                "candidates_started": self._candidates_started,
                "candidates_completed": self._candidates_completed,
                "candidates_failed": self._candidates_failed,
                "candidates_skipped": self._candidates_skipped,
                "http_requests_total": self._http_requests_total,
                "http_403_count": self._http_403_count,
                "http_429_count": self._http_429_count,
                "http_5xx_count": self._http_5xx_count,
                "challenge_count": self._challenge_count,
                "captcha_count": self._captcha_count,
                "retry_count": self._retry_count,
                "stop_reason": stop_reason,
            }
        )
        self._finalized = True

    def close(self) -> None:
        self._stream.close()

    def _write(self, record: dict[str, Any]) -> None:
        self._stream.write(_json_line(record))
        self._stream.flush()


def _safe_part(value: str, fallback: str) -> str:
    result = _SAFE_PART.sub("_", value).strip(" .")
    return result or fallback


def _json_line(record: dict[str, Any]) -> str:
    import json

    return json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
