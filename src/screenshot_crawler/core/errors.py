class CrawlerError(RuntimeError):
    """Base crawler exception."""


class UnsupportedAccessStrategyError(CrawlerError):
    """Raised when an adapter cannot execute the requested access strategy."""


class AccessResourceUnavailableError(CrawlerError):
    """Expected skip when a requested resource is clearly unavailable."""


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
