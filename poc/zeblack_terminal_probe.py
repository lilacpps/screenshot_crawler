"""Read-only Zebrack Z2 terminal / END / NEXT_CONTENT probe.

Z2 deliberately remains a research probe.  It reuses the Z0 bounded
navigation and target guards, observes the end of one fixed chapter, and never
clicks a next-chapter or access control.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

try:  # Support both ``poc.*`` imports and direct script execution.
    from .zeblack_capture_probe import parse_page_index
    from .zeblack_probe import (
        _DRAW_HOOK,
        DEFAULT_URL,
        BrowserSession,
        ZebrackProbe,
        _write_json,
        extract_viewer_identity,
        is_target_viewer_url,
        normalize_navigation_text,
        resolve_cdp_endpoint,
    )
except ImportError:  # pragma: no cover - direct script execution.
    from zeblack_capture_probe import parse_page_index  # type: ignore[no-redef]
    from zeblack_probe import (  # type: ignore[no-redef]
        _DRAW_HOOK,
        DEFAULT_URL,
        BrowserSession,
        ZebrackProbe,
        _write_json,
        extract_viewer_identity,
        is_target_viewer_url,
        normalize_navigation_text,
        resolve_cdp_endpoint,
    )


MAX_TERMINAL_STEPS = 100
MAX_NO_CHANGE_RECHECKS = 2
Z2_OUTPUT_NAME = "zeblack_terminal_probe"
PAGE_COUNTER_RE = re.compile(r"^\s*(?P<numerator>\d+)\s*/\s*(?P<denominator>\d+)\s*$")

_END_TERMS = (
    "読み終わりました",
    "読み終わり",
    "この話はここまで",
    "読了",
    "作品ページへ",
)
_NEXT_CONTENT_TERMS = (
    "次の話を読む",
    "次の話",
    "次話を読む",
    "次話",
    "次のチャプター",
    "次チャプター",
    "続きはこちら",
    "next chapter",
    "next episode",
    "next content",
)
_TERMINAL_UI_TERMS = (
    "recommendation",
    "おすすめ",
    "share",
    "シェア",
    "感想",
)


# Keep the evidence vocabulary explicit even when this file is executed from
# a console with a non-UTF-8 code page.
_END_TERMS = (
    "\u8aad\u307f\u7d42\u308f\u308a\u307e\u3057\u305f",
    "\u8aad\u307f\u7d42\u308f\u308a",
    "\u3053\u306e\u8a71\u306f\u3053\u3053\u307e\u3067",
    "\u8aad\u4e86",
    "\u4f5c\u54c1\u30da\u30fc\u30b8\u3078",
)
_NEXT_CONTENT_TERMS = (
    "\u6b21\u306e\u8a71\u3092\u8aad\u3080",
    "\u6b21\u306e\u8a71",
    "\u6b21\u8a71\u3092\u8aad\u3080",
    "\u6b21\u8a71",
    "\u6b21\u306e\u30c1\u30e3\u30d7\u30bf\u30fc",
    "\u6b21\u30c1\u30e3\u30d7\u30bf\u30fc",
    "\u7d9a\u304d\u306f\u3053\u3061\u3089",
    "next chapter",
    "next episode",
    "next content",
)
_TERMINAL_UI_TERMS = (
    "recommendation",
    "\u304a\u3059\u3059\u3081",
    "share",
    "\u30b7\u30a7\u30a2",
    "\u611f\u60f3",
)


def parse_page_counter(value: Any) -> dict[str, Any] | None:
    """Parse a visible ``numerator / denominator`` counter without guessing."""

    if not isinstance(value, str):
        return None
    match = PAGE_COUNTER_RE.fullmatch(value)
    if match is None:
        return None
    return {
        "text": value.strip(),
        "numerator": int(match.group("numerator")),
        "denominator": int(match.group("denominator")),
    }


def classify_terminal_candidate(*values: Any) -> str | None:
    """Classify explicit terminal evidence; unrelated text remains unknown."""

    label = normalize_navigation_text(" ".join(str(value or "") for value in values))
    if any(term.lower() in label for term in _NEXT_CONTENT_TERMS):
        return "next_content"
    if any(term.lower() in label for term in _END_TERMS):
        return "end"
    if any(term.lower() in label for term in _TERMINAL_UI_TERMS):
        return "terminal_ui"
    return None


def classify_z2_url_change(
    before: str,
    after: str,
    expected_title_id: str,
    expected_chapter_id: str,
) -> str:
    """Classify current-chapter stability and any chapter/title escape."""

    if before == after:
        return "unchanged"
    if is_target_viewer_url(after, expected_title_id, expected_chapter_id):
        return "query_or_hash_changed"
    identity = extract_viewer_identity(after)
    if identity is not None:
        if identity["title_id"] == str(expected_title_id):
            return "next_chapter"
        return "different_title"
    return "other_escape"


def aggregate_terminal_verdict(
    states: list[dict[str, Any]],
    navigation: list[dict[str, Any]],
    *,
    stopped_reason: str | None,
) -> str:
    """Aggregate terminal evidence with no-change and missing-signal fail-closed."""

    if any(record.get("url_change_kind") in {"next_chapter", "different_title", "other_escape"} for record in navigation):
        return "auto_next_navigation_observed"
    terminal_states = [state for state in states if state.get("terminal_observed")]
    if terminal_states:
        terminal = terminal_states[-1]
        signals = set(terminal.get("terminal_signal_kinds", []))
        if "next_content" in signals and not terminal.get("content_present"):
            return "next_content_confirmed"
        if "end" in signals and not terminal.get("content_present") and "next_content" not in signals:
            return "end_confirmed"
        return "terminal_but_type_unknown"
    if stopped_reason in {"max_terminal_steps_reached", "repeated_no_change_without_terminal"}:
        return "no_terminal_observed"
    return "inconclusive"


def _counter_candidates(dom: dict[str, Any]) -> list[dict[str, Any]]:
    counters: list[dict[str, Any]] = []
    for candidate in dom.get("pageInfoCandidates", []):
        parsed = parse_page_counter(candidate.get("text"))
        if parsed is not None:
            counters.append({**parsed, "selector": candidate.get("selector")})
    return counters


def _page_images(dom: dict[str, Any]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for dom_order, image in enumerate(dom.get("visibleImages", [])):
        page_index = parse_page_index(image.get("alt"))
        if page_index is None:
            continue
        pages.append(
            {
                "page_alt": image.get("alt"),
                "page_index": page_index,
                "src": image.get("src"),
                "current_src": image.get("currentSrc"),
                "natural_dimensions": [image.get("naturalWidth"), image.get("naturalHeight")],
                "rendered": image.get("renderedRect"),
                "in_viewport": bool(image.get("inViewport")),
                "dom_order": image.get("domOrder", dom_order),
            }
        )
    return pages


def _candidate_values(candidate: dict[str, Any]) -> list[Any]:
    return [
        candidate.get("text"),
        candidate.get("ariaLabel"),
        candidate.get("title"),
        candidate.get("href"),
        candidate.get("attributes", {}).get("class"),
    ]


def _terminal_candidates(dom: dict[str, Any], page_url: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    visible_candidates = [*dom.get("buttons", []), *dom.get("viewerish", [])]
    for source, candidate in (("dom", item) for item in visible_candidates):
        kind = classify_terminal_candidate(*_candidate_values(candidate))
        if kind is None:
            continue
        key = (source, kind, normalize_navigation_text(candidate.get("text")))
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"source": source, "kind": kind, **candidate})
    visible_text = str(dom.get("visibleText") or "")
    for term, kind in [
        *[(term, "next_content") for term in _NEXT_CONTENT_TERMS],
        *[(term, "end") for term in _END_TERMS],
        *[(term, "terminal_ui") for term in _TERMINAL_UI_TERMS],
    ]:
        if term.lower() not in visible_text.lower():
            continue
        key = ("visible_text", kind, term.lower())
        if key not in seen:
            seen.add(key)
            candidates.append({"source": "visible_text", "kind": kind, "text": term})
    for link in dom.get("chapterLinks", []):
        kind = classify_terminal_candidate(*_candidate_values(link))
        if kind != "next_content":
            continue
        href = urljoin(page_url, str(link.get("href") or ""))
        identity = extract_viewer_identity(href)
        candidates.append(
            {
                "source": "chapter_link",
                "kind": kind,
                "text": link.get("text"),
                "ariaLabel": link.get("attributes", {}).get("aria-label"),
                "href": href,
                "candidate_title_id": identity.get("title_id") if identity else None,
                "candidate_chapter_id": identity.get("chapter_id") if identity else None,
                "clicked": False,
            }
        )
    return candidates


_Z2_FINGERPRINT_SCRIPT = r"""
() => {
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      style.opacity !== "0" && rect.width > 0 && rect.height > 0;
  };
  const counter = Array.from(document.querySelectorAll("[aria-label], [class], [id]"))
    .filter(visible)
    .map((element) => (element.innerText || element.getAttribute("aria-label") || "").trim())
    .filter((text) => /^\s*\d+\s*\/\s*\d+\s*$/.test(text))
    .slice(0, 10);
  const pages = Array.from(document.images)
    .filter((element) => visible(element) && /^page_[0-9]+$/.test(element.alt || ""))
    .map((element) => [element.alt, element.currentSrc || element.src, element.naturalWidth, element.naturalHeight]);
  const terminalText = (document.body?.innerText || "")
    .split(/\s+/)
    .filter(Boolean)
    .filter((text) => /次の話|次話|読み終|この話はここまで|作品ページ|recommendation|おすすめ|share|感想/i.test(text))
    .slice(0, 30);
  const viewerHints = Array.from(document.querySelectorAll("[id], [class]"))
    .filter(visible)
    .filter((element) => /viewer|reader|page|spread|terminal|end|finish/i.test(`${element.id} ${element.className}`))
    .map((element) => [element.tagName, String(element.className || "").slice(0, 200), (element.innerText || "").trim().slice(0, 300)])
    .slice(0, 20);
  return JSON.stringify({url: location.href, pages, counter, terminalText, viewerHints});
}
"""


@dataclass
class ZebrackTerminalProbe(ZebrackProbe):
    """Bounded end-of-chapter observer using the existing Z0 safety model."""

    z2_states: list[dict[str, Any]] = field(default_factory=list)
    z2_navigation: list[dict[str, Any]] = field(default_factory=list)
    z2_seen_page_indices: set[int] = field(default_factory=set)
    z2_stopped_reason: str | None = None
    z2_first_terminal_state: str | None = None
    z2_first_terminal_step: int | None = None

    async def capture_initial(self) -> None:
        await super().capture_initial()
        if self.observations:
            await self.capture_z2_state(self.observations[-1], step=0)

    async def collect_snapshot(self, directory_name: str, *, include_html: bool) -> Any:
        observation = await super().collect_snapshot(directory_name, include_html=include_html)
        if directory_name != "initial":
            step = int(directory_name.rsplit("_", 1)[-1]) if directory_name.startswith("state_") else None
            await self.capture_z2_state(observation, step=step)
        return observation

    async def current_z2_fingerprint(self) -> str | None:
        try:
            return await self.page.evaluate(_Z2_FINGERPRINT_SCRIPT)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"Z2 fingerprint observation failed: {type(exc).__name__}: {exc}")
            return None

    async def wait_for_z2_stability(self, timeout: float = 12.0) -> bool:
        deadline = time.monotonic() + timeout
        previous: str | None = None
        same_count = 0
        while time.monotonic() < deadline:
            fingerprint = await self.current_z2_fingerprint()
            if fingerprint is None:
                return False
            if fingerprint == previous:
                same_count += 1
                if same_count >= 2:
                    return True
            else:
                previous = fingerprint
                same_count = 0
            await asyncio.sleep(0.4)
        return False

    async def wait_for_z2_change(self, before: str, timeout: float = 10.0) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = await self.current_z2_fingerprint()
            if current and current != before:
                return current
            await asyncio.sleep(0.4)
        return None

    async def capture_z2_state(self, observation: Any, *, step: int | None) -> dict[str, Any]:
        dom = observation.dom
        page_images = _page_images(dom)
        page_indices = sorted({int(page["page_index"]) for page in page_images})
        in_viewport_indices = sorted({
            int(page["page_index"]) for page in page_images if page.get("in_viewport")
        })
        newly_observed = [index for index in page_indices if index not in self.z2_seen_page_indices]
        self.z2_seen_page_indices.update(page_indices)
        counters = _counter_candidates(dom)
        terminal_candidates = _terminal_candidates(dom, observation.url)
        signal_kinds = sorted({str(item["kind"]) for item in terminal_candidates})
        content_present = bool(in_viewport_indices)
        terminal_observed = not content_present and bool(signal_kinds)
        fingerprint = await self.current_z2_fingerprint()
        state = {
            "state": observation.state,
            "step": step,
            "url": observation.url,
            "fingerprint": fingerprint,
            "page_indices": page_indices,
            "in_viewport_page_indices": in_viewport_indices,
            "minimum_page_index": min(page_indices) if page_indices else None,
            "maximum_page_index": max(page_indices) if page_indices else None,
            "newly_observed_page_indices": newly_observed,
            "page_images": page_images,
            "page_counter_candidates": counters,
            "visible_text": str(dom.get("visibleText") or "")[:8_000],
            "viewer_like_dom": dom.get("viewerish", []),
            "buttons": dom.get("buttons", []),
            "links": dom.get("links", []),
            "navigation_candidates": dom.get("navigationCandidates", []),
            "chapter_links": dom.get("chapterLinks", []),
            "access_related_candidates": dom.get("accessObservations", []),
            "terminal_related_candidates": terminal_candidates,
            "terminal_signal_kinds": signal_kinds,
            "content_present": content_present,
            "terminal_observed": terminal_observed,
            "screenshot": str(Path(observation.directory) / "screenshot.png"),
        }
        self.z2_states.append(state)
        _write_json(self.output_dir / observation.state / "z2.json", state)
        if terminal_observed:
            terminal_dir = self.output_dir / "terminal"
            terminal_dir.mkdir(parents=True, exist_ok=True)
            _write_json(terminal_dir / "z2.json", state)
            screenshot = Path(observation.directory) / "screenshot.png"
            if screenshot.exists():
                (terminal_dir / "screenshot.png").write_bytes(screenshot.read_bytes())
        return state

    async def advance_z2_once(self, step: int) -> dict[str, Any]:
        before_url = self.page.url
        if not is_target_viewer_url(before_url, self.expected_title_id, self.expected_chapter_id):
            return {
                "step": step,
                "status": "stopped_target_guard_before_navigation",
                "before_url": before_url,
                "after_url": before_url,
                "url_change_kind": "other_escape",
                "changed": False,
                "stable": False,
            }
        candidate = await self.choose_navigation()
        if candidate is None:
            return {
                "step": step,
                "status": "navigation_candidate_unavailable",
                "candidate": None,
                "before_url": before_url,
                "after_url": before_url,
                "url_change_kind": "unchanged",
                "changed": False,
                "stable": False,
            }
        candidate_url = self.page.url
        candidate_url_change = classify_z2_url_change(
            before_url,
            candidate_url,
            self.expected_title_id,
            self.expected_chapter_id,
        )
        if candidate_url_change not in {"unchanged", "query_or_hash_changed"}:
            return {
                "step": step,
                "status": "stopped_target_guard_before_navigation",
                "candidate": candidate,
                "before_url": before_url,
                "after_url": candidate_url,
                "url_change_kind": candidate_url_change,
                "changed": False,
                "stable": False,
            }
        before_fingerprint = await self.current_z2_fingerprint()
        if before_fingerprint is None:
            return {
                "step": step,
                "status": "fingerprint_unavailable",
                "candidate": candidate,
                "before_url": before_url,
                "after_url": before_url,
                "url_change_kind": "unchanged",
                "changed": False,
                "stable": False,
            }
        record: dict[str, Any] = {
            "step": step,
            "candidate": candidate,
            "before_url": before_url,
            "changed": False,
            "stable": False,
        }
        try:
            if candidate.get("interaction") == "keyboard":
                locator = self.page.locator(str(candidate.get("selector") or ""))
                if await locator.count() != 1 or not await locator.is_visible():
                    locator = None
                else:
                    # The keyboard candidate is the single visible viewer root.
                    # Do not reject it because that root's aggregate text contains
                    # a separately rendered next-chapter recommendation.
                    has_content = await locator.locator("img, canvas").count() > 0
                    if not has_content:
                        locator = None
            else:
                locator = await self.revalidate_navigation_candidate(candidate)
            if locator is None:
                record.update({"status": "candidate_revalidation_failed", "after_url": before_url, "url_change_kind": "unchanged"})
                return record
            if candidate.get("interaction") == "keyboard":
                await self.page.keyboard.press(str(candidate.get("key") or "ArrowLeft"))
            else:
                await locator.click(timeout=5_000, no_wait_after=True)
        except BaseException as exc:  # noqa: BLE001
            record.update({
                "status": "failed",
                "after_url": self.page.url,
                "url_change_kind": classify_z2_url_change(
                    before_url, self.page.url, self.expected_title_id, self.expected_chapter_id
                ),
                "error": f"{type(exc).__name__}: {exc}",
            })
            return record
        after_url = self.page.url
        url_change_kind = classify_z2_url_change(
            before_url, after_url, self.expected_title_id, self.expected_chapter_id
        )
        record["after_url"] = after_url
        record["url_change_kind"] = url_change_kind
        if url_change_kind in {"next_chapter", "different_title", "other_escape"}:
            record.update({"status": "target_identity_changed", "changed": True, "stable": False})
            return record
        changed_fingerprint = await self.wait_for_z2_change(before_fingerprint)
        changed = changed_fingerprint is not None
        stable = changed and await self.wait_for_z2_stability()
        stable_url = self.page.url
        stable_url_change_kind = classify_z2_url_change(
            before_url,
            stable_url,
            self.expected_title_id,
            self.expected_chapter_id,
        )
        if stable_url_change_kind in {"next_chapter", "different_title", "other_escape"}:
            record.update({
                "status": "target_identity_changed",
                "after_url": stable_url,
                "url_change_kind": stable_url_change_kind,
                "changed": changed,
                "stable": stable,
            })
            return record
        record.update({
            "status": "changed_and_stable" if changed and stable else "changed_but_not_stable" if changed else "not_changed",
            "after_url": stable_url,
            "url_change_kind": stable_url_change_kind,
            "changed": changed,
            "stable": stable,
        })
        return record

    async def run(self, url: str, steps: int = MAX_TERMINAL_STEPS) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.install_listeners()
        await self.page.add_init_script(script=_DRAW_HOOK)
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"page.goto failed: {type(exc).__name__}: {exc}")
        await self.wait_for_z2_stability()
        if not is_target_viewer_url(self.page.url, self.expected_title_id, self.expected_chapter_id):
            self.z2_stopped_reason = "target viewer URL changed during initial navigation"
        await self.capture_initial()
        if self.z2_stopped_reason:
            await self.drain_image_tasks()
            return self.as_report(url, steps)

        no_change_count = 0
        for step in range(1, steps + 1):
            navigation = await self.advance_z2_once(step)
            self.z2_navigation.append(navigation)
            if navigation.get("url_change_kind") in {"next_chapter", "different_title", "other_escape"}:
                self.z2_stopped_reason = "automatic next-content navigation observed"
                break
            await self.collect_snapshot(f"state_{step:03d}", include_html=False)
            current_state = self.z2_states[-1]
            if current_state.get("terminal_observed"):
                if self.z2_first_terminal_state is None:
                    self.z2_first_terminal_state = current_state["state"]
                    self.z2_first_terminal_step = step
                self.z2_stopped_reason = "terminal_state_observed"
                break
            if not navigation.get("changed") or not navigation.get("stable"):
                no_change_count += 1
                if no_change_count >= MAX_NO_CHANGE_RECHECKS:
                    self.z2_stopped_reason = "repeated_no_change_without_terminal"
                    break
            else:
                no_change_count = 0
        else:
            self.z2_stopped_reason = "max_terminal_steps_reached"
        await self.drain_image_tasks()
        return self.as_report(url, steps)

    def as_report(self, target_url: str, steps: int) -> dict[str, Any]:
        final_state = self.z2_states[-1] if self.z2_states else None
        content_states = [state for state in self.z2_states if state.get("content_present")]
        report = {
            "target_url": target_url,
            "target_title_id": self.expected_title_id,
            "target_chapter_id": self.expected_chapter_id,
            "final_url": self.page.url,
            "steps_requested": steps,
            "max_terminal_steps": MAX_TERMINAL_STEPS,
            "states_observed": len(self.z2_states),
            "navigation": self.z2_navigation,
            "states": self.z2_states,
            "final_state": final_state,
            "final_content_state": content_states[-1] if content_states else None,
            "first_terminal_state": self.z2_first_terminal_state,
            "first_terminal_step": self.z2_first_terminal_step,
            "stopped_reason": self.z2_stopped_reason,
            "terminal_classification": aggregate_terminal_verdict(
                self.z2_states,
                self.z2_navigation,
                stopped_reason=self.z2_stopped_reason,
            ),
            "saved_network_images": self.saved_images,
            "errors": self.errors,
        }
        return report

    def write_report(self, report: dict[str, Any]) -> None:
        _write_json(self.output_dir / "report.json", report)
        (self.output_dir / "summary.md").write_text(self.make_summary(report), encoding="utf-8")

    @staticmethod
    def make_summary(report: dict[str, Any]) -> str:
        states = report.get("states", [])
        final_content = report.get("final_content_state") or {}
        final_state = report.get("final_state") or {}
        counters = final_state.get("page_counter_candidates", [])
        lines = [
            "# Zebrack Z2 terminal probe summary",
            "",
            "## 1. Target",
            "",
            f"- URL: `{report.get('target_url')}`",
            f"- title_id: `{report.get('target_title_id')}`; chapter_id: `{report.get('target_chapter_id')}`",
            f"- final URL: `{report.get('final_url')}`",
            f"- states observed: `{report.get('states_observed')}`",
            "",
            "## 2. Navigation method",
            "",
            "- method: bounded revalidated `ArrowLeft` / explicit page-navigation candidate",
            f"- advances: `{len(report.get('navigation', []))}`; maximum: `{report.get('max_terminal_steps')}`",
            f"- safety stop: `{report.get('stopped_reason') or 'none'}`",
            "- Next-chapter and access controls were not clicked.",
            "",
            "## 3. Observed page progression",
            "",
            *[
                f"- `{state.get('state')}`: pages `{state.get('page_indices')}`, in viewport `{state.get('in_viewport_page_indices')}`, new `{state.get('newly_observed_page_indices')}`"
                for state in states
            ],
            "",
            "## 4. page_N / page counter relation",
            "",
            f"- final content pages: `{final_content.get('page_indices', [])}`",
            f"- final counter candidates: `{counters}`",
            "- Counter is evidence only; it is not used as the sole END authority.",
            "",
            "## 5. Final content state",
            "",
            f"- state: `{final_content.get('state')}`; maximum page index: `{final_content.get('maximum_page_index')}`",
            f"- terminal transition state: `{report.get('first_terminal_state')}` at step `{report.get('first_terminal_step')}`",
            "",
            "## 6. First terminal transition",
            "",
            f"- classification: `{report.get('terminal_classification')}`",
            f"- final state content present: `{final_state.get('content_present')}`",
            "",
            "## 7. END signals",
            "",
            f"- `{[candidate for state in states for candidate in state.get('terminal_related_candidates', []) if candidate.get('kind') == 'end']}`",
            "",
            "## 8. NEXT_CONTENT signals",
            "",
            f"- `{[candidate for state in states for candidate in state.get('terminal_related_candidates', []) if candidate.get('kind') == 'next_content']}`",
            "",
            "## 9. URL / chapter identity behavior",
            "",
            f"- navigation URL changes: `{[(item.get('before_url'), item.get('after_url'), item.get('url_change_kind')) for item in report.get('navigation', [])]}`",
            "- Next chapter candidates were recorded but never clicked.",
            "",
            "## 10. Terminal classification",
            "",
            f"- `Zeblack terminal behavior: {report.get('terminal_classification')}`",
            "",
            "## 11. Safety observations",
            "",
            "- Target host/title/chapter/viewer identity was checked before and after each operation.",
            "- No access resource, purchase, ticket, point, coin, rental, advertisement, login, or next-chapter action was initiated.",
            "",
            "## 12. Remaining unknowns",
            "",
            "- No production END/NEXT_CONTENT PageState decision was implemented.",
            "- Behavior outside this title/chapter and other access states remains unknown.",
            f"- errors: `{json.dumps(report.get('errors', []), ensure_ascii=False)}`",
            "",
            "## 13. Recommendation for production Adapter",
            "",
            "- Keep this terminal evidence site-local and fail closed. Do not use page counter alone; require explicit terminal evidence plus current-chapter identity and stable content disappearance/transition.",
            "- Do not click next-chapter controls as part of terminal detection.",
            "",
        ]
        return "\n".join(lines)


async def run_terminal_probe(
    url: str = DEFAULT_URL,
    output_dir: Path = Path("output/zeblack_terminal_probe"),
    cdp_endpoint: str | None = None,
    steps: int = MAX_TERMINAL_STEPS,
) -> dict[str, Any]:
    identity = extract_viewer_identity(url)
    if identity is None:
        raise ValueError(
            "--url must be a Zebrack URL of the form "
            "https://zebrack-comic.shueisha.co.jp/title/<id>/chapter/<id>/viewer"
        )
    endpoint = resolve_cdp_endpoint(cli_endpoint=cdp_endpoint)
    session = await BrowserSession.connect(endpoint)
    page = await session.new_page()
    probe = ZebrackTerminalProbe(
        page=page,
        output_dir=output_dir,
        expected_title_id=identity["title_id"],
        expected_chapter_id=identity["chapter_id"],
        max_image_responses=0,
    )
    try:
        report = await probe.run(url, max(0, min(MAX_TERMINAL_STEPS, steps)))
        probe.write_report(report)
        return report
    finally:
        await session.close_page(page)
        await session.close()


def main() -> None:  # pragma: no cover - live CLI entry point.
    parser = argparse.ArgumentParser(description="Read-only Zebrack Z2 terminal probe")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=Path("output/zeblack_terminal_probe"))
    parser.add_argument("--cdp-endpoint", default=None)
    parser.add_argument("--steps", type=int, default=MAX_TERMINAL_STEPS)
    args = parser.parse_args()
    report = asyncio.run(run_terminal_probe(args.url, args.output_dir, args.cdp_endpoint, args.steps))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
