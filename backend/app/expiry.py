"""Default expiry dates per shop.

Most gift cards do not print a date: the shop has a rule instead. Two rules cover
everything the family buys.

  * three years to the day from the purchase;
  * until the end of the third calendar year — the German default (§199 BGB), where
    the clock starts at the end of the year of purchase, so the date always lands on
    31 December.

A date derived this way is a guess, not something read off the card, and is stored
with `expiry_estimated` set so the app can say so out loud.
"""

import re
from datetime import date
from enum import StrEnum


class Rule(StrEnum):
    three_years = "three_years"
    end_of_third_year = "end_of_third_year"
    # Known not to expire, as opposed to a shop we simply have no rule for. Both
    # end up without a date; the difference is whether we know why.
    never = "never"


# Keyed by normalised shop name. Aliases exist because the same shop gets typed in
# several ways: "Jet", "Jet Tankstelle", "TotalEnergies", "Total Energies".
#
# Where a shop prints no rule of its own, the statutory one applies: three years
# counted from the end of the year of purchase (§195 with §199 BGB), which is why
# so many entries below are `end_of_third_year` rather than three years to the day.
EXPIRY_RULES: dict[str, Rule] = {
    "rewe": Rule.three_years,
    "penny": Rule.three_years,
    "kaufland": Rule.three_years,
    "ikea": Rule.three_years,
    "rossmann": Rule.three_years,
    "rossman": Rule.three_years,
    "jet": Rule.end_of_third_year,
    "totalenergies": Rule.end_of_third_year,
    "total": Rule.end_of_third_year,
    # Digital balances that are not time-limited.
    "amazon": Rule.never,
    "googleplay": Rule.never,
    "google": Rule.never,
    "play": Rule.never,
    # The rest follow the statutory limitation unless their card says otherwise.
    "douglas": Rule.end_of_third_year,
    "mediamarkt": Rule.end_of_third_year,
    "media": Rule.end_of_third_year,
    "saturn": Rule.end_of_third_year,
    "obi": Rule.end_of_third_year,
    "hm": Rule.end_of_third_year,
    "decathlon": Rule.end_of_third_year,
    "tkmaxx": Rule.end_of_third_year,
    "tk": Rule.end_of_third_year,
    "louis": Rule.end_of_third_year,
    "primark": Rule.end_of_third_year,
    "lieferando": Rule.end_of_third_year,
    "airbnb": Rule.end_of_third_year,
    "zalando": Rule.end_of_third_year,
    "otto": Rule.end_of_third_year,
    "wolt": Rule.end_of_third_year,
}


def _tokens(merchant: str) -> set[str]:
    """Words of a shop name, plus the whole name glued together.

    "Total Energies" has to match the same rule as "TotalEnergies", while "Jetzt
    Markt" must not be mistaken for "Jet" — hence whole words, never substrings.
    """
    words = re.findall(r"[a-zа-яё0-9]+", merchant.lower())
    return set(words) | {"".join(words)}


def rule_for(merchant: str) -> Rule | None:
    if not merchant:
        return None
    for token in _tokens(merchant):
        rule = EXPIRY_RULES.get(token)
        if rule is not None:
            return rule
    return None


def _plus_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        # 29 February in a year that has none.
        return day.replace(year=day.year + years, month=2, day=28)


def default_expiry(merchant: str, purchased_on: date) -> date | None:
    """The date this shop's card would run out, or None if we have no rule."""
    rule = rule_for(merchant)
    if rule is Rule.three_years:
        return _plus_years(purchased_on, 3)
    if rule is Rule.end_of_third_year:
        return date(purchased_on.year + 3, 12, 31)
    # Rule.never and an unknown shop both mean "do not invent a date".
    return None
