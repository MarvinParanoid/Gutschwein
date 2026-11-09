from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app import barcode
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


# The column is NUMERIC(10, 2); SQLite enforces neither, so the schema does.
MAX_MONEY = Decimal("99999999.99")


def check_money(value: Decimal | None) -> Decimal | None:
    """Cents, not below zero, within the column. Keys, so the reader's language applies."""
    if value is None:
        return value
    if not value.is_finite():
        raise ValueError("error.amount_invalid")
    if value < 0:
        raise ValueError("error.amount_negative")
    if value > MAX_MONEY:  # before quantize(), which overflows on a huge value
        raise ValueError("error.amount_too_large")
    if value != value.quantize(Decimal("0.01")):
        raise ValueError("error.amount_precision")
    return value


Money = Annotated[Decimal, AfterValidator(check_money)]


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
    value_amount: Money | None = None
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


def blank_is_none(value: object) -> object:
    """An empty or blank string means no barcode, the same as null."""
    if isinstance(value, str):
        return value.strip() or None
    return value


class VoucherCreate(VoucherFields):
    # Relative path returned by POST /api/uploads.
    image_id: str | None = None
    # The symbology to draw `code` in, named by hand. Left out, the picture decides;
    # null means "no barcode, just the number".
    barcode_format: str | None = Field(None, max_length=32)
    status: VoucherStatus = VoucherStatus.active
    currency: Currency = "EUR"

    normalize_barcode_format = field_validator("barcode_format", mode="before")(blank_is_none)

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
    value_amount: Money | None = None
    currency: Currency | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    conditions: str | None = None
    notes: str | None = None
    image_id: str | None = None
    barcode_format: str | None = Field(None, max_length=32)
    balance_uncertain: bool | None = None

    normalize_currency = field_validator("currency", mode="before")(normalize_currency)
    normalize_barcode_format = field_validator("barcode_format", mode="before")(blank_is_none)

    @model_validator(mode="before")
    @classmethod
    def balance_has_its_own_endpoint(cls, data: object) -> object:
        """The balance changes only through POST /balance, which writes its event.

        It used to be a PATCH field too: set with no `balance_updated` behind it, so
        the card and its history disagreed, and outside the lock that keeps payments
        from overwriting each other. Refused rather than left out, because an unknown
        field is otherwise dropped in silence — a client would think it had worked.
        """
        if isinstance(data, dict) and "balance_amount" in data:
            raise ValueError("error.balance_not_patchable")
        return data


class VoucherOut(VoucherFields):
    model_config = ConfigDict(from_attributes=True)

    # Checked where an amount is typed in, never where one is read back: a card
    # stored before the rules must still list — one bad row would otherwise turn
    # the whole list into a 500.
    value_amount: Decimal | None = None
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

    @computed_field
    @property
    def barcode_version(self) -> str | None:
        """What the client puts into the barcode's address (`?v=`), see barcode.version.

        Null when there is nothing to draw. Computed here rather than in the client,
        so the one implementation is the one the barcode route checks against.
        """
        if not self.code or not self.barcode_format:
            return None
        return barcode.version(self.code, self.barcode_format)


class BarcodeOut(BaseModel):
    """A barcode drawn for a card with no picture to hang a capability URL on."""

    format: str
    svg: str


class BalanceUpdate(BaseModel):
    """Either what was just spent, or what the receipt says is left. Not both."""

    spent: Money | None = None
    remaining: Money | None = None
    note: str = Field("", max_length=200)

    @field_validator("spent")
    @classmethod
    def something_was_spent(cls, value: Decimal | None) -> Decimal | None:
        """A payment of nothing is not a payment — and would only add a 0 to the log."""
        if value is not None and value == 0:
            raise ValueError("error.spent_zero")
        return value

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
