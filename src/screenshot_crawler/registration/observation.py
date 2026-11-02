"""One non-consuming document observation; Page/session ownership stays outside."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime

from playwright.async_api import Error as PlaywrightError


class ObservationUnavailable(ValueError):
    """No metadata proof; an already validated URL can remain a manual candidate."""


class ObservationRejected(ObservationUnavailable):
    """Unexpected navigation/identity, which must block the candidate."""


@asynccontextmanager
async def registration_document(page, url):
    """Allow one exact main-frame GET, no redirects or subresource dispatch."""
    used, violations = False, []

    async def restrict(route):
        nonlocal used
        request = route.request
        if request.is_navigation_request() and request.frame == page.main_frame:
            if (used or request.frame != page.main_frame or request.method != "GET"
                    or request.url != url or request.redirected_from is not None):
                violations.append(True)
                await route.abort()
                return
            used = True
            try:
                response = await route.fetch(max_redirects=0, timeout=20_000)
                if 300 <= response.status < 400:
                    violations.append(True)
                    await route.abort()
                else:
                    await route.fulfill(response=response)
            except PlaywrightError:
                # Catch inside the callback: event error logs can contain headers.
                await route.abort()
        else:
            await route.abort()

    await page.route("**/*", restrict)
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
        if violations or page.url != url or (response and response.from_service_worker):
            raise ObservationRejected("作品情報の取得で未対応の遷移を検出しました")
        if response is None or not response.ok:
            raise ObservationUnavailable("作品情報を取得できませんでした（手動確認可）")
        yield page
        if violations or page.url != url:
            raise ObservationRejected("作品情報の確認中にページが変わりました")
    except PlaywrightError:
        if violations:
            raise ObservationRejected("作品情報の取得でredirect等を拒否しました") from None
        raise ObservationUnavailable("作品情報の通信を確認できませんでした（手動確認可）") from None
    finally:
        await page.unroute("**/*", restrict)


async def require_canonical(page, expected):
    values = await page.locator('link[rel="canonical"]').evaluate_all("els => els.map(e => e.href)")
    if not values:
        raise ObservationUnavailable("作品ページのcanonicalが確認できません（手動確認可）")
    if values != [expected]:
        raise ObservationRejected("作品ページのcanonicalが対象作品と一致しません")


def observed_title(resolution, title, document_url):
    title = " ".join(title.split()) if isinstance(title, str) else ""
    if not title:
        raise ObservationUnavailable("作品名が一意に確認できませんでした（手動確認可）")
    return replace(resolution, title=title, evidence=(*resolution.evidence,
        f"work document title: {document_url}; {datetime.now(UTC).isoformat()}"))


def observation_failure(resolution, error):
    if isinstance(error, ObservationRejected):
        return resolution.blocked(str(error))
    return replace(resolution, warnings=(*resolution.warnings, str(error)))
