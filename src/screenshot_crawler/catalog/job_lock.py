"""Fail-fast per-Catalog job exclusion shared by async and sync workflows."""

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self


class CatalogJobLockError(RuntimeError):
    """Raised when another job currently owns the Catalog lock."""


@dataclass(slots=True)
class _LockState:
    owner: tuple[str, int]
    handle: object | None = None
    depth: int = 1


_registry_guard = threading.Lock()
_active: dict[str, _LockState] = {}


class CatalogJobLock:
    """Advisory lock that permits only same-task nesting in one process.

    The stable sibling lock file is intentionally never unlinked: unlinking a
    held path can split processes across different inodes and defeat exclusion.
    """

    def __init__(self, catalog_path: str | Path) -> None:
        self.catalog_path = Path(catalog_path).resolve(strict=False)
        self._key = os.path.normcase(str(self.catalog_path))
        self._owner: tuple[str, int] | None = None
        self._state: _LockState | None = None
        self._nested = False

    def __enter__(self) -> Self:
        if self._state is not None:
            raise CatalogJobLockError("This Catalog job lock object is already entered")
        owner = _current_owner()
        self._nested = False
        with _registry_guard:
            existing = _active.get(self._key)
            if existing is not None:
                if existing.owner != owner:
                    raise CatalogJobLockError(
                        f"Another job is already using Catalog '{self.catalog_path}'"
                    )
                existing.depth += 1
                self._state = existing
                self._nested = True
                self._owner = owner
                return self
            state = _LockState(owner=owner)
            _active[self._key] = state
            self._state = state
            self._owner = owner

        try:
            self._acquire_file_lock()
        except BaseException:
            with _registry_guard:
                _active.pop(self._key, None)
            self._state = None
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        state = self._state
        if state is None:
            return
        with _registry_guard:
            state.depth -= 1
            should_release = state.depth == 0
            if should_release:
                _active.pop(self._key, None)
        release_handle = should_release and not self._nested
        self._state = None
        self._nested = False
        self._owner = None
        if release_handle:
            self._release_file_lock(state.handle)

    @property
    def lock_path(self) -> Path:
        return self.catalog_path.with_name(f".{self.catalog_path.name}.job.lock")

    def _acquire_file_lock(self) -> None:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+b", buffering=0)
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise CatalogJobLockError(
                f"Another process is already using Catalog '{self.catalog_path}'"
            ) from exc
        assert self._state is not None
        self._state.handle = handle

    @staticmethod
    def _release_file_lock(handle: object | None) -> None:
        if handle is None:
            return
        file_handle = handle
        if os.name == "nt":
            import msvcrt

            file_handle.seek(0)  # type: ignore[attr-defined]
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
        file_handle.close()  # type: ignore[attr-defined]


def _current_owner() -> tuple[str, int]:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    if task is not None:
        return ("task", id(task))
    return ("thread", threading.get_ident())
