from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import EventKind, ValueKind, VoucherStatus


class SessionOut(BaseModel):
    """A signed-in browser, as the access screen shows it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    member: str
    created_at: datetime
    last_used_at: datetime | None
    # The one asking. It is offered last and cannot be revoked from the list,
    # because signing yourself out of the screen you are standing on is a trap.
    current: bool


class InviteRequest(BaseModel):
    """A name creates a new member; without one the link is for the caller."""

    name: str = Field(default="", max_length=128)


class InviteOut(BaseModel):
    url: str
    minutes: int
    member: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # Null for a member invited from the console, who has no Telegram account.
    telegram_id: int | None
    username: str
    display_name: str


def normalize_currency(value: object) -> object:
    """Uppercase a three-letter code, or leave it for the field to reject.

    The field is typed by hand in the form, so it arrives as whatever was typed:
    'eur', ' pln', 'PLZ'. Case and spacing are ours to fix. A wrong-but-plausible
    code is not — statistics groups by this string, so 'eur' and 'EUR' have to be
    one currency, while 'PLZ' can only be steered by the form's suggestions.
    """
    return value.strip().upper() if isinstance(value, str) else value


"""Checked where a currency is typed in, not where one is read back: a database
written before this rule still has to serialize."""
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class VoucherFields(BaseModel):
    merchant: str = Field("", max_length=128)
    title: str = Field("", max_length=256)
    code: str = Field("", max_length=128)
    value_kind: ValueKind = ValueKind.other
    value_amount: Decimal | None = None
    currency: str = Field("EUR", max_length=8)
    valid_from: date | None = None
    valid_until: date | None = None
    conditions: str = ""
    notes: str = ""

    @field_validator("merchant", "title", "code", "conditions", "notes", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    normalize_currency = field_validator("currency", mode="before")(normalize_currency)


class VoucherCreate(VoucherFields):
    # Relative path returned by POST /api/uploads.
    image_id: str | None = None
    status: VoucherStatus = VoucherStatus.active
    currency: Currency = "EUR"

    @field_validator("status")
    @classmethod
    def only_editable_statuses(cls, value: VoucherStatus) -> VoucherStatus:
        if value not in (VoucherStatus.draft, VoucherStatus.active):
            raise ValueError("error.new_voucher_status")
        return value


class VoucherUpdate(BaseModel):
    """PATCH body: every field optional, only provided ones are applied."""

    merchant: str | None = Field(None, max_length=128)
    title: str | None = Field(None, max_length=256)
    code: str | None = Field(None, max_length=128)
    value_kind: ValueKind | None = None
    value_amount: Decimal | None = None
    currency: Currency | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    conditions: str | None = None
    notes: str | None = None
    image_id: str | None = None
    balance_amount: Decimal | None = None
    balance_uncertain: bool | None = None

    normalize_currency = field_validator("currency", mode="before")(normalize_currency)


class VoucherOut(VoucherFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: VoucherStatus
    balance_amount: Decimal | None
    image_id: str | None
    barcode_format: str | None
    # True when valid_until came from the shop rule rather than the card itself.
    expiry_estimated: bool
    balance_uncertain: bool
    is_expired: bool
    days_left: int | None
    created_by: UserOut
    used_by: UserOut | None
    created_at: datetime
    updated_at: datetime
    used_at: datetime | None
    comments_count: int = 0


class BalanceUpdate(BaseModel):
    """Either what was just spent, or what the receipt says is left. Not both."""

    spent: Decimal | None = Field(None, gt=0)
    remaining: Decimal | None = Field(None, ge=0)
    note: str = Field("", max_length=200)

    @model_validator(mode="after")
    def exactly_one(self) -> "BalanceUpdate":
        if (self.spent is None) == (self.remaining is None):
            raise ValueError("error.spent_or_remaining")
        return self


class CommentCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("error.empty_comment")
        return stripped


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    author: UserOut
    created_at: datetime


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: EventKind
    payload: dict
    actor: UserOut | None
    created_at: datetime


class MerchantSpend(BaseModel):
    merchant: str
    spent: Decimal = Decimal("0")
    on_cards: Decimal = Decimal("0")


class MemberSpend(BaseModel):
    name: str
    spent: Decimal = Decimal("0")
    payments: int = 0


class MonthSpend(BaseModel):
    month: str  # YYYY-MM
    spent: Decimal = Decimal("0")


class CurrencyStats(BaseModel):
    """Every money figure of one currency.

    Gift cards are not a bank balance: 200 zł at Biedronka buys nothing at Rewe, so
    the currencies are never added up and never converted. Each gets its own block,
    and the client shows one at a time.
    """

    currency: str = "EUR"

    # What is available right now.
    on_cards: Decimal = Decimal("0")
    cards_active: int = 0
    # Cards whose balance nobody has checked lately, counted apart.
    uncertain_balance: Decimal = Decimal("0")
    cards_uncertain: int = 0

    # Money at risk of quietly evaporating.
    expiring_soon: Decimal = Decimal("0")
    expired_balance: Decimal = Decimal("0")
    archived_balance: Decimal = Decimal("0")

    # What has been spent.
    spent_total: Decimal = Decimal("0")
    spent_this_month: Decimal = Decimal("0")
    spent_prev_month: Decimal = Decimal("0")

    by_merchant: list[MerchantSpend] = []
    by_member: list[MemberSpend] = []
    monthly: list[MonthSpend] = []


class StatsOut(BaseModel):
    expiring_soon_days: int = 30
    # Busiest currency first — by card count, not by amount: ranking currencies by
    # their numbers is the very comparison this split exists to refuse. Always at
    # least one block, so a family with no cards still gets a page.
    currencies: list[CurrencyStats] = []


class MerchantStat(BaseModel):
    """One shop chip on the main screen."""

    merchant: str
    count: int
    balance: Decimal = Decimal("0")
    # Empty, with a zero balance, when this shop's cards are in several currencies:
    # one chip has room for one sum, and the wrong currency beats no currency.
    currency: str = ""
    # How many times money was ever spent here — the frequency the order is based on.
    uses: int = 0


class Money(BaseModel):
    amount: Decimal = Decimal("0")
    currency: str = "EUR"


class CountsOut(BaseModel):
    """Per-tab counters for the menu, plus money still sitting in the archive."""

    active: int = 0
    draft: int = 0
    used: int = 0
    archived: int = 0
    # Remaining balances of archived gift cards — money not yet spent, per currency.
    archived_balance: list[Money] = []


class UploadOut(BaseModel):
    image_id: str


class MeOut(BaseModel):
    user: UserOut
    members: list[UserOut]
