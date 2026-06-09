from __future__ import annotations

import calendar
import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db

if TYPE_CHECKING:
    from app.models.staff import Staff


class EntityType(enum.Enum):
    INDIVIDUAL = "Individual"
    SOLE_PROP = "Sole Proprietor"
    PTY_LTD = "Pty Ltd"
    INC = "Inc"
    CC = "CC"
    TRUST = "Trust"
    PARTNERSHIP = "Partnership"
    NPC = "NPC"


class VatCategory(enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class VatSubmissionMethod(enum.Enum):
    EFILING = "EFILING"
    MANUAL = "MANUAL"


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
    # Primary contact details, structured to match the firm's contact export
    # (Main/CC email, multiple phones, street address) for clean letter addressing.
    # All optional. No email shape check yet (matches the Staff.email decision). A
    # separate Contact table for multiple contacts per client is deferred.
    contact_person: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    cc_email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    work_phone: Mapped[str | None] = mapped_column(String(50))
    mobile: Mapped[str | None] = mapped_column(String(50))
    fax: Mapped[str | None] = mapped_column(String(50))
    street1: Mapped[str | None] = mapped_column(String(200))
    street2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    postcode: Mapped[str | None] = mapped_column(String(20))
    year_end_month: Mapped[int | None] = mapped_column(SmallInteger)  # 1–12
    year_end_day: Mapped[int | None] = mapped_column(SmallInteger)  # 1–31
    # CIPC annual-return anniversary (incorporation month/day). Drives the CIPC
    # obligation; only meaningful for PTY_LTD / CC. Month and day travel together.
    cipc_anniversary_month: Mapped[int | None] = mapped_column(SmallInteger)  # 1–12
    cipc_anniversary_day: Mapped[int | None] = mapped_column(SmallInteger)  # 1–31
    bbee_applicable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    client_since: Mapped[date | None] = mapped_column(Date)
    # Stored UTC; display in Africa/Johannesburg when shown to users
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # The tax/accounting staff member who owns this client's work ("Staff Member"
    # in Tsego's roster / "Rep" in QuickBooks). Nullable so an unallocated client
    # is a first-class state. ON DELETE SET NULL mirrors obligations/tasks: staff
    # offboarding reverts their clients to unallocated rather than blocking delete.
    allocated_staff_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("staff.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    allocated_staff: Mapped[Staff | None] = relationship("Staff", lazy="select")

    # Tax registrations held by this client
    has_income_tax: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_vat: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_paye: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_provisional_tax: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_dividends_tax: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # VAT-specific detail. Nullable at the DB level; cross-field invariants
    # (pairing + has_vat consistency) are enforced in _check_pairing_invariants below.
    vat_category: Mapped[VatCategory | None] = mapped_column(Enum(VatCategory))
    vat_submission_method: Mapped[VatSubmissionMethod | None] = mapped_column(
        Enum(VatSubmissionMethod)
    )

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

    @validates("cipc_anniversary_month")
    def _validate_cipc_anniversary_month(self, key: str, value: int | None) -> int | None:
        if value is not None and not (1 <= value <= 12):
            raise ValueError(f"cipc_anniversary_month must be 1–12, got {value}")
        return value

    @validates("cipc_anniversary_day")
    def _validate_cipc_anniversary_day(self, key: str, value: int | None) -> int | None:
        if value is None:
            return value
        month = self.cipc_anniversary_month
        if month is None:
            raise ValueError("cipc_anniversary_day cannot be set without cipc_anniversary_month")
        # Non-leap year so Feb caps at 28 — Feb 29 anniversaries are not meaningful
        _, max_day = calendar.monthrange(2001, month)
        if not (1 <= value <= max_day):
            raise ValueError(f"day {value} is invalid for month {month} (max {max_day})")
        return value

    @validates("vat_category")
    def _validate_vat_category(
        self, key: str, value: VatCategory | str | None
    ) -> VatCategory | None:
        if value is None or isinstance(value, VatCategory):
            return value
        if isinstance(value, str):
            try:
                return VatCategory[value]
            except KeyError as exc:
                valid = [m.name for m in VatCategory]
                raise ValueError(
                    f"vat_category must be one of {valid} or None, got {value!r}"
                ) from exc
        raise ValueError(
            f"vat_category must be a VatCategory member, name string, or None, got {value!r}"
        )

    @validates("vat_submission_method")
    def _validate_vat_submission_method(
        self, key: str, value: VatSubmissionMethod | str | None
    ) -> VatSubmissionMethod | None:
        if value is None or isinstance(value, VatSubmissionMethod):
            return value
        if isinstance(value, str):
            try:
                return VatSubmissionMethod[value]
            except KeyError as exc:
                valid = [m.name for m in VatSubmissionMethod]
                raise ValueError(
                    f"vat_submission_method must be one of {valid} or None, got {value!r}"
                ) from exc
        raise ValueError(
            f"vat_submission_method must be a VatSubmissionMethod member, name string, "
            f"or None, got {value!r}"
        )

    def __repr__(self) -> str:
        return f"<Client {self.id} {self.legal_name!r}>"


# Fires before INSERT and UPDATE. Enforces cross-field invariants that @validates cannot
# catch (it fires per-attribute, not across the whole object).
@event.listens_for(Client, "before_insert")
@event.listens_for(Client, "before_update")
def _check_pairing_invariants(mapper, connection, target: Client) -> None:
    # -------------------- (i) Year-end pairing --------------------
    # year_end_month and year_end_day must travel together — either both set or both None.
    if (target.year_end_month is None) != (target.year_end_day is None):
        raise ValueError("year_end_month and year_end_day must both be set or both be None")

    # -------------------- (ii) has_vat=False forces both VAT fields to None --------------------
    if not target.has_vat and (
        target.vat_category is not None or target.vat_submission_method is not None
    ):
        raise ValueError(
            "vat_category and vat_submission_method must be None when has_vat is False"
        )

    # -------------------- (iii) VAT pairing rule --------------------
    # Independent of has_vat: if one VAT field is set, the other must also be set.
    if (target.vat_category is None) != (target.vat_submission_method is None):
        raise ValueError("vat_category and vat_submission_method must both be set or both be None")

    # -------------------- (iv) CIPC anniversary pairing --------------------
    # month and day travel together — either both set or both None.
    if (target.cipc_anniversary_month is None) != (target.cipc_anniversary_day is None):
        raise ValueError(
            "cipc_anniversary_month and cipc_anniversary_day must both be set or both be None"
        )
