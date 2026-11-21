"""Bind a displayed end card to the reader's same-episode native response.

Only observe requests the reader itself makes. Never fetch an episode, activate
an end-card control, or retain response HTML, tokens, or account balances.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import parse_qsl, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Request, Response

from screenshot_crawler.site_adapters.yanmaga.discovery import YanmagaEpisodeParts

MAX_TERMINAL_HTML_BYTES = 512 * 1024


def rental_binding_js() -> str:
    """Critical read-only card fields, shared by detached and displayed DOM."""

    return r"""root => {
      if (!root || root.id !== 'rental') return null;
      const text = element => (element.textContent || '').replace(/\s+/gu, ' ').trim();
      const rows = selector => [...root.querySelectorAll(selector)];
      const attr = (element, name) => element.getAttribute(name);
      // Deliberately exclude CSRF, balances, transient geometry and analytics.
      return JSON.stringify({
        titles:rows('.episode-modal-eptitle').map(text),
        works:rows('.episode-modal-title').map(text),
        controls:rows('#js-btn-valid-next-episode,a.ga-viewer-rental-signup,' +
          '#js-btn-rental,a.author-info').map(e => [e.id, text(e.querySelector(':scope > span') || e),
            attr(e,'href'),attr(e,'data-viewer-path')]),
        waits:rows('.episode-modal-wait').map(e => [text(e),
          [...e.querySelectorAll('img')].map(i => attr(i,'src'))]),
        forms:rows('form').map(e => [e.id,attr(e,'action'),attr(e,'method'),
          [...e.querySelectorAll('input[name="jdcn"],input[name="rental_type"]')]
            .map(i => [i.name,attr(i,'type'),i.value])]),
        costs:rows('dl.episode-modal-point--necessary').map(text),
        // The reader fills the share URL after inserting this response. Its
        // current-source URL is independently checked by the engagement proof.
        shareCount:rows('a.ga-viewer-rental-share').length
      });
    }"""


class YanmagaTerminalObserver:
    """One document's bounded, target-bound response evidence."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.expected: YanmagaEpisodeParts | None = None
        self.signature: str | None = None
        self.code: str | None = None
        self.state = "waiting_for_native_response"
        self._generation = 0
        self._serial = 0
        self._pending: dict[Request, tuple[int, int, str]] = {}
        self._tasks: set[asyncio.Task] = set()
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("framenavigated", self._on_navigation)
        page.on("close", self.close)

    def close(self, *_args) -> None:
        self.page.remove_listener("request", self._on_request)
        self.page.remove_listener("response", self._on_response)
        self.page.remove_listener("framenavigated", self._on_navigation)
        self.page.remove_listener("close", self.close)
        self._on_navigation(self.page.main_frame)

    def _on_navigation(self, frame) -> None:
        if frame != self.page.main_frame:
            return
        self._generation += 1
        self.state = "document_changed"
        self.signature = self.code = None
        self._serial += 1
        self._pending.clear()
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    def _on_request(self, request: Request) -> None:
        url = urlsplit(request.url)
        if (
            url.scheme != "https"
            or url.netloc != "yanmaga.jp"
            or url.path != "/viewer/rental_episode"
        ):
            return
        # The native reader also opens this path as a popup iframe document.
        # That separate surface must neither supply nor erase main-reader proof.
        if request.frame != self.page.main_frame or request.resource_type not in {"xhr", "fetch"}:
            return
        self.signature = self.code = None
        self._serial += 1
        self.state = "unsupported_native_request"
        pairs = parse_qsl(url.query, keep_blank_values=True)
        values = dict(pairs)
        if (
            self.expected is None
            or request.method != "GET"
            or url.fragment
            or request.redirected_from is not None
            or len(pairs) != 4
            or set(values) != {"jdcn", "random_identification", "viewer_type", "vm"}
            or values["random_identification"] != self.expected.episode_id
            or values["viewer_type"] != "comics"
            or values["vm"] != "2"
            or re.fullmatch(r"[A-Za-z0-9]{20}", values["jdcn"]) is None
            or len(self._pending) >= 4
            or len(self._tasks) >= 4
        ):
            return
        self._pending[request] = (self._generation, self._serial, values["jdcn"])
        self.state = "waiting_for_response_body"

    def _on_response(self, response: Response) -> None:
        binding = self._pending.pop(response.request, None)
        if binding is None:
            return
        task = asyncio.create_task(self._read_response(response, *binding))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _read_response(
        self, response: Response, generation: int, serial: int, code: str
    ) -> None:
        try:
            async with asyncio.timeout(10):
                mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
                length = response.headers.get("content-length")
                if (
                    response.status != 200
                    or mime != "text/html"
                    or response.from_service_worker
                    or (
                        length is not None
                        and (not length.isdecimal() or int(length) > MAX_TERMINAL_HTML_BYTES)
                    )
                ):
                    self.state = "unsupported_native_response"
                    return
                body = await response.body()
                if len(body) > MAX_TERMINAL_HTML_BYTES:
                    self.state = "response_too_large"
                    return
                signature = await self.page.evaluate(
                    r"""html => {
                      const doc = new DOMParser().parseFromString(html,'text/html');
                      const roots = [...doc.querySelectorAll('#rental')];
                      if (roots.length !== 1 || roots[0].parentElement !== doc.body) return null;
                      return (BINDING)(roots[0]);
                    }""".replace("BINDING", rental_binding_js()),
                    body.decode("utf-8", errors="strict"),
                )
                if (
                    generation == self._generation
                    and serial == self._serial
                    and isinstance(signature, str)
                ):
                    self.signature, self.code = signature, code
                    self.state = "response_bound"
        except (PlaywrightError, TimeoutError, UnicodeError):
            if generation == self._generation and serial == self._serial:
                self.state = "response_unreadable"
            return

    def matches(self, signature: object, viewer_url: str) -> bool:
        from screenshot_crawler.site_adapters.yanmaga.adapter import parse_yanmaga_viewer_url

        if parse_yanmaga_viewer_url(viewer_url) != self.expected:
            return False
        query = dict(parse_qsl(urlsplit(viewer_url).query))
        return (
            self.signature is not None
            and signature == self.signature
            and (not query or query.get("cid") == self.code)
        )
