"""Interactively save a Playwright authentication state.

This command never enters credentials or clicks login controls. The user
logs in in the headed browser and explicitly confirms that the state may be
saved by pressing Enter in the terminal.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from screenshot_crawler.auth.storage import auth_state_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Save a manually-created Playwright authentication state."
    )
    parser.add_argument("--site", required=True, help="Site name used for .auth/<site>.json")
    parser.add_argument("--url", required=True, help="Login or target URL to open")
    parser.add_argument(
        "--auth-dir",
        type=Path,
        default=Path(".auth"),
        help="Directory in which to save authentication state (default: .auth)",
    )
    parser.add_argument(
        "--native-window",
        action="store_true",
        help="Maximize Chromium and use its native viewport for manual login",
    )
    return parser.parse_args()


async def save_auth_state(
    *,
    site: str,
    url: str,
    auth_dir: Path,
    native_window: bool = False,
) -> Path:
    """Open a headed browser and save state after explicit user confirmation."""

    output_path = auth_state_path(site, auth_dir=auth_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        launch_options = {"headless": False}
        if native_window:
            launch_options["args"] = ["--start-maximized"]
        browser = await playwright.chromium.launch(**launch_options)
        try:
            context_options = {"no_viewport": True} if native_window else {}
            context = await browser.new_context(**context_options)
            page = await context.new_page()
            await page.goto(url)
            print("Log in manually in the headed Chromium window.")
            print("When you are finished, return here and press Enter to save auth state.")
            await asyncio.to_thread(input)
            await context.storage_state(path=str(output_path), indexed_db=True)
        finally:
            await browser.close()

    print(f"Authentication state saved for site '{site}'.")
    return output_path


def main() -> None:
    args = _parse_args()
    asyncio.run(
        save_auth_state(
            site=args.site,
            url=args.url,
            auth_dir=args.auth_dir,
            native_window=args.native_window,
        )
    )


if __name__ == "__main__":
    main()
