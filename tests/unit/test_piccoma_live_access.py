from __future__ import annotations

from screenshot_crawler.site_adapters.piccoma.live_access import (
    binge_available_count,
    binge_modal_balances,
    is_known_nonfree_offer_status,
    piccoma_access_endpoint_matches,
    piccoma_access_request_matches,
    piccoma_ticket_kind_from_status,
    ticket_modal_matches,
    waitfree_charge_ready,
    zero_plus_available_count,
    zero_plus_modal_balance,
)


def test_access_request_is_bound_to_one_exact_target() -> None:
    assert piccoma_access_request_matches(
        method="POST",
        url="https://piccoma.com/web/user/access",
        post_data=(
            "current_episode_id=896199&episode_id=896199&product_id=23222&"
            "referrer_type=episode"
        ),
        product_id="23222",
        episode_id="896199",
    )
    for url in (
        "https://user@piccoma.com/web/user/access",
        "https://piccoma.com/web/user/access?episode_id=896199",
        "https://piccoma.com.evil.example/web/user/access",
        "https://piccoma.com/web/user/other",
    ):
        assert not piccoma_access_request_matches(
            method="POST",
            url=url,
            post_data=(
                "current_episode_id=896199&episode_id=896199&product_id=23222&"
                "referrer_type=episode"
            ),
            product_id="23222",
            episode_id="896199",
        )
    assert not piccoma_access_request_matches(
        method="GET",
        url="https://piccoma.com/web/user/access",
        post_data="episode_id=896199&product_id=23222",
        product_id="23222",
        episode_id="896199",
    )
    assert not piccoma_access_request_matches(
        method="POST",
        url="https://piccoma.com/web/user/access",
        post_data=(
            "current_episode_id=896199&episode_id=896199&product_id=23222&"
            "referrer_type=episode&gift_ticket=1"
        ),
        product_id="23222",
        episode_id="896199",
    )
    assert piccoma_access_request_matches(
        method="POST",
        url="https://piccoma.com/web/user/access",
        post_data=(
            "current_episode_id=12345&episode_id=896199&product_id=23222&"
            "referrer_type=episode"
        ),
        product_id="23222",
        episode_id="896199",
    )
    assert piccoma_access_request_matches(
        method="POST",
        url="https://piccoma.com/web/user/access",
        post_data=(
            "current_episode_id=&episode_id=896199&product_id=23222&"
            "referrer_type=episode"
        ),
        product_id="23222",
        episode_id="896199",
    )


def test_access_endpoint_is_checked_before_body_parsing() -> None:
    assert piccoma_access_endpoint_matches(
        method="POST", url="https://piccoma.com/web/user/access"
    )
    for method, url in (
        ("GET", "https://piccoma.com/web/user/access"),
        ("POST", "https://piccoma.com/web/product/900/point/101"),
        ("POST", "https://piccoma.com.evil.example/web/user/access"),
        ("POST", "https://piccoma.com/web/user/access?x=1"),
    ):
        assert not piccoma_access_endpoint_matches(method=method, url=url)


def test_known_status_codes_are_exact_integers() -> None:
    assert [piccoma_ticket_kind_from_status(value) for value in (21000, 24000, 25000)] == [
        "waitfree", "zero_plus", "binge_free"
    ]
    for value in (True, 0, 21001, "21000", None):
        assert piccoma_ticket_kind_from_status(value) is None
    for value in (20000, 21100, 21200, 21210, 21220, 21230, 21240, 21300, 22000, 25010, 25210, 25230):
        assert is_known_nonfree_offer_status(value)
    for value in (True, 21260, 21270, 21310, 29999, "21220", None):
        assert not is_known_nonfree_offer_status(value)


def test_zero_plus_balance_includes_present_stock_without_gift_ticket_confusion() -> None:
    assert zero_plus_available_count("6/6枚（2時間毎に回復） 0枚（プレゼント）") == 6
    assert zero_plus_available_count("0/6枚 1枚（プレゼント）") == 1
    assert zero_plus_available_count("ギフト券 3枚") is None
    assert zero_plus_available_count("残数不明") is None
    assert zero_plus_modal_balance("保有¥０+券： 6枚") == 6


def test_binge_balances_and_modal_copy_match_observed_native_text() -> None:
    assert binge_available_count("30/30枚（1作品で使用可能）") == 30
    assert binge_modal_balances(
        "「待てば¥0」チャージ中です。 爆読み¥0券で読みますか？ "
        "保有爆読み¥0券：100枚 この作品であと30枚使えます"
    ) == (100, 30)


def test_confirmation_copy_is_complete_and_kind_specific() -> None:
    assert ticket_modal_matches("waitfree", "「待てば¥0」で読みますか？")
    assert ticket_modal_matches(
        "waitfree", "「待てば¥0」で読みますか？ ｢待てば¥0｣で読むキャンセル"
    )
    assert ticket_modal_matches(
        "zero_plus",
        "「待てば¥0」チャージ中です。 ¥0+券で読みますか︖ 保有¥０+券： 6枚",
    )
    assert ticket_modal_matches(
        "binge_free",
        "「待てば¥0」チャージ中です。 爆読み¥0券で読みますか？ "
        "保有爆読み¥0券：100枚 この作品であと30枚使えます",
    )
    assert not ticket_modal_matches(
        "zero_plus",
        "「待てば¥0」チャージ中です。 ¥0+券で読みますか︖ "
        "保有¥０+券： 6枚 コインを購入しますか？",
    )
    assert not ticket_modal_matches(
        "binge_free",
        "「待てば¥0」チャージ中です。 爆読み¥0券で読みますか？ "
        "保有爆読み¥0券：100枚 この作品であと30枚使えます ギフト券",
    )


def test_waitfree_state_uses_site_server_and_next_charge_timestamps() -> None:
    assert waitfree_charge_ready({
        "className": "PCM-chargeBar_waitfree",
        "serverTime": "2026-11-18 06:28:58",
        "chargeTime": "2026-11-14 20:06:11",
        "chargeDuration": "82800",
    }) is True
    assert waitfree_charge_ready({
        "className": "PCM-chargeBar_waitfree",
        "serverTime": "2026-11-18 08:07:28",
        "chargeTime": "2026-11-19 06:04:04",
        "chargeDuration": "82800",
    }) is False
    for malformed in (
        None,
        {},
        {
            "className": "PCM-chargeBar_other",
            "serverTime": "2026-11-18 08:07:28",
            "chargeTime": "2026-11-19 06:04:04",
            "chargeDuration": "82800",
        },
        {
            "className": "PCM-chargeBar_waitfree",
            "serverTime": "unknown",
            "chargeTime": "2026-11-19 06:04:04",
            "chargeDuration": "82800",
        },
        {
            "className": "PCM-chargeBar_waitfree",
            "serverTime": "2026-11-18 08:07:28",
            "chargeTime": "2026-11-19 06:04:04",
            "chargeDuration": "0",
        },
    ):
        assert waitfree_charge_ready(malformed) is None
