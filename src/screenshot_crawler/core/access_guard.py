"""Shared fail-safe access observation for supported site adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

from screenshot_crawler.core.errors import AccessStopError

if TYPE_CHECKING:
    from playwright.async_api import Page

AccessStopReason = Literal[
    "http_403",
    "http_429",
    "challenge_detected",
    "captcha_detected",
]
AccessEventType = Literal["request", "challenge", "captcha"]
AccessEventSink = Callable[["AccessEvent"], None]
AccessSignalDetector = Callable[["Page"], Awaitable[str | None]]
RelevantHostMatcher = Callable[[str], bool]


def _never_relevant(_url: str) -> bool:
    return False


@dataclass(frozen=True, slots=True)
class AccessProfile:
    """Site-supplied access classification without site branches in Core."""

    relevant_host: RelevantHostMatcher = _never_relevant
    challenge_detector: AccessSignalDetector | None = None
    captcha_detector: AccessSignalDetector | None = None


@dataclass(frozen=True, slots=True)
class AccessEvent:
    """A body-free access observation suitable for incremental metrics."""

    event_type: AccessEventType
    timestamp: datetime
    url: str
    host: str | None = None
    status: int | None = None
    relevant_host: bool = False
    retry_after: str | None = None
    response_bytes: int | None = None
    classification: str | None = None
    provider: str | None = None
    method: str | None = None
    resource_type: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "type": self.event_type,
            "timestamp": self.timestamp.astimezone(UTC).isoformat(),
            "url": self.url,
            "host": self.host,
            "status": self.status,
            "relevant_host": self.relevant_host,
            "retry_after": self.retry_after,
            "response_bytes": self.response_bytes,
            "classification": self.classification,
            "provider": self.provider,
            "method": self.method,
            "resource_type": self.resource_type,
        }


class AccessGuard:
    """Observe one Page and fail closed on configured access rejection."""

    _CAPTCHA_SELECTORS: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "recaptcha",
            (
                ".g-recaptcha",
                '[class*="recaptcha" i]',
                'iframe[src*="recaptcha" i]',
            ),
        ),
        (
            "hcaptcha",
            (
                ".h-captcha",
                '[class*="hcaptcha" i]',
                'iframe[src*="hcaptcha" i]',
            ),
        ),
        (
            "turnstile",
            (
                ".cf-turnstile",
                '[class*="turnstile" i]',
                'iframe[src*="challenges.cloudflare.com" i]',
            ),
        ),
    )

    def __init__(
        self,
        *,
        site: str,
        relevant_host: RelevantHostMatcher,
        stop_on_http_403: bool = True,
        stop_on_http_429: bool = True,
        stop_on_challenge: bool = True,
        stop_on_captcha: bool = True,
        challenge_detector: AccessSignalDetector | None = None,
        captcha_detector: AccessSignalDetector | None = None,
        event_sink: AccessEventSink | None = None,
        monitor_interval_ms: int = 250,
    ) -> None:
        self.site = site
        self._relevant_host = relevant_host
        self.stop_on_http_403 = stop_on_http_403
        self.stop_on_http_429 = stop_on_http_429
        self.stop_on_challenge = stop_on_challenge
        self.stop_on_captcha = stop_on_captcha
        self.challenge_detector = challenge_detector
        self.captcha_detector = captcha_detector
        self._event_sink = event_sink
        self._monitor_interval_ms = monitor_interval_ms
        self._stop_event = asyncio.Event()
        self._stop_error: AccessStopError | None = None
        self._page: Page | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._dom_signals_seen: set[tuple[str, str]] = set()

    @classmethod
    def from_profile(
        cls,
        *,
        site: str,
        profile: AccessProfile,
        stop_on_http_403: bool,
        stop_on_http_429: bool,
        stop_on_challenge: bool,
        stop_on_captcha: bool,
        event_sink: AccessEventSink | None = None,
    ) -> AccessGuard:
        return cls(
            site=site,
            relevant_host=profile.relevant_host,
            stop_on_http_403=stop_on_http_403,
            stop_on_http_429=stop_on_http_429,
            stop_on_challenge=stop_on_challenge,
            stop_on_captcha=stop_on_captcha,
            challenge_detector=profile.challenge_detector,
            captcha_detector=profile.captcha_detector,
            event_sink=event_sink,
        )

    def start(self, page: Page) -> None:
        """Attach response observation and start candidate-scoped DOM polling."""

        self._page = page
        on = getattr(page, "on", None)
        if not callable(on):
            return
        on("response", self._handle_response)
        self._monitor_task = asyncio.create_task(self._monitor_page(page))

    async def close(self) -> None:
        """Detach listeners and stop the candidate-scoped monitor."""

        if self._page is not None and callable(getattr(self._page, "remove_listener", None)):
            try:
                self._page.remove_listener("response", self._handle_response)
            except BaseException:  # noqa: BLE001, S110
                pass
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            await asyncio.gather(self._monitor_task, return_exceptions=True)
        self._monitor_task = None
        self._page = None

    async def wait_for_stop(self) -> AccessStopError | None:
        """Wait until a fatal event is observed; used to interrupt adapter waits."""

        await self._stop_event.wait()
        return self._stop_error

    def raise_if_stopped(self) -> None:
        if self._stop_error is not None:
            raise self._stop_error

    async def check_page(self, page: Page) -> None:
        """Check site hooks and generic visible CAPTCHA UI without reading bodies."""

        self.raise_if_stopped()
        if self.challenge_detector is not None:
            signal = await self.challenge_detector(page)
            if signal:
                self._record_dom_signal(
                    page,
                    "challenge_detected",
                    classification=signal,
                )
                if self.stop_on_challenge:
                    self._stop(
                        reason="challenge_detected",
                        url=page.url,
                        classification=signal,
                    )
        self.raise_if_stopped()

        if self.captcha_detector is not None:
            signal = await self.captcha_detector(page)
            if signal:
                self._record_dom_signal(
                    page,
                    "captcha_detected",
                    classification=signal,
                )
                if self.stop_on_captcha:
                    self._stop(
                        reason="captcha_detected",
                        url=page.url,
                        classification=signal,
                    )
        self.raise_if_stopped()

        provider = await self._visible_captcha_provider(page)
        if provider is not None:
            self._record_dom_signal(
                page,
                "captcha_detected",
                classification="visible_provider_ui",
                provider=provider,
            )
            if self.stop_on_captcha:
                self._stop(
                    reason="captcha_detected",
                    url=page.url,
                    classification="visible_provider_ui",
                    provider=provider,
                )
        self.raise_if_stopped()

    async def _monitor_page(self, page: Page) -> None:
        while True:
            await asyncio.sleep(self._monitor_interval_ms / 1000)
            try:
                await self.check_page(page)
            except AccessStopError:
                return
            except BaseException:  # noqa: BLE001 - page may close during cleanup
                return

    async def _visible_captcha_provider(self, page: Page) -> str | None:
        for provider, selectors in self._CAPTCHA_SELECTORS:
            for selector in selectors:
                try:
                    locator = page.locator(selector)
                    count = await locator.count()
                    for index in range(count):
                        if await locator.nth(index).is_visible():
                            return provider
                except BaseException:  # noqa: BLE001, S112
                    continue
        return None

    def _handle_response(self, response: object) -> None:
        url = str(getattr(response, "url", ""))
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower() or None
        relevant = False
        try:
            relevant = bool(self._relevant_host(url))
        except BaseException:  # noqa: BLE001 - fail closed for classification only
            relevant = False
        status = _int_or_none(getattr(response, "status", None))
        headers = _response_headers(response)
        retry_after = _header_value(headers, "retry-after")
        response_bytes = _non_negative_int(_header_value(headers, "content-length"))
        request = getattr(response, "request", None)
        method = str(getattr(request, "method", "") or "") or None
        resource_type = str(getattr(request, "resource_type", "") or "") or None

        self._emit(
            AccessEvent(
                event_type="request",
                timestamp=datetime.now(UTC),
                url=url,
                host=host,
                status=status,
                relevant_host=relevant,
                retry_after=retry_after,
                response_bytes=response_bytes,
                method=method,
                resource_type=resource_type,
            )
        )

        challenge_marker = _header_value(headers, "cf-mitigated").lower() == "challenge"
        if relevant and challenge_marker:
            self._emit(
                AccessEvent(
                    event_type="challenge",
                    timestamp=datetime.now(UTC),
                    url=url,
                    host=host,
                    status=status,
                    relevant_host=True,
                    retry_after=retry_after,
                    response_bytes=response_bytes,
                    classification="cf-mitigated: challenge",
                    method=method,
                    resource_type=resource_type,
                )
            )
            if self.stop_on_challenge:
                self._stop(
                    reason="challenge_detected",
                    url=url,
                    host=host,
                    status=status,
                    retry_after=retry_after,
                    classification="cf-mitigated: challenge",
                )
                return

        if relevant and status == 403 and self.stop_on_http_403:
            self._stop(
                reason="http_403",
                url=url,
                host=host,
                status=status,
                retry_after=retry_after,
            )
        elif relevant and status == 429 and self.stop_on_http_429:
            self._stop(
                reason="http_429",
                url=url,
                host=host,
                status=status,
                retry_after=retry_after,
            )

    def _record_dom_signal(
        self,
        page: Page,
        reason: AccessStopReason,
        *,
        classification: str,
        provider: str | None = None,
    ) -> None:
        key = (reason, provider or classification)
        if key in self._dom_signals_seen:
            return
        self._dom_signals_seen.add(key)
        url = page.url
        parsed = urlparse(url)
        self._emit(
            AccessEvent(
                event_type="challenge" if reason == "challenge_detected" else "captcha",
                timestamp=datetime.now(UTC),
                url=url,
                host=(parsed.hostname or "").lower() or None,
                relevant_host=True,
                classification=classification,
                provider=provider,
            )
        )

    def _stop(
        self,
        *,
        reason: AccessStopReason,
        url: str,
        host: str | None = None,
        status: int | None = None,
        retry_after: str | None = None,
        classification: str | None = None,
        provider: str | None = None,
    ) -> None:
        if self._stop_error is not None:
            return
        self._stop_error = AccessStopError(
            reason=reason,
            site=self.site,
            url=url,
            host=host,
            status=status,
            retry_after=retry_after,
            classification=classification,
            provider=provider,
        )
        self._stop_event.set()

    def _emit(self, event: AccessEvent) -> None:
        if self._event_sink is None:
            return
        try:
            self._event_sink(event)
        except BaseException:  # noqa: BLE001 - metrics must not change crawl behavior
            return


def _response_headers(response: object) -> dict[str, str]:
    raw = getattr(response, "headers", {})
    if callable(raw):
        return {}
    try:
        return {str(key).lower(): str(value) for key, value in dict(raw).items()}
    except (AttributeError, TypeError, ValueError):
        return {}


def _header_value(headers: dict[str, str], key: str) -> str:
    return str(headers.get(key.lower(), "") or "").strip()


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _non_negative_int(value: str) -> int | None:
    parsed = _int_or_none(value)
    return parsed if parsed is not None and parsed >= 0 else None
