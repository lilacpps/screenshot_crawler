"""Load and update the deliberately small ``watchlist.yaml`` format."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from screenshot_crawler.watchlist.models import WatchlistTarget


class WatchlistError(ValueError):
    """Base error for invalid or unmodifiable watchlists."""


class InvalidWatchlistError(WatchlistError):
    """Raised when the YAML does not match the watchlist schema."""


class DuplicateWatchlistKeyError(WatchlistError):
    """Raised when a watchlist contains or adds a duplicate key."""


class WatchlistTargetNotFoundError(WatchlistError):
    """Raised when an operation refers to an unknown target."""


class WatchlistService:
    """Repository for a human-editable YAML watchlist.

    A missing file and a genuinely empty file represent an empty watchlist.
    Any non-empty YAML document must explicitly contain a list-valued
    ``targets`` field.
    """

    def __init__(self, path: str | Path = "watchlist.yaml") -> None:
        self.path = Path(path)

    def list_targets(self) -> list[WatchlistTarget]:
        """Return targets in file order."""

        return self._load()

    list = list_targets

    def get(self, key: str) -> WatchlistTarget:
        """Return a target by its stable key."""

        for target in self._load():
            if target.key == key:
                return target
        raise WatchlistTargetNotFoundError(f"Watchlist target not found: {key}")

    def add(
        self,
        *,
        key: str,
        work_key: str,
        site: str,
        url: str,
        label: str,
        enabled: bool = True,
    ) -> WatchlistTarget:
        """Add a target, rejecting an already-used stable key."""

        target = self._validate_target(
            WatchlistTarget(
                key=key, work_key=work_key, site=site, url=url, label=label, enabled=enabled
            ),
            source="new target",
        )
        targets = self._load()
        if any(existing.key == target.key for existing in targets):
            raise DuplicateWatchlistKeyError(f"Duplicate watchlist key: {target.key}")
        targets.append(target)
        self._write(targets)
        return target

    def remove(self, key: str) -> WatchlistTarget:
        """Remove a target without touching any Catalog data."""

        targets = self._load()
        for index, target in enumerate(targets):
            if target.key == key:
                removed = targets.pop(index)
                self._write(targets)
                return removed
        raise WatchlistTargetNotFoundError(f"Watchlist target not found: {key}")

    def set_enabled(self, key: str, enabled: bool) -> WatchlistTarget:
        """Enable or disable a target without touching any Catalog data."""

        targets = self._load()
        for index, target in enumerate(targets):
            if target.key == key:
                updated = WatchlistTarget(
                    key=target.key,
                    work_key=target.work_key,
                    site=target.site,
                    url=target.url,
                    label=target.label,
                    enabled=enabled,
                )
                targets[index] = updated
                self._write(targets)
                return updated
        raise WatchlistTargetNotFoundError(f"Watchlist target not found: {key}")

    def enable(self, key: str) -> WatchlistTarget:
        return self.set_enabled(key, True)

    def disable(self, key: str) -> WatchlistTarget:
        return self.set_enabled(key, False)

    add_target = add
    remove_target = remove
    enable_target = enable
    disable_target = disable

    def _load(self) -> list[WatchlistTarget]:
        if not self.path.exists():
            return []
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise InvalidWatchlistError(f"Cannot read watchlist {self.path}: {exc}") from exc
        except yaml.YAMLError as exc:
            raise InvalidWatchlistError(f"Malformed YAML in {self.path}: {exc}") from exc

        if raw is None:
            return []
        if not isinstance(raw, dict):
            raise InvalidWatchlistError("Watchlist root must be a mapping")
        if "targets" not in raw:
            raise InvalidWatchlistError("Watchlist must contain a 'targets' field")
        raw_targets = raw["targets"]
        if not isinstance(raw_targets, list):
            raise InvalidWatchlistError("Watchlist 'targets' must be a list")

        targets: list[WatchlistTarget] = []
        keys: set[str] = set()
        for index, raw_target in enumerate(raw_targets):
            target = self._parse_target(raw_target, index)
            if target.key in keys:
                raise DuplicateWatchlistKeyError(f"Duplicate watchlist key: {target.key}")
            keys.add(target.key)
            targets.append(target)
        return targets

    def _parse_target(self, raw_target: Any, index: int) -> WatchlistTarget:
        if not isinstance(raw_target, dict):
            raise InvalidWatchlistError(f"targets[{index}] must be a mapping")
        required = ("key", "work_key", "site", "url", "label")
        missing = [field for field in required if field not in raw_target]
        if missing:
            raise InvalidWatchlistError(
                f"targets[{index}] is missing required field(s): {', '.join(missing)}"
            )
        enabled = raw_target.get("enabled", True)
        label = raw_target.get("label")
        if not isinstance(enabled, bool):
            raise InvalidWatchlistError(f"targets[{index}].enabled must be a boolean")
        if not isinstance(label, str):
            raise InvalidWatchlistError(f"targets[{index}].label must be a string")
        return self._validate_target(
            WatchlistTarget(
                work_key=raw_target["work_key"],
                key=raw_target["key"],
                site=raw_target["site"],
                url=raw_target["url"],
                label=label,
                enabled=enabled,
            ),
            source=f"targets[{index}]",
        )

    @staticmethod
    def _validate_target(target: WatchlistTarget, *, source: str) -> WatchlistTarget:
        for name in ("key", "work_key", "site", "url", "label"):
            value = getattr(target, name)
            if not isinstance(value, str) or not value.strip():
                raise InvalidWatchlistError(f"{source}.{name} must be a non-empty string")
        if not isinstance(target.enabled, bool):
            raise InvalidWatchlistError(f"{source}.enabled must be a boolean")
        return target

    def _write(self, targets: list[WatchlistTarget]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "targets": [
                {
                    "key": target.key,
                    "work_key": target.work_key,
                    "site": target.site,
                    "url": target.url,
                    "enabled": target.enabled,
                    "label": target.label,
                }
                for target in targets
            ]
        }
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                yaml.safe_dump(payload, temporary, allow_unicode=True, sort_keys=False)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        except OSError as exc:
            raise WatchlistError(f"Cannot write watchlist {self.path}: {exc}") from exc
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
