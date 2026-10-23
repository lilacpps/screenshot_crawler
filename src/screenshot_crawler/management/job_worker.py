"""Qt-free subprocess worker for the P3 management queue."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from screenshot_crawler.execution_worker import WorkerCancelled, _run
from screenshot_crawler.management.jobs import JobEvent, JsonlEventSink
from screenshot_crawler.management.process_identity import process_start_identity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="screenshot-crawler-job-worker")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--request-json", required=True)
    parser.add_argument("--worker-token", required=True)
    parser.add_argument("--start-gate", required=True)
    return parser


async def run_job(
    job_id: str,
    request: dict[str, object],
    *,
    worker_token: str,
    job_dir: str | Path,
) -> int:
    job_dir = Path(job_dir)
    sink = JsonlEventSink(job_dir / "events.jsonl", job_id)
    identity = job_dir / "worker.identity"
    identity.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "token": worker_token,
                "start_identity": process_start_identity(os.getpid()),
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    raw_gate = request.get("_start_gate")
    if raw_gate:
        gate = Path(str(raw_gate))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 15
        while loop.time() < deadline:
            try:
                state = gate.read_text(encoding="utf-8").strip()
            except OSError:
                state = ""
            if state == "go":
                break
            if state == "cancel":
                return 1
            await asyncio.sleep(0.05)
        else:
            return 1

    start_identity = process_start_identity(os.getpid())

    def write_heartbeat() -> None:
        value = {
            "job_id": job_id,
            "pid": os.getpid(),
            "token": worker_token,
            "start_identity": start_identity,
            "observed_at": datetime.now(UTC).isoformat(),
        }
        temporary = job_dir / "worker.heartbeat.tmp"
        temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, job_dir / "worker.heartbeat.json")

    heartbeat_error: list[BaseException] = []
    stop_heartbeat = asyncio.Event()

    async def heartbeat_loop() -> None:
        while not stop_heartbeat.is_set():
            try:
                write_heartbeat()
            except BaseException as exc:  # noqa: BLE001 - fail at next safe checkpoint
                heartbeat_error.append(exc)
                return
            try:
                await asyncio.wait_for(stop_heartbeat.wait(), timeout=5)
            except TimeoutError:
                continue

    current_site: str | None = None

    def emit(event_type: str, **fields: object) -> None:
        nonlocal current_site
        payload = fields.get("payload")
        site = fields.get("site")
        if site is None and isinstance(payload, dict):
            site = payload.get("site")
        if event_type == "task_started" and isinstance(site, str):
            current_site = site
        if site is None:
            site = current_site
        if site is not None:
            fields["site"] = site
            fields["task_id"] = f"{job_id}:{site}"
        sink.emit(JobEvent(job_id, event_type, **fields))
        if event_type in {"task_finished", "task_failed"}:
            current_site = None

    def cancel_requested() -> bool:
        return bool(heartbeat_error) or (job_dir / "cancel.request").is_file()

    write_heartbeat()
    heartbeat_task = asyncio.create_task(heartbeat_loop())
    try:
        emit("job_started", phase="planning", payload={"pid": os.getpid()})
        await _run(request, event_sink=emit, cancel_check=cancel_requested)
    except WorkerCancelled as exc:
        emit("task_failed", result="cancelled", reason=str(exc), resource_consumed=None)
        emit("job_finished", result="cancelled", reason=str(exc), resource_consumed=None)
        emit("process_exited", result="cancelled", resource_consumed=None)
        return 0
    except BaseException as exc:  # noqa: BLE001 - process boundary must serialize failure
        emit(
            "task_failed",
            result="failed",
            error_type=type(exc).__name__,
            reason=str(exc)[:2000],
            resource_consumed=getattr(exc, "resource_consumed", None),
        )
        emit(
            "process_exited",
            result="failed",
            reason=str(exc)[:2000],
            resource_consumed=getattr(exc, "resource_consumed", None),
        )
        return 1
    else:
        emit("job_finished", result="succeeded")
        emit("process_exited", result="succeeded")
        return 0
    finally:
        stop_heartbeat.set()
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request_path = Path(args.request_json)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise TypeError("job request must be a JSON object")
    request["_start_gate"] = args.start_gate
    return asyncio.run(
        run_job(
            args.job_id,
            request,
            worker_token=args.worker_token,
            job_dir=args.job_dir,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_job"]
