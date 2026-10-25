"""Bounded, Qt-free readers for a management job's raw worker logs.

The worker has two independent streams.  This reader deliberately keeps them
separate and only opens the two fixed log names owned by ``JobStore``; callers
cannot use event payloads to redirect it to an arbitrary path.
"""

from __future__ import annotations

import codecs
from pathlib import Path
from typing import Any

_STREAMS = frozenset({"stdout", "stderr"})


class LogTailReader:
    """Read bounded incremental text from one management job's log directory.

    ``job_dir`` may be a concrete directory, or a ``JobStore`` together with
    ``job_id``.  The latter form keeps path ownership with ``JobStore`` while
    making the reader usable without importing Qt or any GUI module.
    """

    def __init__(
        self,
        job_dir: str | Path | Any,
        job_id: str | None = None,
        *,
        max_bytes_per_read: int = 64 * 1024,
        initial_tail_bytes: int = 64 * 1024,
    ) -> None:
        if job_id is not None:
            resolver = getattr(job_dir, "job_dir", None)
            if resolver is None:
                raise TypeError("job_dir must provide job_dir(job_id) when job_id is supplied")
            job_dir = resolver(job_id)
        self.job_dir = Path(job_dir)
        if max_bytes_per_read <= 0 or initial_tail_bytes <= 0:
            raise ValueError("log read limits must be positive")
        self.max_bytes_per_read = max_bytes_per_read
        self.initial_tail_bytes = initial_tail_bytes
        self._offsets = {stream: 0 for stream in _STREAMS}
        self._decoders = {
            stream: codecs.getincrementaldecoder("utf-8")(errors="replace")
            for stream in _STREAMS
        }
        self._started = {stream: False for stream in _STREAMS}
        self._identities: dict[str, tuple[int, int, int] | None] = {
            stream: None for stream in _STREAMS
        }
        self._metadata = {
            stream: {
                "tail_omitted": False,
                "history_omitted": False,
                "initial_offset": 0,
                "initial_size": None,
                "file_present": False,
            }
            for stream in _STREAMS
        }

    @staticmethod
    def _identity(stat_result: Any) -> tuple[int, int, int]:
        """Return an identity based on immutable file identity fields.

        ``st_ctime_ns`` is metadata-change time on POSIX and therefore changes
        on ordinary appends.  Windows exposes ``st_birthtime_ns`` as the
        creation timestamp, which is safe as a fallback when inode numbers are
        unavailable.
        """

        return (
            int(getattr(stat_result, "st_dev", 0)),
            int(getattr(stat_result, "st_ino", 0)),
            int(getattr(stat_result, "st_birthtime_ns", 0)),
        )

    def _path(self, stream: str) -> Path:
        if stream not in _STREAMS:
            raise ValueError("stream must be 'stdout' or 'stderr'")
        return self.job_dir / f"{stream}.log"

    def reset(self, stream: str | None = None) -> None:
        """Forget offsets and decoder state for one or both streams."""

        streams = _STREAMS if stream is None else (stream,)
        for name in streams:
            self._path(name)  # validate before mutating state
            self._offsets[name] = 0
            self._decoders[name] = codecs.getincrementaldecoder("utf-8")(errors="replace")
            self._started[name] = False
            self._identities[name] = None
            self._metadata[name] = {
                "tail_omitted": False,
                "history_omitted": False,
                "initial_offset": 0,
                "initial_size": None,
                "file_present": False,
            }

    def read(self, stream: str) -> str:
        """Return at most one bounded incremental chunk from ``stream``."""

        path = self._path(stream)
        try:
            stat_result = path.stat()
        except OSError:
            # A deleted log is a new stream even when the replacement later
            # has the same size as the old file.
            self.reset(stream)
            return ""
        identity = self._identity(stat_result)
        size = stat_result.st_size
        if self._identities[stream] is not None and identity != self._identities[stream]:
            self.reset(stream)
        self._identities[stream] = identity
        self._metadata[stream]["file_present"] = True

        offset = self._offsets[stream]
        if size < offset:
            # A truncated/replaced log is a new stream.  Do not retain stale
            # decoder bytes from the previous file.
            self.reset(stream)
            offset = 0
            try:
                stat_result = path.stat()
            except OSError:
                return ""
            size = stat_result.st_size
            self._identities[stream] = self._identity(stat_result)
            self._metadata[stream]["file_present"] = True
        if not self._started[stream] and size > self.initial_tail_bytes:
            offset = size - self.initial_tail_bytes
            self._metadata[stream].update(
                tail_omitted=True,
                history_omitted=True,
                initial_offset=offset,
                initial_size=size,
            )
            # A bounded tail may begin in the middle of a UTF-8 code point.
            # Skip continuation bytes so the first returned text is valid and
            # never starts with an artificial replacement character.
            try:
                with path.open("rb") as handle:
                    handle.seek(offset)
                    # UTF-8 code points contain at most three continuation
                    # bytes after their leading byte.  Keep malformed files
                    # bounded even when a tail begins in a long continuation
                    # run.
                    for _ in range(3):
                        if offset >= size:
                            break
                        first = handle.read(1)
                        if not first or first[0] & 0xC0 != 0x80:
                            break
                        offset += 1
            except (OSError, IndexError):
                return ""
            self._offsets[stream] = offset
        self._started[stream] = True
        if size <= offset:
            return ""

        count = min(size - offset, self.max_bytes_per_read)
        try:
            with path.open("rb") as handle:
                handle.seek(offset)
                data = handle.read(count)
        except OSError:
            return ""
        self._offsets[stream] += len(data)
        return self._decoders[stream].decode(data, final=False)

    def read_all(self) -> dict[str, str]:
        """Read one bounded chunk from both streams, preserving separation."""

        return {stream: self.read(stream) for stream in ("stdout", "stderr")}

    def offsets(self) -> dict[str, int]:
        """Return a copy of per-stream byte offsets for diagnostics/tests."""

        return dict(self._offsets)

    def metadata(self, stream: str) -> dict[str, object]:
        """Return bounded stream state, including initial-tail omission."""

        self._path(stream)  # validate before exposing state
        return dict(self._metadata[stream])


__all__ = ["LogTailReader"]
