"""Manga ONE login flow."""

from __future__ import annotations

import asyncio

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class MangaOneLoginError(RuntimeError):
    """Raised when Manga ONE login cannot be completed safely."""


_LOGIN_FORM_TIMEOUT_MS = 15_000
_LOGIN_RESULT_TIMEOUT_MS = 15_000


async def _first_visible(
    root: Page | Locator,
    selectors: tuple[str, ...],
    label: str,
) -> Locator:
    """Find a visible control while allowing the client-rendered form to mount."""

    elapsed_ms = 0
    while elapsed_ms < _LOGIN_FORM_TIMEOUT_MS:
        for selector in selectors:
            candidates = root.locator(selector)
            for index in range(await candidates.count()):
                candidate = candidates.nth(index)
                try:
                    if await candidate.is_visible(timeout=250):
                        return candidate
                except PlaywrightTimeoutError:
                    continue
        await asyncio.sleep(0.1)
        elapsed_ms += 100
    raise MangaOneLoginError(f"Manga ONE {label} was not found")


async def _wait_for_login_result(page: Page, previous_url: str) -> None:
    """Wait for Manga ONE's client-side login redirect."""

    try:
        await page.wait_for_url(
            lambda url: url != previous_url,
            timeout=_LOGIN_RESULT_TIMEOUT_MS,
            wait_until="domcontentloaded",
        )
    except PlaywrightTimeoutError:
        # Invalid credentials or an additional challenge can keep the same URL.
        # The caller checks that the form has disappeared before returning.
        pass


async def login_mangaone(
    page: Page,
    *,
    email: str,
    password: str,
    home_url: str = "https://manga-one.com/login",
) -> None:
    """Open Manga ONE's login page, fill credentials, and submit the form."""

    await page.goto(home_url, wait_until="domcontentloaded", timeout=30_000)

    email_field = await _first_visible(
        page,
        (
            "input[name='email']",
            "input[type='email']",
            "input[autocomplete='username']",
        ),
        "email field",
    )
    password_field = await _first_visible(
        page,
        (
            "input[name='password']",
            "input[type='password']",
            "input[autocomplete='current-password']",
        ),
        "password field",
    )
    await email_field.fill(email)
    await password_field.fill(password)

    login_form = page.locator("form:has(input[name='email'])")
    submit = await _first_visible(
        login_form,
        ("button[type='submit']", "button"),
        "submit button",
    )
    submitted_url = page.url
    await submit.click()
    await _wait_for_login_result(page, submitted_url)

    remaining_form = page.locator("form:has(input[name='email'])")
    if await remaining_form.count():
        try:
            if await remaining_form.first.is_visible(timeout=500):
                raise MangaOneLoginError(
                    "Manga ONE login did not complete; the login form is still visible "
                    "(credentials may be incorrect, or a validation error, CAPTCHA, or MFA "
                    "may be present)."
                )
        except PlaywrightTimeoutError:
            pass

    if page.url == submitted_url:
        raise MangaOneLoginError(
            "Manga ONE login did not complete; the page did not navigate after submission."
        )
