"""GUI-side controller for the single P3 worker subprocess."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from screenshot_crawler.management.execution import JobExecutionRequest, execution_request_payload
from screenshot_crawler.management.jobs import (
    ACTIVE_JOB_STATES,
    JobEvent,
    JobStore,
    sanitize_text,
)
from screenshot_crawler.management.process_identity import process_is_alive, process_start_identity


def _pid_alive(pid: int | None) -> bool:
    return process_is_alive(pid) if pid is not None else False


def _identity_matches(job_dir: Path, *, pid: int | None, token: str | None) -> bool:
    if pid is None or not token:
        return False
    try:
        identity = json.loads((job_dir / "worker.identity").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not bool(identity.get("pid")) or identity.get("token") != token:
        return False
    # Some Windows Python launchers expose a short-lived launcher PID through
    # Popen and replace it with the interpreter PID.  The per-launch token plus
    # the child-written PID is the stable identity pair in that case.  While a
    # child is live, also compare the OS creation identity to reject PID reuse.
    start_identity = identity.get("start_identity")
    if start_identity is not None and _pid_alive(identity.get("pid")):
        return process_start_identity(int(identity["pid"])) == str(start_identity)
    return True


def _verified_worker_pid(job_dir: Path, token: str | None) -> int | None:
    """Return the child PID only when its token and OS start identity match."""

    if not token:
        return None
    try:
        identity = json.loads((job_dir / "worker.identity").read_text(encoding="utf-8"))
        pid = int(identity["pid"])
        if identity.get("token") != token or not _pid_alive(pid):
            return None
        start_identity = identity.get("start_identity")
        if start_identity is not None and process_start_identity(pid) != str(start_identity):
            return None
        return pid
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _terminate_pid(pid: int, *, timeout: float = 10.0) -> bool:
    """Terminate a verified process and wait for it to disappear."""

    try:
        os.kill(pid, 15)
    except (OSError, ProcessLookupError):
        return not _pid_alive(pid)
    deadline = time.monotonic() + timeout
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _pid_alive(pid):
        with contextlib.suppress(OSError, ProcessLookupError):
            os.kill(pid, 9)
        while _pid_alive(pid) and time.monotonic() < deadline + 2:
            time.sleep(0.05)
    return not _pid_alive(pid)


class JobController:
    """Queue and supervise exactly one worker process at a time.

    Queued work is never started by construction.  ``start_next`` is an
    explicit GUI action and ``reconcile`` never retries an unfinished job.
    """

    _claimed_stores: ClassVar[set[str]] = set()

    def __init__(
        self,
        store: JobStore,
        *,
        python_executable: str | None = None,
        worker_module: str = "screenshot_crawler.management.job_worker",
        on_event: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self.store = store
        store_key = str(store.path.resolve())
        if store_key in self._claimed_stores:
            raise RuntimeError("another JobController already owns this management DB")
        self._claimed_store_key = store_key
        self._claimed_stores.add(store_key)
        self._lease_token = secrets.token_urlsafe(16)
        self._lease_path = store.path.with_suffix(store.path.suffix + ".controller.lock")
        self._lease_handle = None
        try:
            self._lease_path.parent.mkdir(parents=True, exist_ok=True)
            self._lease_handle = self._open_lease()
            self._lease_handle.seek(0)
            self._lease_handle.truncate()
            self._lease_handle.write(
                json.dumps({"pid": os.getpid(), "token": self._lease_token}).encode("utf-8")
            )
            self._lease_handle.flush()
            self.store.initialize()
        except BaseException:
            self._claimed_stores.discard(store_key)
            if self._lease_handle is not None:
                self._release_lease()
            raise
        self.python_executable = python_executable or sys.executable
        self.worker_module = worker_module
        self.on_event = on_event
        self.process: subprocess.Popen[str] | None = None
        self._log_handles: tuple[object, object] | None = None
        self._log_threads: tuple[threading.Thread, threading.Thread] | None = None
        self._log_errors: list[BaseException] = []
        self.active_job_id: str | None = None
        self.worker_token: str | None = None
        self.orphaned_live_worker = False
        self.worker_heartbeat_stale = False
        self._requests: dict[str, JobExecutionRequest] = {}
        self._supervision_error: str | None = None

    def close(self) -> None:
        """Release the in-process controller claim after the GUI stops polling."""

        self._claimed_stores.discard(self._claimed_store_key)
        self._release_lease()

    @property
    def supervision_error(self) -> str | None:
        """Return a latched controller health error for the active job."""

        return self._supervision_error

    def _open_lease(self):
        handle = self._lease_path.open("a+b")
        try:
            handle.seek(0)
            if handle.read(1) == b"":
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            handle.close()
            raise RuntimeError("another JobController already owns this management DB") from None

    def _release_lease(self) -> None:
        if self._lease_handle is None:
            return
        with contextlib.suppress(OSError):
            if os.name == "nt":
                import msvcrt

                self._lease_handle.seek(0)
                msvcrt.locking(self._lease_handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._lease_handle.fileno(), fcntl.LOCK_UN)
        self._lease_handle.close()
        self._lease_handle = None

    def queue(self, request: JobExecutionRequest, *, original_job_id: str | None = None) -> str:
        job_id, _ = self.store.create_job(request, original_job_id=original_job_id)
        self._requests[job_id] = request
        self.store.append_event(JobEvent(
            job_id, "job_queued", event_id=f"{job_id}:controller:queued", sequence=-1
        ))
        return job_id

    def reconcile(self) -> tuple[str, ...]:
        """Classify jobs from a previous GUI process without auto-resuming."""

        self.orphaned_live_worker = False
        changed: list[str] = []
        for row in self.store.list_jobs(limit=1000):
            if row["state"] not in ACTIVE_JOB_STATES:
                continue
            identity_path = self.store.job_dir(row["job_id"]) / "worker.identity"
            try:
                identity = json.loads(identity_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                identity = {}
            identity_pid = identity.get("pid")
            identity_live = _pid_alive(identity_pid)
            if identity_live or _pid_alive(row["worker_pid"]):
                # The persisted PID must agree with the child-written token.
                # We still do not reattach; a live unverified child blocks a
                # second worker until an operator resolves it.
                self.orphaned_live_worker = True
                continue
            self.store.mark_interrupted(
                row["job_id"],
                reason="GUI restarted before worker identity could be verified",
            )
            changed.append(row["job_id"])
        return tuple(changed)

    def start_next(self) -> str | None:
        if self.process is not None and self.process.poll() is None:
            return self.active_job_id
        if self.orphaned_live_worker:
            return None
        for row in self.store.queued_jobs():
            job_id = row["job_id"]
            self.start_job(job_id)
            if self.process is not None:
                return job_id
        return None

    def start_job(self, job_id: str) -> str:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("another worker is already active")
        if self.orphaned_live_worker:
            raise RuntimeError("an unverified worker is still live")
        row = self.store.get_job(job_id)
        if row["state"] != "queued":
            raise RuntimeError(f"job is not queued: {job_id}")
        if self.store.cancel_requested(job_id):
            self.store.set_state(job_id, "cancelled", summary={"reason": "cancelled while queued"})
            return job_id
        request_path = self.store.job_dir(job_id) / "request.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        gate_path = self.store.job_dir(job_id) / "start.gate"
        self._write_gate(gate_path, "wait")
        request = self._requests.get(job_id)
        request_payload = (
            execution_request_payload(request) if request is not None else json.loads(row["request_json"])
        )
        explicit_endpoint = request.cdp_endpoint if request is not None else None
        request_payload["cdp_endpoint"] = None
        request_path.write_text(json.dumps(request_payload, ensure_ascii=False), encoding="utf-8")
        # Prefix the value so argparse never interprets a random leading
        # hyphen from urlsafe base64 as another command-line option.
        token = "worker-" + secrets.token_urlsafe(24)
        command = [
            self.python_executable,
            "-u",
            "-m",
            self.worker_module,
            "--job-id",
            job_id,
            "--job-dir",
            str(self.store.job_dir(job_id).resolve()),
            "--request-json",
            str(request_path.resolve()),
            "--worker-token",
            token,
            "--start-gate",
            str(gate_path.resolve()),
        ]
        job_dir = self.store.job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = (job_dir / "stdout.log").open("a", encoding="utf-8")
        stderr_log = (job_dir / "stderr.log").open("a", encoding="utf-8")
        worker_env = os.environ.copy()
        # Only the child worker is made unbuffered.  The GUI/controller and
        # unrelated CLI invocations retain their existing environment.
        worker_env["PYTHONUNBUFFERED"] = "1"
        worker_env["PYTHONIOENCODING"] = "utf-8"
        # A previous controller or shell must not silently provide an
        # endpoint when this request has no explicit transient override.
        worker_env.pop("CRAWLER_CDP_ENDPOINT_OVERRIDE", None)
        if explicit_endpoint:
            # Keep the explicit value transient and above site-specific .env
            # endpoints. It is never written to request.json or management DB.
            worker_env["CRAWLER_CDP_ENDPOINT_OVERRIDE"] = explicit_endpoint
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env=worker_env,
        )
        self.process = process
        self.active_job_id = job_id
        self.worker_token = token
        self._log_handles = (stdout_log, stderr_log)
        self._log_errors = []
        self._supervision_error = None
        self._log_threads = (
            threading.Thread(target=self._copy_log, args=(process.stdout, stdout_log, self._log_errors), daemon=True),
            threading.Thread(target=self._copy_log, args=(process.stderr, stderr_log, self._log_errors), daemon=True),
        )
        for thread in self._log_threads:
            thread.start()
        try:
            self.store.set_worker_identity(job_id, pid=process.pid, token=token)
            self.store.append_event(JobEvent(
                job_id, "task_planning", event_id=f"{job_id}:controller:planning", sequence=-2
            ))
            # Keep the child behind the barrier until all durable start data is
            # written.  A gate write failure must follow the same fail-closed
            # path as a management DB failure.
            self._write_gate(gate_path, "go")
        except BaseException:
            child_pid = _verified_worker_pid(job_dir, token)
            if child_pid is not None and child_pid != process.pid:
                _terminate_pid(child_pid)
            with contextlib.suppress(OSError):
                self._write_gate(gate_path, "cancel")
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                process.wait(timeout=10)
            if self._log_threads is not None:
                for thread in self._log_threads:
                    thread.join(timeout=2)
            for stream in (stdout_log, stderr_log):
                with contextlib.suppress(OSError):
                    stream.close()
            with contextlib.suppress(Exception):
                self.store.mark_interrupted(job_id, reason="worker startup barrier failed")
            self._log_threads = None
            self.process = None
            self.active_job_id = None
            self.worker_token = None
            self._log_handles = None
            raise
        return job_id

    def poll(self) -> str | None:
        """Import complete events and finalize a finished child process."""

        if self.active_job_id is None:
            return None
        job_id = self.active_job_id
        if self._supervision_error is not None:
            # Once supervision has failed, a later successful-looking event
            # cannot repair the evidence gap. Keep requesting safe stop and
            # finish this job as unverified.
            self._write_cancel_sentinel(job_id)
            if self.process is None or self.process.poll() is not None:
                return self._mark_unverified(job_id, self._supervision_error)
            return None
        try:
            self.store.import_events(job_id)
        except BaseException as exc:  # noqa: BLE001 - DB failure is fail-closed
            return self._handle_supervision_failure(job_id, exc)
        heartbeat_path = self.store.job_dir(job_id) / "worker.heartbeat.json"
        try:
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            heartbeat = {}
        if heartbeat.get("token") == self.worker_token and heartbeat.get("observed_at"):
            try:
                observed = datetime.fromisoformat(str(heartbeat["observed_at"]))
                self.worker_heartbeat_stale = (
                    (datetime.now(UTC) - observed.astimezone(UTC)).total_seconds() > 15
                )
            except ValueError:
                self.worker_heartbeat_stale = True
            try:
                self.store.record_worker_heartbeat(
                    job_id,
                    token=self.worker_token or "",
                    observed_at=str(heartbeat["observed_at"]),
                )
            except BaseException as exc:  # noqa: BLE001
                return self._handle_supervision_failure(job_id, exc)
        else:
            self.worker_heartbeat_stale = True
        if self._log_errors and self.process is not None and self.process.poll() is None:
            # A log sink failure is a controller-side safety failure.  Ask the
            # worker to stop at its next safe boundary while it is still live;
            # never let it continue into another candidate/pass.
            with contextlib.suppress(Exception):
                self.request_stop()
        if self.process is None or self.process.poll() is None:
            return None
        returncode = self.process.returncode
        while self.store.events_pending(job_id):
            before = self.store._event_offsets.get(job_id, 0)
            try:
                self.store.import_events(job_id, max_events=500)
            except BaseException as exc:  # noqa: BLE001
                return self._handle_supervision_failure(job_id, exc)
            after = self.store._event_offsets.get(job_id, 0)
            if after <= before:
                return self._mark_unverified(
                    job_id,
                    "worker event log ended with an incomplete line; result is unverified",
                )
        if not _identity_matches(
            self.store.job_dir(job_id), pid=self.process.pid if self.process else None,
            token=self.worker_token,
        ):
            return self._mark_unverified(
                job_id, "worker identity/token mismatch; result is unverified"
            )
        if self._log_threads is not None:
            for thread in self._log_threads:
                thread.join(timeout=2)
            if any(thread.is_alive() for thread in self._log_threads):
                return self._mark_unverified(
                    job_id, "worker log capture did not drain; result is unverified"
                )
        if self._log_errors:
            return self._mark_unverified(
                job_id, "worker log capture failed; result is unverified"
            )
        try:
            cancelled = self.store.cancel_requested(job_id)
            summary = self.store.terminal_event_summary(job_id)
        except BaseException as exc:  # noqa: BLE001
            return self._handle_supervision_failure(job_id, exc)
        has_success = bool(summary["has_success"])
        has_failure = bool(summary["has_failure"])
        expected_tasks = int(summary["expected_tasks"])
        authoritative_success = (
            returncode == 0
            and not has_failure
            and bool(summary["job_succeeded"])
            and bool(summary["process_succeeded"])
            and int(summary["finished_tasks"]) == expected_tasks
        )
        if cancelled:
            state = "partial" if has_success else "cancelled"
        elif authoritative_success:
            state = "succeeded"
        elif has_success:
            state = "partial"
        else:
            state = "failed"
        try:
            self.store.set_state(job_id, state, summary={
                "returncode": returncode,
                "success": has_success,
                "failure": has_failure,
                "cancel_requested": cancelled,
            })
        except BaseException as exc:  # noqa: BLE001
            return self._handle_supervision_failure(job_id, exc)
        self.process = None
        if self._log_handles is not None:
            for stream in self._log_handles:
                stream.close()
            self._log_handles = None
            self._log_threads = None
        self.active_job_id = None
        self.worker_token = None
        self.worker_heartbeat_stale = False
        return state

    def request_stop(self) -> None:
        if self.active_job_id is None:
            return
        job_id = self.active_job_id
        # The sentinel is independent of SQLite so a management DB failure
        # still reaches the worker at its next safe checkpoint.
        self._write_cancel_sentinel(job_id)
        with contextlib.suppress(Exception):
            self.store.request_cancel(job_id)
        with contextlib.suppress(Exception):
            self.store.append_event(JobEvent(
                job_id,
                "cancel_requested",
                event_id=f"{job_id}:controller:cancel",
                sequence=-3,
            ))

    def force_stop(self) -> None:
        """Emergency-only termination; the result remains consumption-unknown."""

        if self.process is None or self.active_job_id is None:
            return
        job_id = self.active_job_id
        child_pid = _verified_worker_pid(self.store.job_dir(job_id), self.worker_token)
        child_terminated = child_pid is None or _terminate_pid(child_pid)
        self.process.kill()
        self.process.wait(timeout=10)
        if self._log_handles is not None and self._log_threads is not None:
            for thread in self._log_threads:
                thread.join(timeout=2)
        self._mark_unverified(
            job_id, "worker force terminated; resource consumption unknown"
        )
        if not child_terminated:
            # We could not prove that the real child exited; block a new job
            # until the operator resolves the live worker identity.
            self.orphaned_live_worker = True

    def rerun(self, job_id: str, request: JobExecutionRequest) -> str:
        """Queue a new job from a fresh caller preview."""

        return self.queue(request, original_job_id=job_id)

    def _mark_unverified(self, job_id: str, reason: str) -> str:
        with contextlib.suppress(Exception):
            self.store.mark_interrupted(job_id, reason=reason)
        self._write_supervision_error(job_id, reason)
        if self._log_handles is not None:
            for stream in self._log_handles:
                with contextlib.suppress(OSError):
                    stream.close()
        self._log_handles = None
        self._log_threads = None
        self.process = None
        self.active_job_id = None
        self.worker_token = None
        self.worker_heartbeat_stale = False
        return "interrupted"

    def _handle_supervision_failure(self, job_id: str, error: BaseException) -> str | None:
        reason = "management supervision failed; worker result is unverified: " + sanitize_text(str(error))
        self._supervision_error = reason
        self._write_cancel_sentinel(job_id)
        self._write_supervision_error(job_id, reason)
        if self.process is None or self.process.poll() is not None:
            return self._mark_unverified(job_id, reason)
        return None

    def _write_cancel_sentinel(self, job_id: str) -> None:
        sentinel = self.store.job_dir(job_id) / "cancel.request"
        temporary = sentinel.with_suffix(".supervision.tmp")
        try:
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text("controller-supervision-failure", encoding="utf-8")
            os.replace(temporary, sentinel)
        except OSError as exc:
            self._supervision_error = (
                self._supervision_error
                or "unable to write worker cancel sentinel: " + sanitize_text(str(exc))
            )
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink()

    def _write_supervision_error(self, job_id: str, reason: str) -> None:
        marker = self.store.job_dir(job_id) / "supervision-error.json"
        temporary = marker.with_suffix(".tmp")
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps({"job_id": job_id, "reason": sanitize_text(reason)}, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temporary, marker)
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink()

    @staticmethod
    def _write_gate(path: Path, value: str) -> None:
        """Atomically publish a worker start/cancel gate."""

        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            temporary.write_text(value, encoding="utf-8")
            os.replace(temporary, path)
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink()

    @staticmethod
    def _copy_log(source: object, target: object, errors: list[BaseException]) -> None:
        if source is None:
            return
        try:
            for line in source:  # type: ignore[union-attr]
                target.write(sanitize_text(line))  # type: ignore[union-attr]
                target.flush()  # type: ignore[union-attr]
        except BaseException as exc:  # noqa: BLE001 - controller handles fail-closed
            errors.append(exc)


__all__ = ["JobController"]
