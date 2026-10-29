"""Bounded, non-consuming predecessor reading for a stranded Work Ticket."""

from __future__ import annotations

import asyncio
import math
import re
import time
from itertools import pairwise

from playwright.async_api import Page

from screenshot_crawler.core.errors import PageChangeTimeoutError, UnknownPageStateError
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.zeblack.discovery_protobuf import (
    ConsumptionStatus,
    ZeblackChapterV3,
    map_zeblack_access_mode,
)
from screenshot_crawler.site_adapters.zeblack.live_access import (
    ZeblackChapterListSnapshot,
    ZeblackLiveAccessError,
    observe_zeblack_chapter_list,
)

RECOVERY_TIMEOUT_MS = 180_000
MAX_REREAD_PAGES = 100
MAX_REREAD_STEPS = 120
_STOCK = re.compile(r"^×\s*([0-9]+)\s*チケットでさっそく読もう！$")


async def observe_ticket_stock(page: Page, title_id: str, *, timeout_ms: int) -> int | None:
    """Accept only the observed title-local stock banner, never a chapter icon."""
    url = f"https://zebrack-comic.shueisha.co.jp/title/{title_id}"
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if str(page.url) != url:
            raise ZeblackLiveAccessError("Zeblack stock observation changed title identity")
        banners = await page.locator('img[alt="チケット"]').evaluate_all("""images => {
          const visible = e => {
            if (!e.getClientRects().length) return false;
            for (let n=e; n; n=n.parentElement) {
              const s=getComputedStyle(n);
              if (s.display==='none' || s.visibility==='hidden' ||
                  s.visibility==='collapse' || s.opacity==='0') return false;
            }
            return true;
          };
          return images.filter(visible).map(image => {
            let node=image.parentElement;
            for (let i=0; node && i<4; i++,node=node.parentElement) {
              const text=(node.innerText||'').replace(/\\s+/g,' ').trim();
              if (/^×\\s*[0-9]+\\s*チケットでさっそく読もう！$/.test(text)) return text;
            }
            return '';
          });
        }""")
        if len(banners) > 1:
            raise ZeblackLiveAccessError("Zeblack stock banner is ambiguous")
        if banners:
            match = _STOCK.fullmatch(banners[0])
            return int(match[1]) if match else None
        await page.wait_for_timeout(100)
    return None


async def ordered_chapters(
    page: Page, snapshot: ZeblackChapterListSnapshot, *, timeout_ms: int,
) -> tuple[ZeblackChapterV3, ...]:
    """Validate complete, stable top-to-bottom rows against this exact snapshot."""
    from screenshot_crawler.site_adapters.zeblack.live_access import (
        canonical_zeblack_chapter_list_url,
    )

    deadline = time.monotonic() + timeout_ms / 1000
    previous: tuple[str, ...] | None = None
    while time.monotonic() < deadline:
        if str(page.url) != canonical_zeblack_chapter_list_url(snapshot.title_id):
            raise ZeblackLiveAccessError("Zeblack predecessor list identity changed")
        rows = await page.locator('[id^="chapter"]').evaluate_all("""els => els.map(e => ({
          id:e.id, top:e.getBoundingClientRect().top, height:e.getBoundingClientRect().height,
          visible:getComputedStyle(e).display!=='none' &&
            getComputedStyle(e).visibility==='visible'
        }))""")
        ids = tuple(str(row["id"])[7:] for row in rows)
        if any(not re.fullmatch(r"chapter[0-9]+", str(row["id"])) for row in rows):
            raise ZeblackLiveAccessError("Zeblack predecessor list has invalid chapter IDs")
        if len(ids) != len(set(ids)):
            raise ZeblackLiveAccessError("Zeblack predecessor list has duplicate chapters")
        if ids and set(ids) == set(snapshot.by_id):
            if any(not row["visible"] or row["height"] <= 0 for row in rows) or any(
                right["top"] <= left["top"] for left, right in pairwise(rows)
            ):
                raise ZeblackLiveAccessError("Zeblack predecessor display order is ambiguous")
            if ids == previous:
                if snapshot.document is not None and not await snapshot.document.evaluate(
                    "node => node.isConnected && node === document.documentElement"
                ):
                    raise ZeblackLiveAccessError("Zeblack predecessor document changed")
                return tuple(snapshot.by_id[cid] for cid in ids)
            previous = ids
        else:
            previous = None
        await page.wait_for_timeout(100)
    raise ZeblackLiveAccessError("Zeblack predecessor DOM/protobuf list did not stabilize")


def predecessor_for_candidates(
    chapters: tuple[ZeblackChapterV3, ...], candidate_ids: frozenset[str],
) -> ZeblackChapterV3 | None:
    for index, chapter in enumerate(chapters):
        if chapter.chapter_id not in candidate_ids:
            continue
        if map_zeblack_access_mode(chapter.status_value) != "quota":
            continue
        if chapter.status_value == ConsumptionStatus.RENTAL and (
            chapter.remaining_rental_time or 0
        ) > 0:
            continue
        return chapters[index - 1] if index else None
    return None


def predecessor_skip_reason(chapter: ZeblackChapterV3, *, safe_seconds: int) -> str | None:
    status = chapter.status_value
    if status == ConsumptionStatus.FREE:
        return None
    if status == ConsumptionStatus.RENTAL and (chapter.remaining_rental_time or 0) > safe_seconds:
        return None
    if map_zeblack_access_mode(status) == "paid":
        return "work_ticket_predecessor_paid: 直前話がpaidのため再読不可"
    return (
        "work_ticket_predecessor_requires_access: "
        "直前話が期限切れ・権利未確認・期限切れ間近のため再読不可（アプリ等で手動対応が必要）"
    )


async def reread_predecessor(
    page: Page, chapter: ZeblackChapterV3, *, page_turn_delay_ms: int,
) -> None:
    """Read from page_0 through the verified terminal card, then close natively."""
    from screenshot_crawler.site_adapters.zeblack.adapter import (
        ZeblackAdapter,
        parse_zeblack_viewer_url,
    )
    from screenshot_crawler.site_adapters.zeblack.live_access import (
        canonical_zeblack_chapter_list_url,
    )

    url = (
        f"https://zebrack-comic.shueisha.co.jp/title/{chapter.title_id}"
        f"/chapter/{chapter.chapter_id}/viewer"
    )
    await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    reader = ZeblackAdapter()
    await reader.configure_run(page, "direct")
    # Do not install capture listeners or call any capture/output hook.
    await reader.initialize(page)

    async def indices() -> tuple[int, ...]:
        identity = parse_zeblack_viewer_url(str(page.url))
        if identity is None or identity.key != (chapter.title_id, chapter.chapter_id):
            raise UnknownPageStateError("Zeblack prerequisite reading escaped its chapter")
        return tuple(int(row["page_index"]) for row in await reader._active_page_rows(page))

    # ArrowRight was live-verified to reverse ArrowLeft without changing chapter.
    for _ in range(MAX_REREAD_STEPS):
        current = await indices()
        if not current:
            raise UnknownPageStateError("Zeblack prerequisite first page is unavailable")
        if min(current) == 0:
            break
        unsafe = await page.evaluate("""() => {
          const e=document.activeElement;
          return !!e && (['INPUT','TEXTAREA','SELECT'].includes(e.tagName) || e.isContentEditable);
        }""")
        if unsafe:
            raise UnknownPageStateError("Zeblack prerequisite rewind has unsafe focus")
        previous = await reader.get_content_identity(page)
        await page.wait_for_timeout(page_turn_delay_ms)
        await page.keyboard.press("ArrowRight")
        await reader.wait_for_change(page, previous)
        after = await indices()
        if not after or max(after) >= max(current):
            raise PageChangeTimeoutError("Zeblack prerequisite rewind did not move backward")
    else:
        raise PageChangeTimeoutError("Zeblack prerequisite rewind exceeded its step limit")

    seen: set[int] = set()
    next_index = 0
    for _ in range(MAX_REREAD_STEPS):
        current = await indices()
        state = await reader.detect_state(page)
        if state in {PageState.END, PageState.NEXT_CONTENT}:
            if not seen:
                raise UnknownPageStateError("Zeblack prerequisite ended without content")
            break
        if state == PageState.CONTENT:
            if (
                not current or set(current) & seen or min(current) != next_index
                or tuple(sorted(current)) != tuple(range(min(current), max(current) + 1))
            ):
                raise UnknownPageStateError("Zeblack prerequisite repeated or skipped content")
            seen.update(current)
            if len(seen) > MAX_REREAD_PAGES:
                raise PageChangeTimeoutError("Zeblack prerequisite exceeded max_pages")
            next_index = max(current) + 1
        elif state != PageState.AD:
            raise UnknownPageStateError("Zeblack prerequisite viewer state is unknown")
        previous = await reader.get_content_identity(page)
        if state == PageState.CONTENT:
            await page.wait_for_timeout(page_turn_delay_ms)
        await reader.go_next(page)
        await reader.wait_for_change(page, previous)
    else:
        raise PageChangeTimeoutError("Zeblack prerequisite reading exceeded its step limit")

    # Supported native close component observed 2026-10-29. Never choose a
    # generic first button, next-story control or arbitrary link as fallback.
    close = page.locator("button.sc-bEHKTb")
    if await close.count() != 1 or not await close.is_visible() or not await close.is_enabled():
        raise UnknownPageStateError("Zeblack prerequisite close control is unavailable")
    if not await close.evaluate(
        "e => e.children.length === 0 && !e.textContent.trim() && !e.getAttribute('aria-label')"
    ):
        raise UnknownPageStateError("Zeblack prerequisite close control identity changed")
    # Native close can reuse a cached list without any API request. The final
    # observer accepts only requests issued after it attaches, so an outstanding
    # return-navigation response cannot contaminate its explicit fresh load.
    await close.click(timeout=10_000)
    await page.wait_for_function(
        "url => location.href === url",
        arg=canonical_zeblack_chapter_list_url(chapter.title_id), timeout=10_000,
    )


async def recover_work_ticket(
    page: Page, snapshot: ZeblackChapterListSnapshot, candidate_ids: frozenset[str], *,
    timeout_ms: int, capture_document: bool, page_turn_delay_ms: int,
    blocked_external_ids: frozenset[str] = frozenset(),
) -> tuple[ZeblackChapterListSnapshot | None, str]:
    """Attempt one recovery, with no ticket/point/coin acquisition for rereading."""
    async with asyncio.timeout(RECOVERY_TIMEOUT_MS / 1000):
        started = time.monotonic()
        stock = await observe_ticket_stock(page, snapshot.title_id, timeout_ms=timeout_ms)
        if stock is None or stock <= 0:
            return None, "work_ticket_stock_unconfirmed_or_empty"
        fresh = await observe_zeblack_chapter_list(
            page, title_id=snapshot.title_id, timeout_ms=timeout_ms,
            capture_document=capture_document,
        )
        if candidate_ids & set(fresh.ticket_available_ids):
            return fresh, ""
        chapters = await ordered_chapters(page, fresh, timeout_ms=timeout_ms)
        predecessor = predecessor_for_candidates(chapters, candidate_ids)
        if predecessor is None:
            return None, "work_ticket_predecessor_missing"
        if predecessor.chapter_id in blocked_external_ids:
            return None, "work_ticket_predecessor_excluded: 直前話が明示的に除外されているため再読不可"
        # Require the rental to outlive this entire bounded operation, including
        # navigation. A positive but nearly expired rental is not safe to open.
        safe_seconds = math.ceil(RECOVERY_TIMEOUT_MS / 1000) + 5
        reason = predecessor_skip_reason(predecessor, safe_seconds=safe_seconds)
        if reason is not None:
            return None, reason
        print(f"Zeblack Work Ticket: 直前話を再読 chapter={predecessor.chapter_id} "
              f"{predecessor.main_name}", flush=True)
        await reread_predecessor(page, predecessor, page_turn_delay_ms=page_turn_delay_ms)
        final = await observe_zeblack_chapter_list(
            page, title_id=snapshot.title_id, timeout_ms=timeout_ms,
            capture_document=capture_document,
        )
        print(f"Zeblack Work Ticket: 再読後の利用可否を確認 ({time.monotonic()-started:.1f}s)",
              flush=True)
        return final, "work_ticket_unavailable_after_reread"
