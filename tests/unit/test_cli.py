from pathlib import Path

import pytest

from screenshot_crawler.cli import _parser


def test_crawl_uses_cdp_options() -> None:
    args = _parser().parse_args(
        [
            "crawl",
            "--site",
            "mangaone",
            "--url",
            "https://manga-one.com/manga/2379/chapter/214131",
            "--cdp-endpoint",
            "http://127.0.0.1:9333",
        ]
    )

    assert args.cdp_endpoint == "http://127.0.0.1:9333"
    assert args.env_file == Path(".env")
    assert not hasattr(args, "auth_state")
    assert not hasattr(args, "auth_required")
    assert not hasattr(args, "headed")


@pytest.mark.parametrize("option", ["--auth-state", "--auth-required", "--headed"])
def test_crawl_rejects_non_cdp_browser_options(option: str) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "crawl",
                "--site",
                "mangaone",
                "--url",
                "https://manga-one.com/",
                option,
            ]
        )
