from __future__ import annotations

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.staff import Staff


class CIPCAnnualStatus(enum.Enum):
    """Ordered six-state workflow for a CIPC Annual Return (Ticket 4g).

    GENERATED → INVOICED → INVOICE_PAID → BO_SUBMITTED → AR_SUBMITTED → CLOSED.

    BO_SUBMITTED precedes AR_SUBMITTED by regulatory mandate: since 15 Apr 2024 CIPC
    blocks Annual Return filing unless the Beneficial Ownership declaration is already
    on file. The state graph is enforced only by the Chunk 4 transitions service, never
    here (mirrors the ObligationInstance / Task convention). No terminal CANCELLED/EXEMPT
    state in this iteration (locked decision: 6 states only)."""

    GENERATED = "GENERATED"
    INVOICED = "INVOICED"
    INVOICE_PAID = "INVOICE_PAID"
    BO_SUBMITTED = "BO_SUBMITTED"
    AR_SUBMITTED = "AR_SUBMITTED"
    CLOSED = "CLOSED"


class CIPCAnnualInstance(db.Model):
    """One CIPC Annual Return obligation occurrence for a client in a given filing year.

    A SEPARATE model from ObligationInstance (Ticket 4g): the CIPC AR has its own
    six-state workflow, an entity-type-dependent deadline, a turnover-banded fee, and a
    BO milestone — none of which fit the shared SARS-return shape. Centralised to Tsego
    (Secretarial), not per-client allocation. Beneficial Ownership is tracked here only
    as the BO_SUBMITTED workflow milestone; the BeneficialOwner data model is Ticket 7.
    """

    __tablename__ = "cipc_annual_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ON DELETE RESTRICT mirrors obligation_instances/tasks: never lose CIPC filing
    # history because of an accidental client delete. Clients are archived via
    # active=False, not deleted.
    client_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # The incorporation anniversary falling in this filing year — drives the company
    # 30-business-day deadline and, with client_id, uniquely identifies the occurrence.
    # Stored as a full date (the client's cipc_anniversary_month/day applied to the
    # filing year); for a CC only the month matters for the deadline, but the date is
    # still well-defined and keeps one row per client per year.
    anniversary_date: Mapped[date] = mapped_column(Date, nullable=False)
    # The computed CIPC AR deadline. Entity-type dependent (Chunk 2): companies (Pty
    # Ltd / INC / NPC) = 30 business days after anniversary_date; CC = last day of the
    # month following the anniversary month. Stored, not derived, so a row's deadline is
    # stable even if the rule or holiday data changes later.
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[CIPCAnnualStatus] = mapped_column(
        Enum(CIPCAnnualStatus),
        nullable=False,
        default=CIPCAnnualStatus.GENERATED,
    )
    # Annual turnover from the client's AFS, captured manually on the instance (drives
    # the turnover-banded fee in Chunk 5). Stored in CENTS as a BigInteger per the
    # money-as-integer rule (turnover runs to billions of cents). Nullable: captured
    # when known. Designed so a future hook can auto-populate it from the ITR14 (Ticket
    # 4a) on submission — that hook is deliberately NOT built now.
    annual_turnover_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Centralised to Tsego at generation. Kept as a nullable FK (not hard-coded) so the
    # dashboard renders uniformly and the row survives staff offboarding: ON DELETE SET
    # NULL mirrors obligations/tasks. Soft delete via Staff.active=False is the routine
    # path.
    assignee_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("staff.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stored UTC; display in Africa/Johannesburg when shown to users.
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
    # query-heavy paths like the CIPC dashboard to avoid N+1.
    client: Mapped[Client] = relationship("Client", lazy="select")
    assignee: Mapped[Staff | None] = relationship("Staff", lazy="select")

    __table_args__ = (
        # Idempotency key: one CIPC AR per client per anniversary occurrence; prevents
        # the generator from creating duplicates when re-run.
        UniqueConstraint(
            "client_id",
            "anniversary_date",
            name="uq_cipc_annual_instances_client_anniversary",
        ),
        # Supports the CIPC dashboard query "what's due / outstanding, soonest first".
        Index(
            "ix_cipc_annual_instances_status_due",
            "status",
            "due_date",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CIPCAnnualInstance {self.id} client={self.client_id} "
            f"anniversary={self.anniversary_date} due={self.due_date} "
            f"status={self.status.name}>"
        )
