"""Per-shop expiry rules.

The two rules differ by more than a few days: three years to the day from a July
purchase lands in July, while the German end-of-third-calendar-year rule always
lands on 31 December — five months later.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.expiry import Rule, default_expiry, rule_for
from app.models import utcnow


@pytest.mark.parametrize(
    ("merchant", "rule"),
    [
        ("Rewe", Rule.three_years),
        ("rewe", Rule.three_years),
        ("  REWE  ", Rule.three_years),
        ("Penny", Rule.three_years),
        ("Kaufland", Rule.three_years),
        ("IKEA", Rule.three_years),
        ("Rossmann", Rule.three_years),
        ("Rossman", Rule.three_years),
        ("Jet", Rule.end_of_third_year),
        ("Jet Tankstelle", Rule.end_of_third_year),
        ("TotalEnergies", Rule.end_of_third_year),
        ("Total Energies", Rule.end_of_third_year),
        ("Total Energies Tankstelle", Rule.end_of_third_year),
    ],
)
def test_shops_are_recognised_however_they_are_typed(merchant: str, rule: Rule) -> None:
    assert rule_for(merchant) is rule


@pytest.mark.parametrize("merchant", ["Lidl", "Aldi", "", "Jetzt Markt", "Totalitarian Books"])
def test_unknown_shops_get_no_rule(merchant: str) -> None:
    """Whole words only — "Jetzt" must not be read as "Jet"."""
    assert rule_for(merchant) is None
    assert default_expiry(merchant, date(2026, 7, 25)) is None


def test_three_years_is_to_the_day() -> None:
    assert default_expiry("Rewe", date(2026, 7, 25)) == date(2029, 7, 25)
    assert default_expiry("Ikea", date(2026, 1, 1)) == date(2029, 1, 1)


def test_end_of_third_year_always_lands_on_31_december() -> None:
    # Bought in July 2026 → 31.12.2029, five months later than the other rule.
    assert default_expiry("Jet", date(2026, 7, 25)) == date(2029, 12, 31)
    # Even a purchase on the last day of the year keeps three full years.
    assert default_expiry("TotalEnergies", date(2026, 12, 31)) == date(2029, 12, 31)
    assert default_expiry("Jet", date(2026, 1, 1)) == date(2029, 12, 31)


def test_leap_day_does_not_crash() -> None:
    assert default_expiry("Rewe", date(2028, 2, 29)) == date(2031, 2, 28)


def test_card_created_today_gets_the_shop_rule(client: TestClient) -> None:
    card = client.post(
        "/api/vouchers",
        json={"merchant": "Kaufland", "value_kind": "amount", "value_amount": "50"},
    ).json()

    # utcnow(), not date.today(): around midnight the local date is already
    # tomorrow while the server still counts from yesterday.
    expected = default_expiry("Kaufland", utcnow().date())
    assert card["valid_until"] == expected.isoformat()
    # Flagged as a guess: the app must not present it as printed on the card.
    assert card["expiry_estimated"] is True


def test_a_typed_date_is_never_replaced(client: TestClient) -> None:
    card = client.post(
        "/api/vouchers",
        json={"merchant": "Rewe", "value_kind": "amount", "value_amount": "50",
              "valid_until": "2027-03-01"},
    ).json()

    assert card["valid_until"] == "2027-03-01"
    assert card["expiry_estimated"] is False


def test_activation_date_moves_the_deadline(client: TestClient) -> None:
    """valid_from is when the card was bought, so the rule counts from there."""
    card = client.post(
        "/api/vouchers",
        json={"merchant": "Jet", "value_kind": "amount", "value_amount": "60",
              "valid_from": "2024-05-10"},
    ).json()

    assert card["valid_until"] == "2027-12-31"
    assert card["expiry_estimated"] is True


def test_unknown_shop_stays_without_a_date(client: TestClient) -> None:
    card = client.post(
        "/api/vouchers",
        json={"merchant": "Магазин у дома", "value_kind": "amount", "value_amount": "10"},
    ).json()

    assert card["valid_until"] is None
    assert card["expiry_estimated"] is False
