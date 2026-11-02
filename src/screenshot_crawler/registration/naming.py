"""Human-readable suggestions; machine readings are never confirmation."""

import re
import unicodedata
from dataclasses import dataclass


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    # Do not silently drop unresolved Japanese characters from a title.
    if any(ord(char) > 127 for char in value):
        return ""
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def valid_slug(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", value))


def available_name(base: str, reserved) -> str:
    if not base:
        return ""
    result, index = base, 1
    while result in reserved:
        index += 1
        result = f"{base}_{index}"
    return result


@dataclass(frozen=True)
class NameSuggestion:
    reading: str
    work_key: str
    evidence: str


def suggest_name(title: str, reading: str = "") -> NameSuggestion:
    value = reading or title
    normalized = unicodedata.normalize("NFKC", value)
    if normalized.isascii():
        return NameSuggestion(reading, slug(normalized), "ASCII suggestion; human confirmation required")
    try:
        from pykakasi import kakasi
        words = kakasi().convert(normalized)
        return NameSuggestion("".join(word["hira"] for word in words),
            slug(" ".join(word["hepburn"] for word in words)),
            "pykakasi machine reading; human confirmation required")
    except ImportError:
        return NameSuggestion(reading, "", "読み又はローマ字IDを手入力してください（pykakasi未導入）")
