"""Bounded metadata-only identity research, independent of normal Discovery."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

from screenshot_crawler.maintenance.hanayume_repair import (
    IdentityObservation,
    RepairAnalysis,
    validate_pair,
)
from screenshot_crawler.site_adapters.hanayume.discovery import parse_hanayume_episode_api_identity

METADATA_DOCUMENT = "https://hanayume.com/robots.txt"

# This document is plain text: no reader navigation, application hydration,
# image downloads, access acquisition, or read-completed side effects.
FETCH_IDENTITY = """async (id) => {
  const url = `https://hanayume.com/api/episodes/${id}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(url, {method:'GET', credentials:'include',
      cache:'no-store', redirect:'error', signal:controller.signal});
    let payload = null;
    try {
      const reader = response.body.getReader(), chunks = [];
      let size = 0;
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 2000000) { await reader.cancel(); throw new Error('metadata too large'); }
        chunks.push(value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      const data = JSON.parse(new TextDecoder().decode(bytes)), e = data?.episode;
      payload = {episode: {id:e?.id, indexId:e?.indexId,
        series:{id:e?.series?.id}, access:{episodeId:e?.access?.episodeId},
        summary:{id:e?.summary?.id, indexId:e?.summary?.indexId}}};
    } catch (_) {}
    return {status:response.status, url:response.url,
      redirected:response.redirected, payload};
  } finally { clearTimeout(timer); }
}"""


@dataclass(frozen=True)
class ProbeLimits:
    max_old_ids: int = 100
    max_requests: int = 200
    seconds: float = 180
    interval: float = 2
    offset: int = 0

    def validate(self) -> None:
        if not (1 <= self.max_old_ids <= 500 and 1 <= self.max_requests <= 1000
                and 1 <= self.seconds <= 600 and 0.5 <= self.interval <= 30
                and self.offset >= 0):
            raise ValueError("解析上限が範囲外です（件数1–500、GET1–1000、秒1–600、間隔0.5–30）")


@dataclass(frozen=True)
class ProbeResult:
    observations: tuple[IdentityObservation, ...]
    requests: int
    next_offset: int
    total_old: int
    stop_reason: str


class _StopProbe(Exception):
    pass


async def probe_identities(
    page, analysis: RepairAnalysis, limits: ProbeLimits, *,
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[str], None] = lambda message: None,
    clock: Callable[[], float] = monotonic,
    sleep=asyncio.sleep,
) -> ProbeResult:
    """Use an owned same-origin Page. Caller owns CDP and closes this Page.

    No retry; failure to read one endpoint cannot authorize equivalence.
    Budget exhaustion before the new endpoint leaves the old offset resumable.
    """
    limits.validate()
    deadline = clock() + limits.seconds
    requests, last_request, completed = 0, None, 0
    observations: list[IdentityObservation] = []
    old = analysis.old
    current = {e.source.external_id: e for e in analysis.current}
    permitted = {METADATA_DOCUMENT}
    cache = {}

    async def guard(route):
        request = route.request
        if request.method == "GET" and request.url in permitted:
            await route.continue_()
        else:
            await route.abort()

    def check() -> None:
        if cancelled():
            raise _StopProbe("停止しました")
        if clock() >= deadline:
            raise _StopProbe("総時間上限")

    async def fetch(episode_id: str):
        nonlocal requests, last_request
        check()
        if episode_id in cache:
            return cache[episode_id]
        if requests >= limits.max_requests:
            raise _StopProbe("API GET件数上限")
        if last_request is not None:
            # Short waits keep cooperative cancellation responsive.
            while clock() - last_request < limits.interval:
                check()
                await sleep(min(0.1, limits.interval - (clock() - last_request)))
        check()
        permitted.add(f"https://hanayume.com/api/episodes/{episode_id}")
        requests += 1
        last_request = clock()
        progress(f"API GET {requests}/{limits.max_requests}・旧 {limits.offset + completed}/{len(old)}")
        try:
            result = await asyncio.wait_for(page.evaluate(FETCH_IDENTITY, episode_id),
                                            timeout=min(6, max(0.01, deadline - clock())))
        except Exception as exc:
            raise _StopProbe(f"API通信失敗（再試行なし）: {type(exc).__name__}") from exc
        if not isinstance(result, dict):
            raise _StopProbe("API結果が不正")
        if result.get("status") in (401, 403, 429) or (
            isinstance(result.get("status"), int) and result["status"] >= 500
        ):
            raise _StopProbe(f"HTTP {result['status']}で停止")
        cache[episode_id] = result
        return result

    def parse(result, episode_id, work_id):
        if (result.get("status") != 200 or result.get("redirected") is not False
                or result.get("url") != f"https://hanayume.com/api/episodes/{episode_id}"):
            return None
        return parse_hanayume_episode_api_identity(result.get("payload"), expected_work_id=work_id)

    stop_reason = "指定範囲の解析完了"
    try:
        check()
        await page.route("**/*", guard)
        response = await asyncio.wait_for(
            page.goto(METADATA_DOCUMENT, wait_until="domcontentloaded", timeout=10000),
            timeout=min(11, max(0.01, deadline - clock())),
        )
        if response is None or response.status != 200 or page.url != METADATA_DOCUMENT:
            raise _StopProbe("metadata専用documentを検証できませんでした")
        for entry in old[limits.offset:limits.offset + limits.max_old_ids]:
            check()
            observed_at = datetime.now(UTC).isoformat()
            sid = entry.source.id
            # validate_pair below also validates the old identity/URL/key.
            possible = []
            for candidate in analysis.current:
                try:
                    validate_pair(analysis, sid, candidate.source.id)
                    possible.append(candidate)
                except ValueError:
                    continue
            if not possible:
                observations.append(IdentityObservation(sid, None,
                    "同work/keyの有効な現行候補なし（API未取得）", observed_at=observed_at))
                completed += 1
                continue
            work_id, old_id = entry.source.external_id.split(":")
            first = parse(await fetch(old_id), old_id, work_id)
            new = current.get(f"{work_id}:{first[0]}") if first else None
            if new is None or new not in possible:
                observations.append(IdentityObservation(sid, None,
                    "旧APIの厳密なidentity対応が現行Catalog内に見つかりません", observed_at=observed_at))
                completed += 1
                continue
            second = parse(await fetch(first[0]), first[0], work_id)
            if second != first:
                observations.append(IdentityObservation(sid, None,
                    "旧・新APIのidentity/indexが一致しません", observed_at=observed_at))
            else:
                observations.append(IdentityObservation(sid, new.source.id,
                    f"旧・新exact APIのepisode/summary/access/series/index一致 (index={first[1]})",
                    first[1], observed_at))
            completed += 1
    except _StopProbe as exc:
        stop_reason = str(exc)
    except (TimeoutError, ValueError) as exc:
        stop_reason = f"解析停止: {type(exc).__name__}"
    return ProbeResult(tuple(observations), requests, limits.offset + completed, len(old), stop_reason)
