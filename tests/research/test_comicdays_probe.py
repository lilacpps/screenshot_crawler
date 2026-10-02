"""Research helper contract tests for the bounded Comic DAYS probe."""

from __future__ import annotations

import asyncio

import pytest

from poc.comicdays_probe import (
    bounded_fetch_expression,
    evaluate_bounded,
    navigation_snapshot,
    page_metadata,
)


class StalledPage:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def evaluate(self, expression: str) -> None:
        del expression
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled = True


@pytest.mark.asyncio
async def test_evaluate_bounded_cancels_a_stalled_page_evaluation() -> None:
    page = StalledPage()

    with pytest.raises(asyncio.TimeoutError):
        await evaluate_bounded(page, "() => stalled", timeout_seconds=0.01)

    assert page.started.is_set()
    assert page.cancelled


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [page_metadata, navigation_snapshot])
async def test_probe_snapshots_cancel_a_stalled_page_evaluation(operation) -> None:
    page = StalledPage()

    with pytest.raises(asyncio.TimeoutError):
        await operation(page, timeout_seconds=0.01)

    assert page.cancelled


def test_bounded_fetch_expression_has_abort_and_timer_cleanup() -> None:
    expression = bounded_fetch_expression("return await fetch('/local-stall');")

    assert "AbortController" in expression
    assert "controller.abort()" in expression
    assert "clearTimeout(timer)" in expression
