"""Stable Watchlist fingerprints used by scope reconciliation and Discovery."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from screenshot_crawler.watchlist.models import WatchlistTarget


def target_scope_definition(target: WatchlistTarget) -> dict[str, object]:
    scope = target.discovery_scope
    if scope is not None:
        excluded = tuple(scope.excluded_external_ids)
        if any(not isinstance(value, str) or not value.strip() for value in excluded):
            raise ValueError("discovery_scope.excluded_external_ids must contain non-empty strings")
        if len(excluded) != len(set(excluded)):
            raise ValueError("discovery_scope.excluded_external_ids contains duplicates")
        excluded = tuple(sorted(excluded))
        if scope.from_url is None and scope.through_url is None and not excluded:
            scope = None
    scope_definition: dict[str, object] | None
    if scope is None:
        scope_definition = None
    else:
        scope_definition = {
            "from_url": scope.from_url,
            "through_url": scope.through_url,
        }
        if excluded:
            scope_definition["excluded_external_ids"] = list(excluded)
    return {
        "work_key": target.work_key,
        "key": target.key,
        "site": target.site,
        "url": target.url,
        "discovery_scope": scope_definition,
    }


def target_scope_fingerprint(target: WatchlistTarget) -> str:
    return _fingerprint(target_scope_definition(target))


def normalized_work_configuration(
    targets: Iterable[WatchlistTarget], *, include_archive_order: bool
) -> list[dict[str, object]]:
    normalized = []
    for target in targets:
        value = target_scope_definition(target)
        if include_archive_order:
            value["archive_order"] = target.archive_order
        normalized.append(value)
    return sorted(normalized, key=lambda value: str(value["key"]))


def work_scope_fingerprint(targets: Iterable[WatchlistTarget]) -> str:
    return _fingerprint(normalized_work_configuration(targets, include_archive_order=True))


def work_definition_fingerprint(targets: Iterable[WatchlistTarget]) -> str:
    return _fingerprint(normalized_work_configuration(targets, include_archive_order=False))


def configuration_json(targets: Iterable[WatchlistTarget]) -> str:
    return json.dumps(
        normalized_work_configuration(targets, include_archive_order=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
