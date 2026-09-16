# Manga ONE adapter

## Viewer and capture target

The observed chapter URL is:

`https://manga-one.com/manga/2379/chapter/214131`

Manga ONE renders the chapter reader as individual images under
`.viewer-container`, currently with `alt="page_N"`. The adapter first presses
the visible `全画面` control. With the standard `1920x1080` crawler viewport,
the images render at Full HD height. Only images overlapping the viewport are
captured; surrounding chapter-page content is ignored.

## Spread and order

The normal view is a two-page spread. The right-hand image is returned first,
then the left-hand image. The opening page and an odd final page may have only
one visible image, which is captured as-is. No center split or blank-side
guess is used.

## Navigation and page change

The adapter clicks the left side of `.viewer-container`, which advances the
right-to-left reader. Page identity is the visible `page_N` label set, with
the chapter ID as the source ID. A bounded wait requires the visible labels and
geometry to remain stable before capture; a bounded retry handles a click that
is consumed by the viewer's transition.

## Content context and stopping

The URL path provides `work_id` and `chapter_id`; the chapter ID is also used
as `content_id` and `episode_id`. A chapter URL change is `NEXT_CONTENT`.
After the final advance, the adapter waits for the viewer images to disappear
and then stops as `END`. If the viewer remains ambiguous, the adapter does not
invent a next chapter and eventually raises a page-change error with core
diagnostics.

## Ads and known limitations

Chapter-end promotional pages are ordinary chapter images and currently have
no stable DOM marker that distinguishes them from manga pages. They are kept
to avoid deleting valid final content. A fixed number of trailing pages is
intentionally not enabled by default; this can be revisited after observing
several chapters with the same reliable pattern.

Authentication is available through the shared `login` CLI command. It attaches
to an existing CDP browser, opens `MANGAONE_URL`, fills `MANGAONE_EMAIL` and
`MANGAONE_PASSWORD`, and submits the login form. Chapters that require login
still stop safely when no ready page image is available.

For a persistent Manga ONE browser profile on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_mangaone_chrome.ps1
.\venv\Scripts\python.exe -m screenshot_crawler.cli login --site mangaone
```

The login command does not print credentials or create a second auth-state file;
the `.chrome-mangaone` profile keeps the resulting session for later CDP crawls.

After login, crawl through the same CDP browser:

```powershell
.\venv\Scripts\python.exe -m screenshot_crawler.cli crawl `
  --site mangaone `
  --url "https://manga-one.com/manga/2379/chapter/214131"
```

`--cdp-endpoint` is optional when `MANGAONE_CDP_ENDPOINT` is set; otherwise the
default is `http://127.0.0.1:9222`.

Last verified: 2026-09-16.

## Output naming and ZIP packaging

The adapter exposes the chapter title as the archive title and the episode
label as generic package `order` metadata. For example:

```text
獣王と薬草-第01話.zip
獣王と薬草-第80話-後編.zip
```

The existing core packaging flow creates the ZIP under
`output/Books/漫画/<title>/` after a normal `END` or `NEXT_CONTENT` stop. The
episode parts remain separate archives; merging them or converting episodes
to volumes is intentionally deferred.
