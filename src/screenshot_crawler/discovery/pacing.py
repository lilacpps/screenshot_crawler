"""Run-local pacing between Discovery targets, shared by CLI and GUI."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from screenshot_crawler.runtime_settings import CrawlerRuntimeSettings


class DiscoveryPacer:
    def __init__(
        self, settings: CrawlerRuntimeSettings, *, checkpoint: Callable[[], None] | None = None
    ) -> None:
        self.settings = settings
        self.checkpoint = checkpoint
        self._previous_delay_ms = 0

    async def before_target(self, site: str) -> None:
        """Wait for the previous attempt, then record this attempt's delay.

        Call after local validation and immediately before connecting. The
        caller must finish browser cleanup before starting another target.
        """
        remaining_ms = self._previous_delay_ms
        while remaining_ms > 0:
            if self.checkpoint is not None:
                self.checkpoint()
            chunk_ms = min(remaining_ms, 200) if self.checkpoint is not None else remaining_ms
            await asyncio.sleep(chunk_ms / 1000)
            remaining_ms -= chunk_ms
        if self.checkpoint is not None:
            self.checkpoint()
        self._previous_delay_ms = self.settings.for_site(site).discovery_inter_target_delay_ms
