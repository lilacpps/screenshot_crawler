"""Bounded, read-only recovery of an ambiguous viewer forward click.

Adapters supply their existing body observations. This helper never sends a
second click, classifies a terminal screen, or grants access.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.errors import UnknownPageStateError


@dataclass(frozen=True)
class ForwardObservation:
    positions: tuple[int, ...]
    signature: object


class ForwardClick:
    """One click invocation, followed only by body observation on timeout."""

    timeout_ms = 3_000
    poll_ms = 100

    def __init__(self) -> None:
        self.error: Exception | None = None
        self.before: ForwardObservation | None = None
        self.url = ""
        self.timed_out_at = 0.0
        self.debug: dict[str, Any] = {}

    async def click(
        self, page: Page, button: Locator, before: ForwardObservation | None,
        *, position: dict[str, float] | None = None,
        timeout_error: Exception | None = None,
    ) -> None:
        if self.error is not None:
            raise self.error  # An ambiguous action must never be replayed.
        self.before, self.url = before, page.url
        started = asyncio.get_running_loop().time()
        self.debug = {"outcome": "click_started", "before": self._debug_positions(before)}
        kwargs: dict[str, Any] = {"timeout": self.timeout_ms, "no_wait_after": True}
        if position is not None:
            kwargs["position"] = position
        try:
            await button.click(**kwargs)
        except PlaywrightTimeoutError as exc:
            self.error = timeout_error if timeout_error is not None else exc
            self.timed_out_at = asyncio.get_running_loop().time()
            self.debug.update(outcome="click_timeout", click_ms=round(
                (self.timed_out_at - started) * 1000))
            # Diagnostic failure cannot replace the original click exception.
            try:
                self.debug["control"] = await asyncio.wait_for(button.evaluate(
                    """(n, point) => {
                      const r=n.getBoundingClientRect(), s=getComputedStyle(n);
                      const x=r.x+(point ? point.x : r.width/2);
                      const y=r.y+(point ? point.y : r.height/2);
                      const top=document.elementFromPoint(x,y);
                      return {connected:n.isConnected, disabled:!!n.disabled,
                        ariaDisabled:n.getAttribute('aria-disabled')==='true',
                        visible:s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0,
                        rect:[r.x,r.y,r.width,r.height],
                        receivesPointer:!!top&&(top===n||n.contains(top)),
                        coveringTag:top?.tagName||null};
                    }""", position), timeout=0.25)
            except Exception:  # noqa: BLE001 - diagnostics only
                self.debug["control"] = {"observation_failed": True}
            if before is None or not self._valid_positions(before.positions):
                if self.error is exc:
                    raise
                raise self.error from exc
        else:
            self.debug.update(outcome="click_returned", click_ms=round(
                (asyncio.get_running_loop().time() - started) * 1000))

    @staticmethod
    def _debug_positions(observation: ForwardObservation | None) -> list[int]:
        return [i for i in observation.positions if type(i) is int][:2] if observation else []

    @staticmethod
    def _valid_positions(positions: tuple[int, ...]) -> bool:
        return (1 <= len(positions) <= 2
                and all(type(i) is int and i >= 0 for i in positions)
                and len(set(positions)) == len(positions)
                and sorted(positions) == list(range(min(positions), max(positions) + 1)))

    async def recover(
        self, page: Page, observe: Callable[[], Awaitable[ForwardObservation | None]],
        *, timeout_ms: int, stable_checks: int,
    ) -> None:
        error, before = self.error, self.before
        assert error is not None and before is not None
        deadline = self.timed_out_at + timeout_ms / 1000
        previous: ForwardObservation | None = None
        stable, samples = 0, 0
        try:
            async with asyncio.timeout_at(deadline):
                while True:
                    if page.url != self.url:
                        raise UnknownPageStateError("Viewer route changed after forward click timeout")
                    current = await observe()
                    if page.url != self.url:
                        raise UnknownPageStateError("Viewer route changed during forward observation")
                    samples += 1
                    self.debug["samples"] = samples
                    stable = stable + 1 if current is not None and current == previous else 0
                    previous = current
                    if current is not None:
                        self.debug["after"] = self._debug_positions(current)
                        self.debug["signature_hash"] = hashlib.sha256(
                            repr(current.signature).encode()).hexdigest()[:16]
                        if stable >= max(2, stable_checks):
                            positions = current.positions
                            if not self._valid_positions(positions):
                                raise UnknownPageStateError("Forward observation has unknown body positions")
                            if min(positions) < min(before.positions):
                                raise UnknownPageStateError("Forward click reversed body pages")
                            if positions != before.positions and not set(positions) & set(before.positions):
                                if min(positions) != max(before.positions) + 1:
                                    raise UnknownPageStateError("Forward click skipped or reversed body pages")
                                self.debug["outcome"] = "recovered_body"
                                self.error = None
                                return
                    await page.wait_for_timeout(self.poll_ms)
        except TimeoutError as exc:
            self.debug["outcome"] = "recovery_timeout"
            raise error from exc
        except asyncio.CancelledError:
            self.debug["outcome"] = "cancelled"
            raise
        except Exception:
            self.debug["outcome"] = "recovery_failed"
            raise
        finally:
            self.debug["recovery_ms"] = round(
                (asyncio.get_running_loop().time() - self.timed_out_at) * 1000)
