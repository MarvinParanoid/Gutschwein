from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import EventKind, ValueKind, VoucherStatus


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_id: int
    username: str
    display_name: str


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


class VoucherCreate(VoucherFields):
    # Relative path returned by POST /api/uploads.
    image_id: str | None = None
    status: VoucherStatus = VoucherStatus.active

    @field_validator("status")
    @classmethod
    def only_editable_statuses(cls, value: VoucherStatus) -> VoucherStatus:
        if value not in (VoucherStatus.draft, VoucherStatus.active):
            raise ValueError("Новый купон может быть только черновиком или активным")
        return value


class VoucherUpdate(BaseModel):
    """PATCH body: every field optional, only provided ones are applied."""

    merchant: str | None = Field(None, max_length=128)
    title: str | None = Field(None, max_length=256)
    code: str | None = Field(None, max_length=128)
    value_kind: ValueKind | None = None
    value_amount: Decimal | None = None
    currency: str | None = Field(None, max_length=8)
    valid_from: date | None = None
    valid_until: date | None = None
    conditions: str | None = None
    notes: str | None = None
    image_id: str | None = None
    balance_amount: Decimal | None = None
    balance_uncertain: bool | None = None


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
            raise ValueError("Укажите либо потраченную сумму, либо остаток")
        return self


class CommentCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Пустой комментарий")
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


class StatsOut(BaseModel):
    currency: str = "EUR"

    # What is available right now.
    on_cards: Decimal = Decimal("0")
    cards_active: int = 0
    # Cards whose balance nobody has checked lately, counted apart.
    uncertain_balance: Decimal = Decimal("0")
    cards_uncertain: int = 0

    # Money at risk of quietly evaporating.
    expiring_soon: Decimal = Decimal("0")
    expiring_soon_days: int = 30
    expired_balance: Decimal = Decimal("0")
    archived_balance: Decimal = Decimal("0")

    # What has been spent.
    spent_total: Decimal = Decimal("0")
    spent_this_month: Decimal = Decimal("0")
    spent_prev_month: Decimal = Decimal("0")

    by_merchant: list[MerchantSpend] = []
    by_member: list[MemberSpend] = []
    monthly: list[MonthSpend] = []


class MerchantStat(BaseModel):
    """One shop chip on the main screen."""

    merchant: str
    count: int
    balance: Decimal = Decimal("0")
    # How many times money was ever spent here — the frequency the order is based on.
    uses: int = 0


class CountsOut(BaseModel):
    """Per-tab counters for the menu, plus money still sitting in the archive."""

    active: int = 0
    draft: int = 0
    used: int = 0
    archived: int = 0
    # Sum of remaining balances of archived gift cards — money not yet spent.
    archived_balance: Decimal = Decimal("0")
    currency: str = "EUR"


class UploadOut(BaseModel):
    image_id: str


class MeOut(BaseModel):
    user: UserOut
    members: list[UserOut]
