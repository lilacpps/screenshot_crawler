"""Pure research tests for Comic DAYS C1 access/list parsing."""

from __future__ import annotations

import re

from poc.comicdays_c1_access_probe import parse_atom_entries, summarize_json


def test_atom_parser_prefers_episode_alternate_over_thumbnail_enclosure() -> None:
    fixture = b"""
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>comicdays:episode:123</id>
        <title>Episode One</title>
        <updated>2026-10-02T03:00:00Z</updated>
        <link rel="enclosure" href="https://cdn-img.comic-days.com/public/episode-thumbnail/123-hash" />
        <link rel="alternate" href="https://comic-days.com/episode/123" />
      </entry>
    </feed>
    """

    entries = parse_atom_entries(fixture)

    assert entries == [
        {
            "id": "comicdays:episode:123",
            "title": "Episode One",
            "updated": "2026-10-02T03:00:00Z",
            "link": "https://comic-days.com/episode/123",
        }
    ]
    assert re.search(r"/episode/123$", entries[0]["link"])


def test_json_summary_drops_sensitive_string_fields() -> None:
    result = summarize_json(
        {
            "access_token": "secret",
            "signature": "signed",
            "free_only": True,
            "episode_id": "123",
        }
    )

    assert "access_token" not in result
    assert "signature" not in result
    assert result["free_only"] is True
    assert result["episode_id"] == "123"
