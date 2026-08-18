"""What the bot puts in the family chat is parsed as HTML by Telegram.

A shop is named by a person, and "H&M" or "Rewe <Bahnhof>" in an unescaped message
is `Bad Request: can't parse entities`. On the notification path that error is
caught and logged, so the chat simply never hears about the card — and on the
expiry path it used to cost every card after it in the batch its warning too.
"""

from decimal import Decimal

from app.i18n import Html, group_t, html_t
from app.models import ValueKind, Voucher
from app.services import voucher_label


def _card(merchant: str) -> Voucher:
    return Voucher(
        merchant=merchant,
        value_kind=ValueKind.amount,
        value_amount=Decimal("50"),
        currency="EUR",
    )


def test_a_shop_name_cannot_close_a_tag() -> None:
    message = group_t(
        "notify.card_added", actor="Аня", label=voucher_label(_card("Rewe </b>лишнее"))
    )
    assert "</b>лишнее" not in message
    assert "&lt;/b&gt;лишнее" in message


def test_an_ampersand_is_an_entity() -> None:
    """The shop that made this real: H&M."""
    message = group_t("notify.card_added", actor="Аня", label=voucher_label(_card("H&M")))
    assert "H&amp;M" in message
    assert "H&M" not in message


def test_a_name_is_escaped_too() -> None:
    message = group_t("notify.card_added", actor="Аня & Дима", label="карта")
    assert "Аня &amp; Дима" in message


def test_the_templates_own_markup_survives() -> None:
    message = group_t("notify.card_added", actor="Аня", label="карта")
    assert "<b>карта</b>" in message


def test_a_nested_message_is_not_escaped_twice() -> None:
    """An expiry warning is built from smaller rendered messages."""
    when = group_t("notify.expires_today")
    assert isinstance(when, Html)
    message = group_t("notify.expiring", label="карта", when=when, caveat="")
    assert "&lt;" not in message
    assert str(when) in message


def test_the_bots_own_replies_escape_as_well() -> None:
    reply = html_t("bot.shop_noted", "ru", merchant="H&M")
    assert "H&amp;M" in reply


def test_the_json_api_is_left_alone() -> None:
    """`t()` also answers the HTTP API, where an entity would be a rendering bug."""
    from app.i18n import t

    detail = t("error.spend_too_much", "ru", spent="5", current="3", currency="A&B")
    assert "A&B" in detail
    assert "&amp;" not in detail
