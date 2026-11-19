"""Small stdlib-only process start identity helpers for worker recovery."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path


def process_start_identity(pid: int) -> str | None:
    """Return an OS process creation identity when it can be read safely."""

    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name == "nt":
        return _windows_start_identity(pid)
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
        # Linux starttime is field 22 (index 21), measured in clock ticks.
        return fields[21]
    except (OSError, IndexError, ValueError):
        return None


def process_is_alive(pid: int) -> bool:
    """Check liveness without using Windows ``os.kill(pid, 0)`` semantics."""

    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # ERROR_INVALID_PARAMETER means the PID does not exist. Other
            # failures (notably access denied) are unknown and stay live to
            # prevent an unsafe restart.
            return ctypes.get_last_error() != 87
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True

def _windows_start_identity(pid: int) -> str | None:
    direct = _windows_handle_start_identity(pid)
    return direct if direct is not None else _windows_snapshot_start_identity(pid)


def _windows_handle_start_identity(pid: int) -> str | None:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return str(value)
    finally:
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(handle)


class _UnicodeString(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint16), ("maximum_length", ctypes.c_uint16),
                ("buffer", ctypes.c_void_p)]


class _SystemProcessPrefix(ctypes.Structure):
    # SystemProcessInformation (NT6+) prefix; no image-name pointers are read.
    # The internal creation-time layout is accepted only after checking it
    # against GetProcessTimes for our own live process in the SAME snapshot.
    _fields_ = [
        ("next_offset", ctypes.c_uint32), ("thread_count", ctypes.c_uint32),
        ("private_working_set", ctypes.c_int64), ("hard_fault_count", ctypes.c_uint32),
        ("thread_high_watermark", ctypes.c_uint32), ("cycle_time", ctypes.c_uint64),
        ("create_time", ctypes.c_int64), ("user_time", ctypes.c_int64),
        ("kernel_time", ctypes.c_int64), ("image_name", _UnicodeString),
        ("base_priority", ctypes.c_int32), ("pid", ctypes.c_void_p),
    ]


def _snapshot_start_identity(data: bytes, pid: int, reference_pid: int, reference_start: str) -> str | None:
    """Validate every offset and an independent creation-time reference."""
    offset = 0
    result = reference = None
    size = ctypes.sizeof(_SystemProcessPrefix)
    while offset + size <= len(data):
        entry = _SystemProcessPrefix.from_buffer_copy(data, offset)
        if entry.pid == reference_pid:
            reference = str(entry.create_time)
        if entry.pid == pid and entry.create_time > 0:
            result = str(entry.create_time)
        if entry.next_offset == 0:
            return result if reference == reference_start else None
        if entry.next_offset < size or offset + entry.next_offset + size > len(data):
            return None
        offset += entry.next_offset
    return None


def _windows_snapshot_start_identity(pid: int) -> str | None:
    """Bounded read-only fallback for processes denying OpenProcess.

    NtQuerySystemInformation may change or be unavailable. A failed query,
    unknown layout or missing reference remains unknown, never exit proof.
    """
    reference = _windows_handle_start_identity(os.getpid())
    if reference is None:
        return None
    try:
        query = ctypes.WinDLL("ntdll").NtQuerySystemInformation
        query.argtypes = [wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        query.restype = ctypes.c_int32
        capacity = 1024 * 1024
        for _attempt in range(4):
            if capacity > 16 * 1024 * 1024:
                return None
            buffer = ctypes.create_string_buffer(capacity)
            returned = wintypes.ULONG()
            status = query(5, buffer, capacity, ctypes.byref(returned))
            if status == 0:
                if not 0 < returned.value <= capacity:
                    return None
                return _snapshot_start_identity(buffer.raw[:returned.value], pid, os.getpid(), reference)
            if status & 0xFFFFFFFF != 0xC0000004:  # STATUS_INFO_LENGTH_MISMATCH
                return None
            capacity = max(capacity * 2, returned.value)
    except (OSError, AttributeError, ValueError, OverflowError):
        return None
    return None


__all__ = ["process_is_alive", "process_start_identity"]
