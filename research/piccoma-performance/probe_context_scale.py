"""Probe Playwright context DPR conversion without opening a site page."""

from __future__ import annotations

import asyncio
import json

from playwright.async_api import async_playwright


async def main() -> None:
    output = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
        for factor in (
            0.99999997, 0.99999998, 0.999999984, 0.999999985,
            0.999999986, 0.99999999, 0.999999995, 1.0, 1.000000005,
        ):
            options = {"viewport": {"width": 1904, "height": 1200}}
            if factor is not None:
                options["device_scale_factor"] = factor
            context = await browser.new_context(**options)
            page = await context.new_page()
            observed = await page.evaluate(
                "() => ({inner: [innerWidth, innerHeight], dpr: devicePixelRatio, "
                "screen: [screen.width, screen.height]})"
            )
            output.append({"requested_factor": factor, **observed})
            await context.close()
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
