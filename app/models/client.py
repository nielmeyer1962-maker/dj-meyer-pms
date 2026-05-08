from __future__ import annotations

import calendar
import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, Integer, SmallInteger, String, event, func
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.extensions import db


class EntityType(enum.Enum):
    INDIVIDUAL = "Individual"
    SOLE_PROP = "Sole Proprietor"
    PTY_LTD = "Pty Ltd"
    CC = "CC"
    TRUST = "Trust"
    PARTNERSHIP = "Partnership"
    NPC = "NPC"


class Client(db.Model):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(200))
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType), nullable=False)
    registration_number: Mapped[str | None] = mapped_column(String(50))
    tax_ref: Mapped[str | None] = mapped_column(String(50))
    vat_number: Mapped[str | None] = mapped_column(String(50))
    paye_number: Mapped[str | None] = mapped_column(String(50))
    year_end_month: Mapped[int | None] = mapped_column(SmallInteger)  # 1–12
    year_end_day: Mapped[int | None] = mapped_column(SmallInteger)    # 1–31
    bbee_applicable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    client_since: Mapped[date | None] = mapped_column(Date)
    # Stored UTC; display in Africa/Johannesburg when shown to users
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Tax registrations held by this client
    has_income_tax: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_vat: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_paye: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_provisional_tax: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_dividends_tax: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    @validates("legal_name")
    def _validate_legal_name(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("legal_name is required and cannot be blank")
        return value

    @validates("year_end_month")
    def _validate_year_end_month(self, key: str, value: int | None) -> int | None:
        if value is not None and not (1 <= value <= 12):
            raise ValueError(f"year_end_month must be 1–12, got {value}")
        return value

    @validates("year_end_day")
    def _validate_year_end_day(self, key: str, value: int | None) -> int | None:
        if value is None:
            return value
        month = self.year_end_month
        if month is None:
            raise ValueError("year_end_day cannot be set without year_end_month")
        # Non-leap year so Feb is capped at 28 — year-ends of Feb 29 are not meaningful
        _, max_day = calendar.monthrange(2001, month)
        if not (1 <= value <= max_day):
            raise ValueError(f"day {value} is invalid for month {month} (max {max_day})")
        return value

    def __repr__(self) -> str:
        return f"<Client {self.id} {self.legal_name!r}>"


# Fires before INSERT and UPDATE to catch month-set-without-day (and vice versa).
# @validates cannot catch this because it fires per-attribute, not across the whole object.
@event.listens_for(Client, "before_insert")
@event.listens_for(Client, "before_update")
def _check_year_end_pairing(mapper, connection, target: Client) -> None:
    if (target.year_end_month is None) != (target.year_end_day is None):
        raise ValueError("year_end_month and year_end_day must both be set or both be None")
