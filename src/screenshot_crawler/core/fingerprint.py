"""Stable SHA-256 fingerprint helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path


def fingerprint_bytes(data: bytes) -> str:
    """Return a stable SHA-256 hex digest."""

    return hashlib.sha256(data).hexdigest()


def fingerprint_file(path: str | Path) -> str:
    """Hash a file without changing or logging its contents."""

    return fingerprint_bytes(Path(path).read_bytes())
