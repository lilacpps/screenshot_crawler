from pathlib import Path
from types import SimpleNamespace

import pytest

from screenshot_crawler.management.log_tail import LogTailReader


def test_log_tail_reads_two_streams_incrementally_and_preserves_utf8_boundaries(tmp_path: Path) -> None:
    (tmp_path / "stdout.log").write_bytes("先頭\n".encode())
    (tmp_path / "stderr.log").write_bytes(b"warning\n")
    reader = LogTailReader(tmp_path, max_bytes_per_read=4, initial_tail_bytes=100)

    assert reader.read("stdout") == "先"
    assert reader.read("stdout") == "頭\n"
    assert reader.read("stdout") == ""
    assert reader.read("stderr") == "warn"
    assert reader.read_all() == {"stdout": "", "stderr": "ing\n"}


def test_log_tail_handles_multibyte_split_across_reads(tmp_path: Path) -> None:
    path = tmp_path / "stdout.log"
    path.write_bytes("あ".encode()[:1])
    reader = LogTailReader(tmp_path, max_bytes_per_read=1, initial_tail_bytes=100)
    assert reader.read("stdout") == ""
    with path.open("ab") as stream:
        stream.write("あ\n".encode()[1:])
    assert reader.read("stdout") == ""
    assert reader.read("stdout") == "あ"
    assert reader.read("stdout") == "\n"


def test_log_tail_reinitializes_after_truncate_and_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "stdout.log"
    reader = LogTailReader(tmp_path, initial_tail_bytes=100)
    assert reader.read("stdout") == ""
    path.write_bytes(b"before\n")
    assert reader.read("stdout") == "before\n"
    path.write_bytes(b"afterx")
    assert reader.read("stdout") == "afterx"


def test_log_tail_initial_history_is_bounded(tmp_path: Path) -> None:
    (tmp_path / "stdout.log").write_text("0123456789", encoding="utf-8")
    reader = LogTailReader(tmp_path, initial_tail_bytes=4, max_bytes_per_read=99)
    assert reader.read("stdout") == "6789"
    metadata = reader.metadata("stdout")
    assert metadata["tail_omitted"] is True
    assert metadata["history_omitted"] is True
    assert metadata["initial_offset"] == 6
    assert metadata["initial_size"] == 10


def test_log_tail_preserves_crlf_and_long_lines_without_duplicate_or_loss(tmp_path: Path) -> None:
    payload = (b"x" * 1_048_575) + b"\r\nlast\r\n"
    (tmp_path / "stdout.log").write_bytes(payload)
    reader = LogTailReader(tmp_path, max_bytes_per_read=4093, initial_tail_bytes=len(payload) + 1)
    chunks: list[str] = []
    while True:
        chunk = reader.read("stdout")
        if not chunk:
            break
        chunks.append(chunk)
    assert "".join(chunks).encode() == payload


def test_log_tail_recreated_file_resets_same_size_and_decoder_state(tmp_path: Path) -> None:
    path = tmp_path / "stdout.log"
    path.write_bytes(b"old!\n")
    reader = LogTailReader(tmp_path, max_bytes_per_read=1, initial_tail_bytes=100)
    assert reader.read("stdout") == "o"
    path.unlink()
    assert reader.read("stdout") == ""
    # Same byte length as the old file: size-only detection would duplicate
    # or skip the replacement, and could retain the previous UTF-8 decoder.
    path.write_bytes(b"new!\n")
    assert reader.read("stdout") == "n"
    assert reader.read("stdout") == "e"
    assert reader.metadata("stdout")["file_present"] is True


def test_log_tail_identity_ignores_posix_metadata_change_time() -> None:
    first = SimpleNamespace(st_dev=7, st_ino=9, st_ctime_ns=100, st_birthtime_ns=0)
    appended = SimpleNamespace(st_dev=7, st_ino=9, st_ctime_ns=200, st_birthtime_ns=0)
    assert LogTailReader._identity(first) == LogTailReader._identity(appended)


def test_log_tail_continuation_skip_is_bounded(tmp_path: Path) -> None:
    # The initial tail starts in an invalid run of continuation bytes.
    (tmp_path / "stdout.log").write_bytes((b"\x80" * 128) + b"end")
    reader = LogTailReader(tmp_path, initial_tail_bytes=8, max_bytes_per_read=8)
    chunk = reader.read("stdout")
    assert len(chunk.encode()) <= 8 * 3
    assert reader.offsets()["stdout"] <= 131


def test_log_tail_rejects_arbitrary_stream_names(tmp_path: Path) -> None:
    reader = LogTailReader(tmp_path)
    with pytest.raises(ValueError):
        reader.read("events")
