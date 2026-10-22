from __future__ import annotations

import asyncio
import subprocess
import sys
import time

import pytest

from screenshot_crawler.catalog.job_lock import CatalogJobLock, CatalogJobLockError


@pytest.mark.asyncio
async def test_job_lock_allows_same_task_nesting_and_rejects_other_task(tmp_path) -> None:
    catalog = tmp_path / "catalog.sqlite"
    lock = CatalogJobLock(catalog)
    with lock:
        nested = CatalogJobLock(catalog)
        with nested:
            pass
        with nested:
            pass

        async def competing_job() -> bool:
            try:
                with CatalogJobLock(catalog):
                    return True
            except CatalogJobLockError:
                return False

        assert await asyncio.create_task(competing_job()) is False

    assert lock.lock_path.exists()


@pytest.mark.asyncio
async def test_lock_owner_is_resolved_when_entered_not_constructed(tmp_path) -> None:
    catalog = tmp_path / "catalog.sqlite"
    lock_created_by_parent = CatalogJobLock(catalog)
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        with lock_created_by_parent:
            started.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await started.wait()
    try:
        with pytest.raises(CatalogJobLockError), CatalogJobLock(catalog):
            pass
    finally:
        release.set()
        await task


def test_lock_file_is_not_created_by_construction(tmp_path) -> None:
    catalog = tmp_path / "nested" / "catalog.sqlite"
    lock = CatalogJobLock(catalog)
    assert not catalog.parent.exists()
    assert not lock.lock_path.exists()


def test_job_lock_is_released_after_exception(tmp_path) -> None:
    catalog = tmp_path / "catalog.sqlite"
    with pytest.raises(RuntimeError, match="failure"), CatalogJobLock(catalog):
        raise RuntimeError("failure")
    with CatalogJobLock(catalog):
        pass


def test_job_lock_excludes_a_second_process(tmp_path) -> None:
    catalog = tmp_path / "catalog.sqlite"
    ready = tmp_path / "child-ready"
    code = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from screenshot_crawler.catalog.job_lock import CatalogJobLock\n"
        "with CatalogJobLock(sys.argv[1]):\n"
        "    Path(sys.argv[2]).write_text('ready')\n"
        "    time.sleep(8)\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(catalog), str(ready)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), child.stderr.read() if child.poll() is not None else "child did not start"
        with pytest.raises(CatalogJobLockError), CatalogJobLock(catalog):
            pass
    finally:
        child.terminate()
        child.wait(timeout=5)
        if child.stdout is not None:
            child.stdout.close()
        if child.stderr is not None:
            child.stderr.close()

