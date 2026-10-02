from datetime import datetime

import pytest

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.comicdays import ComicDaysSitePolicy


def _source(mode: str, available: bool = True) -> Source:
    return Source(1, 1, "comicdays", "1", None, mode, None, available, None, None, None, None, None, "", "", None)


@pytest.mark.parametrize("mode", ["paid", "quota", "owned", "rental", "grant", "unknown"])
def test_comicdays_policy_rejects_non_free_modes(mode: str) -> None:
    result = ComicDaysSitePolicy().evaluate(_source(mode), now=datetime.now(JST), quota_available=10)
    assert not result.eligible
    assert result.access_strategy is None


def test_comicdays_policy_allows_only_current_free_source() -> None:
    result = ComicDaysSitePolicy().evaluate(_source("free"), now=datetime.now(JST), quota_available=None)
    assert result.eligible and result.access_strategy == "direct" and not result.consumes_quota
    assert not ComicDaysSitePolicy().evaluate(_source("free", False), now=datetime.now(JST), quota_available=None).eligible
