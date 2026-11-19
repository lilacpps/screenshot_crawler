import ctypes
import os

import pytest

import screenshot_crawler.management.process_identity as identity


@pytest.mark.parametrize("problem", [None, "reference", "short", "offset", "missing", "zero"])
def test_snapshot_creation_identity_requires_valid_reference_and_bounds(problem):
    first = identity._SystemProcessPrefix()
    second = identity._SystemProcessPrefix()
    first.pid, first.create_time = 123, 100
    second.pid, second.create_time = 456, 200
    first.next_offset = ctypes.sizeof(first)
    if problem == "offset":
        first.next_offset = 1
    elif problem == "zero":
        second.create_time = 0
    data = bytes(first) + bytes(second)
    if problem == "short":
        data = data[:-1]
    result = identity._snapshot_start_identity(data, 789 if problem == "missing" else 456,
                                             123, "wrong" if problem == "reference" else "100")
    assert result == ("200" if problem is None else None)


@pytest.mark.skipif(os.name != "nt", reason="Windows native process identity boundary")
def test_windows_snapshot_and_access_denied_fallback(monkeypatch):
    pid = os.getpid()
    direct = identity._windows_handle_start_identity(pid)
    assert direct is not None
    assert identity._windows_snapshot_start_identity(pid) == direct
    assert identity._windows_snapshot_start_identity(0x7FFFFFFF) is None
    original = identity._windows_handle_start_identity
    calls = []

    def denied_once(value):
        calls.append(value)
        return None if len(calls) == 1 else original(value)

    monkeypatch.setattr(identity, "_windows_handle_start_identity", denied_once)
    assert identity.process_start_identity(pid) == direct
    assert len(calls) == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows native process identity boundary")
def test_windows_snapshot_unavailable_or_unknown_layout_stays_unknown(monkeypatch):
    monkeypatch.setattr(identity, "_windows_handle_start_identity", lambda _pid: None)
    assert identity.process_start_identity(os.getpid()) is None


@pytest.mark.parametrize("problem", ["denied", "resizing", "oversize", "invalid_length", "reference"])
def test_windows_snapshot_query_failure_is_bounded(monkeypatch, problem):
    monkeypatch.setattr(identity, "_windows_handle_start_identity", lambda _pid: "100")
    calls = []

    class Query:
        def __call__(self, _kind, buffer, capacity, returned):
            calls.append(capacity)
            if problem in {"resizing", "oversize"}:
                returned._obj.value = 32 * 1024 * 1024 if problem == "oversize" else capacity + 1
                return -1073741820  # STATUS_INFO_LENGTH_MISMATCH
            if problem == "denied":
                return -1073741790  # STATUS_ACCESS_DENIED
            if problem == "reference":
                entry = identity._SystemProcessPrefix()
                entry.pid, entry.create_time = os.getpid(), 999
                ctypes.memmove(buffer, bytes(entry), ctypes.sizeof(entry))
                returned._obj.value = ctypes.sizeof(entry)
            else:
                returned._obj.value = capacity + 1
            return 0

    class Native:
        NtQuerySystemInformation = Query()

    monkeypatch.setattr(ctypes, "WinDLL", lambda _name: Native(), raising=False)
    assert identity._windows_snapshot_start_identity(123) is None
    assert len(calls) == (4 if problem == "resizing" else 1)
