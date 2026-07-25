"""Money formatting for chat messages.

Decimal.normalize() turned a 10 EUR card into "1E+1 EUR" in the bot's reply and in
every family-chat notification. Round amounts are the common case, so this is
pinned down per value.
"""

from decimal import Decimal

import pytest

from app.models import ValueKind, Voucher
from app.services import format_amount, value_label


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10", "10"),
        ("10.00", "10"),
        ("50", "50"),
        ("100", "100"),
        ("1000", "1000"),
        ("15", "15"),
        ("12.50", "12.5"),
        ("12.55", "12.55"),
        ("0.50", "0.5"),
        ("0", "0"),
        ("0.05", "0.05"),
        # Anything that would previously come out as an exponent.
        ("20", "20"),
        ("200", "200"),
    ],
)
def test_no_scientific_notation(value: str, expected: str) -> None:
    assert format_amount(Decimal(value)) == expected


def test_value_label_of_a_round_card() -> None:
    card = Voucher(
        merchant="Test", value_kind=ValueKind.amount, value_amount=Decimal("10"), currency="EUR"
    )
    assert value_label(card) == "10 EUR"


def test_value_label_of_a_percent_voucher() -> None:
    percent = Voucher(
        value_kind=ValueKind.percent, value_amount=Decimal("20.00"), currency="EUR"
    )
    assert value_label(percent) == "-20%"
