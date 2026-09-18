"""Pure classification helpers for BookWalker product-page reader controls."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import NotRequired, TypedDict


class ReaderControlMetadata(TypedDict, total=False):
    """The small DOM metadata shape shared by BookWalker reader controls."""

    text: NotRequired[str | None]
    action: NotRequired[str | None]
    href: NotRequired[str | None]
    uuid: NotRequired[str | None]


class ReaderControlKind(StrEnum):
    """Classification of a BookWalker product-page control."""

    MARUYOMI = "maruyomi"
    TRIAL = "trial"
    OWNED = "owned"
    SUBSCRIPTION = "subscription"
    GENERIC_READER = "generic_reader"
    UNKNOWN = "unknown"


ReaderControlClassification = ReaderControlKind

_EXCLUDED_ACTIONS = {"cover", "check", "more_read", "author"}
_OWNED_ACTIONS = {"read", "reading"}


def _value(metadata: Mapping[str, object], key: str) -> str:
    raw_value = metadata.get(key)
    return raw_value.strip() if isinstance(raw_value, str) else ""


def _reader_signal(text: str, action: str, href: str) -> bool:
    return bool(
        "viewer" in href
        or "read" in action
        or "reading" in action
        or "読む" in text
        or "読み" in text
        or "まる読み" in text
        or "10分" in text
    )


def classify_reader_control(
    metadata: Mapping[str, object],
) -> ReaderControlKind:
    """Classify BookWalker control metadata without touching the browser.

    The precedence is deliberately explicit: a strong maruyomi signal wins
    over all other labels, then explicit trial/owned actions, subscription,
    generic reader signals, and finally unknown. A viewer URL by itself is
    therefore never enough to classify a control as owned.
    """

    text = _value(metadata, "text")
    action = _value(metadata, "action").lower()
    href = _value(metadata, "href").lower()

    if action in _EXCLUDED_ACTIONS:
        return ReaderControlKind.UNKNOWN

    if action == "read_maruyomi" or (
        "10分" in text and "まる読み" in text
    ):
        return ReaderControlKind.MARUYOMI

    if action == "trial_reading" or "試し読み" in text:
        return ReaderControlKind.TRIAL

    if action in _OWNED_ACTIONS or (not action and text == "読む"):
        return ReaderControlKind.OWNED

    if action == "subscription_reading" or "読み放題" in text:
        return ReaderControlKind.SUBSCRIPTION

    if _reader_signal(text, action, href):
        return ReaderControlKind.GENERIC_READER

    return ReaderControlKind.UNKNOWN


def is_reader_control_candidate(metadata: Mapping[str, object]) -> bool:
    """Return the legacy auto-flow candidate decision for the metadata."""

    return classify_reader_control(metadata) is not ReaderControlKind.UNKNOWN
