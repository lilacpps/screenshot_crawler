# BookWalker login command

## Target Browser Session model

BookWalker login uses the common Browser Session architecture:

```text
shared Crawler Chrome/profile (.chrome-crawler/)
    ↑ CDP
Playwright Page
    ↓
BookWalker login handler
```

The login handler is responsible only for BookWalker DOM interaction. Chrome launch, profile selection, CDP endpoint resolution, and BrowserContext lifecycle belong to the common Browser Session layer.

The resulting BookWalker session remains in the shared Chrome profile for later crawls. The crawler does not create a second BookWalker-specific auth-state file as the standard path.

## Credentials

```powershell
Copy-Item .env.example .env
# Set BOOKWALKER_URL, BOOKWALKER_EMAIL, and BOOKWALKER_PASSWORD.
```

Target endpoint precedence:

1. `--cdp-endpoint`
2. `BOOKWALKER_CDP_ENDPOINT`
3. `CRAWLER_CDP_ENDPOINT`
4. `http://127.0.0.1:9222`

`BOOKWALKER_CDP_ENDPOINT` is an exception override. Normal operation should use the shared Crawler Chrome/global endpoint.

## Login command

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli login --site bookwalker
```

The command does not print credentials. CAPTCHA, MFA, and validation errors are not automatically bypassed.

## Current transition state

The common `start_crawler_chrome.ps1` / `.chrome-crawler/` implementation is still pending.

Until that migration is implemented, the existing launcher remains usable:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_bookwalker_chrome.ps1
```

and the current session may be stored in `.chrome-bookwalker`.

This is a compatibility path during migration, not the final Browser Session architecture. Do not duplicate this per-site launcher/profile pattern for new sites.
