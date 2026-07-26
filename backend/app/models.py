from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON}


class VoucherStatus(StrEnum):
    draft = "draft"
    active = "active"
    used = "used"
    archived = "archived"


class ValueKind(StrEnum):
    amount = "amount"      # fixed money value, e.g. 10 EUR
    percent = "percent"    # relative discount, e.g. -20%
    other = "other"        # anything unquantified: "1+1", free shipping


class EventKind(StrEnum):
    created = "created"
    published = "published"
    updated = "updated"
    balance_updated = "balance_updated"
    used = "used"
    unused = "unused"
    archived = "archived"
    restored = "restored"
    commented = "commented"
    image_replaced = "image_replaced"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Null for a member invited from the server console: they never touched
    # Telegram, so there is no id to store.
    telegram_id: Mapped[int | None] = mapped_column(
        BigInteger, unique=True, index=True, nullable=True
    )
    first_name: Mapped[str] = mapped_column(String(128), default="")
    last_name: Mapped[str] = mapped_column(String(128), default="")
    username: Mapped[str] = mapped_column(String(128), default="")
    # Telegram's language for this member; background jobs need it after the fact.
    language: Mapped[str] = mapped_column(String(8), default="ru")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    @property
    def display_name(self) -> str:
        name = " ".join(p for p in (self.first_name, self.last_name) if p).strip()
        return name or (f"@{self.username}" if self.username else f"#{self.id}")


class Voucher(Base):
    __tablename__ = "vouchers"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[VoucherStatus] = mapped_column(
        String(16), default=VoucherStatus.active, index=True
    )

    merchant: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(256), default="")
    code: Mapped[str] = mapped_column(String(128), default="")

    value_kind: Mapped[ValueKind] = mapped_column(String(16), default=ValueKind.other)
    # Face value of the voucher: the amount printed on it, or the percentage.
    value_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # What is left to spend. Only meaningful for ValueKind.amount, where a gift
    # card is used across several visits; every change is logged as an event.
    balance_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")

    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    # True when valid_until came from the shop's rule rather than from the card,
    # so the app can show it as an estimate instead of stating it as fact.
    expiry_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    # "I do not know whether anything is left on this one." Money under a question
    # mark is counted apart from money you can rely on.
    balance_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    conditions: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Symbology of the barcode found in the image ("Code 128", "Aztec", …), so the
    # scan screen can redraw it. Empty when the picture has no readable code.
    barcode_format: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    used_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Expiry date we already sent a reminder for, so we notify once per voucher.
    reminded_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id], lazy="joined")
    used_by: Mapped[User | None] = relationship(foreign_keys=[used_by_id], lazy="joined")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="voucher", cascade="all, delete-orphan"
    )
    events: Mapped[list["Event"]] = relationship(
        back_populates="voucher", cascade="all, delete-orphan"
    )

    @property
    def image_id(self) -> str | None:
        """Public handle of the image; also its capability URL segment."""
        return self.image_path

    @property
    def is_expired(self) -> bool:
        return self.valid_until is not None and self.valid_until < utcnow().date()

    @property
    def days_left(self) -> int | None:
        if self.valid_until is None:
            return None
        return (self.valid_until - utcnow().date()).days


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    voucher_id: Mapped[int] = mapped_column(
        ForeignKey("vouchers.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    voucher: Mapped[Voucher] = relationship(back_populates="comments")
    author: Mapped[User] = relationship(lazy="joined")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    voucher_id: Mapped[int] = mapped_column(
        ForeignKey("vouchers.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    kind: Mapped[EventKind] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    voucher: Mapped[Voucher] = relationship(back_populates="events")
    actor: Mapped[User | None] = relationship(lazy="joined")


class LoginToken(Base):
    """One-time token behind the login link the bot sends."""

    __tablename__ = "login_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    # SHA-256 of the token: the database never holds anything replayable.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Session(Base):
    """A logged-in browser — the PWA's equivalent of Telegram's initData."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
