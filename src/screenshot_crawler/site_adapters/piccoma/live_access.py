"""Bounded ticket-entry observations for Piccoma's native reader UI."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from screenshot_crawler.core.errors import AccessResourceUnavailableError

PiccomaTicketKind = Literal["waitfree", "zero_plus", "binge_free"]
_PICCOMA_TIMEZONE = timezone(timedelta(hours=9))

TICKET_STATUS_KIND: Mapping[int, PiccomaTicketKind] = {
    21000: "waitfree",
    24000: "zero_plus",
    25000: "binge_free",
}
_KNOWN_NONFREE_OFFER_STATUSES = frozenset(
    {
        20000,  # WEB_READABLE_ENOUGH_POINT
        21100,  # WEB_WAITFREE_NOT_WAIT_AND_ENOUGH_POINT
        21200,  # WEB_WAITFREE_EXCEPT_NOT_WAIT_AND_ENOUGH_POINT
        21210,  # WEB_WAITFREE_EXCEPT_NOT_WAIT_AND_NOT_ENOUGH_POINT
        21220,  # WEB_WAITFREE_EXCEPT_NOT_WAIT_AND_HAS_GIFT_TICKET
        21230,  # WEB_WAITFREE_NOT_WAIT_AND_ENOUGH_TIME_SAVING
        21240,  # WEB_USABLE_AD_REWARD_TICKET_FOR_WAITFREE
        21300,  # WEB_LACK_POINTS_DIRECT_PURCHASE
        22000,  # WEB_GIFT_TICKET_READABLE
        25010,  # WEB_READABLE_NOT_RENTAL
        25210,  # WEB_WAITFREE_EXCEPT_NOT_WAIT_AND_RENTAL
        25230,  # WEB_WAITFREE_EXCEPT_NOT_WAIT_AND_RENTAL_TIME_SAVING
    }
)
TICKET_BUTTON_CLASS: Mapping[PiccomaTicketKind, str] = {
    "waitfree": "btn-waitfree",
    "zero_plus": "btn-free-plus-ticket",
    "binge_free": "btn-bingefree-ticket",
}
TICKET_ROW_MARKER: Mapping[PiccomaTicketKind, str] = {
    "waitfree": "PCM-epList_status_waitfree",
    "zero_plus": "PCM-epList_status_zeroPlus",
    "binge_free": "PCM-epList_status_bingefree",
}
PICCOMA_TICKET_NO_ACTION_REASON = "piccoma_ticket_unavailable_before_click"

_ACCESS_FIELDS = frozenset(
    {"current_episode_id", "episode_id", "product_id", "referrer_type"}
)
_ZERO_PLUS_RATIO = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)")
_ZERO_PLUS_PRESENT = re.compile(r"(?<!\d)(\d+)\s*枚\s*[（(]\s*プレゼント\s*[）)]")
_ZERO_PLUS_MODAL = re.compile(
    r"保有\s*[¥￥]\s*0\s*\+\s*券\s*[:：]?\s*(\d+)\s*枚"
)
_BINGE_MODAL_ACCOUNT = re.compile(
    r"保有\s*(?:爆|バク)読み\s*[¥￥]?\s*0\s*券\s*[:：]?\s*(\d+)\s*枚"
)
_BINGE_MODAL_WORK = re.compile(r"この作品であと\s*(\d+)\s*枚")
_BINGE_STATUS_RATIO = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)")
_WAITFREE_MODAL = re.compile(
    r"[「｢]待てば¥0[」｣]で読みますか[?？︖]"
)
_ZERO_PLUS_CONFIRMATION = re.compile(
    r"[「｢]待てば¥0[」｣]チャージ中です。\s*¥0\+券で読みますか[?？︖]"
    r"\s*保有¥[０0]\+券[:：]\s*\d+枚"
)
_BINGE_CONFIRMATION = re.compile(
    r"[「｢]待てば¥0[」｣]チャージ中です。\s*爆読み¥0券で読みますか[?？︖]"
    r"\s*保有爆読み¥0券[:：]\s*\d+枚"
    r"\s*この作品であと\s*\d+枚使えます"
)
TICKET_BUTTON_LABEL: Mapping[PiccomaTicketKind, str] = {
    "waitfree": "｢待てば¥0｣で読む",
    "zero_plus": "¥0+券で読む",
    "binge_free": "爆読み¥0券で読む",
}


class PiccomaTicketNoActionError(AccessResourceUnavailableError):
    """A recognized ticket option is unavailable before any affirmative click."""

    def __init__(self) -> None:
        super().__init__(PICCOMA_TICKET_NO_ACTION_REASON)


def piccoma_access_request_matches(
    *,
    method: str,
    url: str,
    post_data: str | None,
    product_id: str,
    episode_id: str,
) -> bool:
    """Bind the observed eligibility exchange to one exact product/episode."""

    try:
        if not piccoma_access_endpoint_matches(method=method, url=url):
            return False
        fields = parse_qs(post_data or "", keep_blank_values=True, strict_parsing=True)
    except (ValueError, TypeError):
        return False
    return (
        set(fields) == _ACCESS_FIELDS
        and fields.get("product_id") == [product_id]
        and fields.get("episode_id") == [episode_id]
        and len(fields.get("current_episode_id", ())) == 1
        and len(fields.get("referrer_type", ())) == 1
    )


def piccoma_access_endpoint_matches(*, method: str, url: str) -> bool:
    """Check the exact first-party eligibility endpoint before reading a body."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (ValueError, TypeError):
        return False
    return (
        method.upper() == "POST"
        and parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() in {"piccoma.com", "www.piccoma.com"}
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and parsed.path == "/web/user/access"
        and not parsed.query
        and not parsed.fragment
    )


def piccoma_ticket_kind_from_status(value: object) -> PiccomaTicketKind | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return TICKET_STATUS_KIND.get(value)
    return None


def is_known_nonfree_offer_status(value: object) -> bool:
    """Identify only loaded-JS statuses whose modal offers a forbidden route."""

    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value in _KNOWN_NONFREE_OFFER_STATUSES
    )


def zero_plus_available_count(text: str) -> int | None:
    """Count regular and event ¥0+ stock without confusing Gift Tickets."""

    regular = _ZERO_PLUS_RATIO.search(_normalize_digits(text))
    present = _ZERO_PLUS_PRESENT.search(_normalize_digits(text))
    if regular is None and present is None:
        return None
    return (int(regular[1]) if regular is not None else 0) + (
        int(present[1]) if present is not None else 0
    )


def zero_plus_modal_balance(text: str) -> int | None:
    match = _ZERO_PLUS_MODAL.search(_normalize_digits(text))
    return int(match[1]) if match is not None else None


def binge_modal_balances(text: str) -> tuple[int, int] | None:
    value = _normalize_digits(text)
    account = _BINGE_MODAL_ACCOUNT.search(value)
    work = _BINGE_MODAL_WORK.search(value)
    if account is None or work is None:
        return None
    return int(account[1]), int(work[1])


def binge_available_count(text: str) -> int | None:
    match = _BINGE_STATUS_RATIO.search(_normalize_digits(text))
    return int(match[1]) if match is not None else None


def waitfree_charge_ready(value: object) -> bool | None:
    """Resolve charge state from the server's exact displayed time attributes."""

    if not isinstance(value, dict):
        return None
    if value.get("className") != "PCM-chargeBar_waitfree":
        return None
    server_time = value.get("serverTime")
    charge_time = value.get("chargeTime")
    duration = value.get("chargeDuration")
    if not isinstance(server_time, str) or not isinstance(charge_time, str):
        return None
    if not isinstance(duration, str) or re.fullmatch(r"[1-9][0-9]*", duration) is None:
        return None
    try:
        server = datetime.strptime(server_time, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=_PICCOMA_TIMEZONE
        )
        charge = datetime.strptime(charge_time, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=_PICCOMA_TIMEZONE
        )
    except ValueError:
        return None
    return charge <= server


def ticket_modal_matches(kind: PiccomaTicketKind, text: str) -> bool:
    """Accept only the observed complete native confirmation copy for a kind."""

    normalized = " ".join(text.split())
    button_suffixes = (
        f" {TICKET_BUTTON_LABEL[kind]} キャンセル",
        f" {TICKET_BUTTON_LABEL[kind]}キャンセル",
        f"{TICKET_BUTTON_LABEL[kind]} キャンセル",
        f"{TICKET_BUTTON_LABEL[kind]}キャンセル",
    )
    for button_suffix in button_suffixes:
        if normalized.endswith(button_suffix):
            normalized = normalized[: -len(button_suffix)]
            break
    pattern = {
        "waitfree": _WAITFREE_MODAL,
        "zero_plus": _ZERO_PLUS_CONFIRMATION,
        "binge_free": _BINGE_CONFIRMATION,
    }[kind]
    return pattern.fullmatch(normalized) is not None


def observed_now() -> datetime:
    return datetime.now(UTC)


def _normalize_digits(value: str) -> str:
    return value.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


__all__ = [
    "PICCOMA_TICKET_NO_ACTION_REASON",
    "TICKET_BUTTON_CLASS",
    "TICKET_BUTTON_LABEL",
    "TICKET_ROW_MARKER",
    "PiccomaTicketKind",
    "PiccomaTicketNoActionError",
    "binge_available_count",
    "binge_modal_balances",
    "is_known_nonfree_offer_status",
    "observed_now",
    "piccoma_access_request_matches",
    "piccoma_ticket_kind_from_status",
    "ticket_modal_matches",
    "waitfree_charge_ready",
    "zero_plus_available_count",
    "zero_plus_modal_balance",
]
