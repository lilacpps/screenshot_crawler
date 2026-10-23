"""``python -m screenshot_crawler.gui`` entry point."""

from .main import main

if __name__ == "__main__":  # pragma: no cover - exercised by subprocess
    raise SystemExit(main())

