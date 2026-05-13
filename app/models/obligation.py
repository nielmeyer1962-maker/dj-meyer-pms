from __future__ import annotations

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.staff import Staff


class ObligationType(enum.Enum):
    VAT201 = "VAT201"


class ObligationStatus(enum.Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    EXEMPT = "EXEMPT"


class ObligationInstance(db.Model):
    __tablename__ = "obligation_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ON DELETE RESTRICT: never lose submission history because of an accidental
    # client delete. Clients are archived via active=False, not deleted.
    client_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    obligation_type: Mapped[ObligationType] = mapped_column(Enum(ObligationType), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    # For VAT201, submission_due_date == payment_due_date. Kept separate so future
    # obligations (e.g. provisional tax) with distinct dates fit without schema change.
    submission_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    # OVERDUE is derived at read time (status == PENDING AND submission_due_date <
    # today_in_Africa_Johannesburg) — not stored. State graph is enforced only by
    # the Ticket 3b service layer, never here.
    status: Mapped[ObligationStatus] = mapped_column(
        Enum(ObligationStatus),
        nullable=False,
        default=ObligationStatus.PENDING,
    )
    # Nullable so the dashboard can surface "Unassigned" as a first-class filter
    # category — newly-generated obligations for a client whose engagement-rep
    # mapping isn't captured yet show up here. ON DELETE SET NULL because staff
    # offboarding is a normal event: hard-deleting a staff record reverts their
    # open obligations to unassigned rather than blocking the delete (RESTRICT
    # would force manual reassignment first). Soft delete via Staff.active=False
    # is the recommended routine path; SET NULL is the right hard-delete
    # semantics.
    assignee_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("staff.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Stored UTC; display in Africa/Johannesburg when shown to users
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships (Python-only, no FK or schema change). selectinload these in
    # query-heavy paths like the dashboard list to avoid N+1.
    client: Mapped[Client] = relationship("Client", lazy="select")
    assignee: Mapped[Staff | None] = relationship("Staff", lazy="select")

    __table_args__ = (
        # Idempotency key: prevents the generator from creating duplicates when re-run.
        UniqueConstraint(
            "client_id",
            "obligation_type",
            "period_end",
            name="uq_obligation_instances_client_type_period",
        ),
        # Supports the dashboard query "what's due in the next 30 days that is not yet
        # submitted" and the derived OVERDUE read-time predicate.
        Index(
            "ix_obligation_instances_status_submission_due",
            "status",
            "submission_due_date",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ObligationInstance {self.id} {self.obligation_type.name} "
            f"client={self.client_id} period_end={self.period_end} "
            f"status={self.status.name}>"
        )
