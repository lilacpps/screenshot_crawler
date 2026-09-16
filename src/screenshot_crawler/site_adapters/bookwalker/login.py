"""BookWalker login flow."""

from __future__ import annotations

import re

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class BookWalkerLoginError(RuntimeError):
    """Raised when BookWalker login cannot be completed safely."""


async def _first_visible(page: Page, selectors: tuple[str, ...], label: str) -> Locator:
    for selector in selectors:
        candidates = page.locator(selector)
        for index in range(await candidates.count()):
            candidate = candidates.nth(index)
            if await candidate.is_visible():
                return candidate
    raise BookWalkerLoginError(f"BookWalker {label} was not found")


async def _wait_briefly_for_navigation(page: Page) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except PlaywrightTimeoutError:
        pass


async def _wait_for_login_result(page: Page, previous_url: str) -> None:
    """Wait for BookWalker's post-login navigation before checking the form."""

    try:
        await page.wait_for_url(
            lambda url: url != previous_url,
            timeout=15_000,
            wait_until="domcontentloaded",
        )
    except PlaywrightTimeoutError:
        # Invalid credentials or an additional challenge can keep the same URL.
        # The caller will inspect the still-visible form and stop safely.
        pass


async def login_bookwalker(
    page: Page,
    *,
    email: str,
    password: str,
    home_url: str = "https://bookwalker.jp/",
) -> None:
    """Open BookWalker's login UI, fill credentials, and submit it."""

    if "bookwalker.jp" not in page.url:
        await page.goto(home_url, wait_until="domcontentloaded", timeout=30_000)

    login_link = await _first_visible(
        page,
        (
            "a:has-text('ログイン')",
            "button:has-text('ログイン')",
            "[role='link']:has-text('ログイン')",
            "[role='button']:has-text('ログイン')",
        ),
        "login button",
    )
    await login_link.click()
    await _wait_briefly_for_navigation(page)

    email_field = await _first_visible(
        page,
        (
            "input[type='email']",
            "input[autocomplete='username']",
            "input[name='j_username']",
            "input[name='email']",
            "input[name='mail']",
            "input[placeholder*='メール']",
        ),
        "email field",
    )
    password_field = await _first_visible(
        page,
        (
            "input[type='password']",
            "input[autocomplete='current-password']",
            "input[name='j_password']",
            "input[name='password']",
            "input[placeholder*='パスワード']",
        ),
        "password field",
    )
    await email_field.fill(email)
    await password_field.fill(password)

    submit = await _first_visible(
        page,
        (
            "button:has-text('ログイン')",
            "input[type='submit'][value*='ログイン']",
            "button[type='submit']",
            "[role='button']:has-text('ログイン')",
        ),
        "submit button",
    )
    submitted_url = page.url
    await submit.click()
    await _wait_for_login_result(page, submitted_url)

    # Do not guess past an unresolved login screen. CAPTCHA, MFA, or a
    # validation error requires a human decision instead of an automatic retry.
    remaining_passwords = page.locator("input[type='password']")
    if await remaining_passwords.count() and await remaining_passwords.first.is_visible():
        error_text = await page.locator("body").inner_text(timeout=5_000)
        if re.search(r"エラー|正しく|認証|パスワード|メールアドレス", error_text):
            raise BookWalkerLoginError(
                "BookWalker login did not complete; the login form is still visible "
                "(credentials may be incorrect, or a validation error, CAPTCHA, or MFA "
                "may be present)."
            )
