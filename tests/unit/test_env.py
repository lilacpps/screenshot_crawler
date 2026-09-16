from pathlib import Path

import pytest

from screenshot_crawler.auth.env import (
    read_env_file,
    require_env_value,
    require_site_env_value,
    site_env_name,
)


def test_read_env_file_supports_comments_quotes_and_export(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nexport BOOKWALKER_EMAIL='reader@example.com'\n"
        "BOOKWALKER_PASSWORD=secret # local only\n",
        encoding="utf-8",
    )

    assert read_env_file(env_file) == {
        "BOOKWALKER_EMAIL": "reader@example.com",
        "BOOKWALKER_PASSWORD": "secret",
    }


def test_read_env_file_rejects_invalid_entries(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("not-an-entry\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid environment entry"):
        read_env_file(env_file)


def test_require_env_value_does_not_accept_empty_values() -> None:
    with pytest.raises(ValueError, match="BOOKWALKER_PASSWORD"):
        require_env_value("BOOKWALKER_PASSWORD", {"BOOKWALKER_PASSWORD": ""})


def test_site_env_values_are_scoped_by_site_name() -> None:
    values = {"BOOKWALKER_URL": "https://bookwalker.jp/st3/"}

    assert site_env_name("bookwalker", "url") == "BOOKWALKER_URL"
    assert require_site_env_value("bookwalker", "url", values) == values["BOOKWALKER_URL"]


@pytest.mark.parametrize("site", ["bookwalker-site", "bookwalker/site", ""])
def test_site_env_name_rejects_unsafe_site_names(site: str) -> None:
    with pytest.raises(ValueError):
        site_env_name(site, "URL")
