# BookWalker login command

The login command attaches to the dedicated Chrome started by
`scripts/start_bookwalker_chrome.ps1`. It reads the site-scoped values from `.env` and
uses the existing Chrome profile, so the resulting cookies remain in that
profile for later CDP crawls.

## Setup

```powershell
Copy-Item .env.example .env
# Edit .env and set BOOKWALKER_URL, BOOKWALKER_EMAIL, and BOOKWALKER_PASSWORD.
```

Start the browser first:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_bookwalker_chrome.ps1
```

Then run the login command:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli login --site bookwalker
```

The command does not print credentials and does not save a second auth-state
file. The dedicated `.chrome-bookwalker` profile is the persistent session.

If the site presents CAPTCHA, MFA, or a validation error, the command stops and
does not retry automatically.
