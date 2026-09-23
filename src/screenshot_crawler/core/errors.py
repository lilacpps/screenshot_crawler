class CrawlerError(RuntimeError):
    """Base crawler exception."""


class AccessStopError(CrawlerError):
    """Fatal access rejection or challenge observed by the shared guard."""

    def __init__(
        self,
        *,
        reason: str,
        site: str,
        url: str,
        host: str | None = None,
        status: int | None = None,
        retry_after: str | None = None,
        classification: str | None = None,
        provider: str | None = None,
    ) -> None:
        self.reason = reason
        self.site = site
        self.url = url
        self.host = host
        self.status = status
        self.retry_after = retry_after
        self.classification = classification
        self.provider = provider
        details = [f"access stop: {reason}", f"site={site}", f"url={url}"]
        if status is not None:
            details.append(f"status={status}")
        if retry_after is not None:
            details.append(f"retry_after={retry_after}")
        if classification is not None:
            details.append(f"classification={classification}")
        if provider is not None:
            details.append(f"provider={provider}")
        super().__init__(", ".join(details))


class UnsupportedAccessStrategyError(CrawlerError):
    """Raised when an adapter cannot execute the requested access strategy."""


class AccessResourceUnavailableError(CrawlerError):
    """Expected skip when a requested resource is clearly unavailable."""

    def __init__(self, reason: str, *, stop_resource_pass: bool = False) -> None:
        self.reason = reason
        self.stop_resource_pass = stop_resource_pass
        super().__init__(reason)


class UnknownPageStateError(CrawlerError):
    """Raised when an adapter cannot safely classify the current screen."""


class PageChangeTimeoutError(CrawlerError):
    """Raised when a requested page change cannot be confirmed."""


class CaptureUnavailableError(CrawlerError):
    """Raised when an adapter's direct capture cannot safely produce a page."""


class MaxPagesExceededError(CrawlerError):
    """Raised by the infinite-loop guard."""


class RunAlreadyExistsError(CrawlerError):
    """Raised when a new crawl would overwrite an existing run."""


class AuthenticationStateNotFoundError(CrawlerError):
    """Raised when a site requires auth state that has not been saved."""
