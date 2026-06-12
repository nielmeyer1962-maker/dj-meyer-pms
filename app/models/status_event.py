"""Audit trail: one row per obligation/CIPC status change or reassignment.

Deliberately decoupled from the two domain instance tables — it stores (kind,
instance_id) rather than two nullable FKs, so a single table records events for both
ObligationInstance and CIPCAnnualInstance without a column per type. from_value/to_value
hold status names or staff codes (or "unassigned") as plain strings, captured at the
moment of the change so later renames/deletes can't rewrite history.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.staff import Staff

# kind values — which domain table instance_id points at.
KIND_OBLIGATION = "OBLIGATION"
KIND_CIPC = "CIPC"
# event values — what kind of change.
EVENT_TRANSITION = "TRANSITION"
EVENT_REASSIGN = "REASSIGN"


class StatusEvent(db.Model):
    __tablename__ = "status_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # OBLIGATION | CIPC
    instance_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event: Mapped[str] = mapped_column(String(20), nullable=False)  # TRANSITION | REASSIGN
    from_value: Mapped[str | None] = mapped_column(String(50))
    to_value: Mapped[str | None] = mapped_column(String(50))
    # The staff member who made the change. SET NULL on staff hard-delete so history
    # survives offboarding (renders as "—" with no actor).
    actor_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id", ondelete="SET NULL"))
    # Stored UTC; display in Africa/Johannesburg.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Read-only convenience for the history view; "—" when the actor was deleted.
    actor: Mapped[Staff | None] = relationship("Staff", lazy="select")

    __table_args__ = (Index("ix_status_events_kind_instance", "kind", "instance_id"),)

    def __repr__(self) -> str:
        return (
            f"<StatusEvent {self.kind}#{self.instance_id} {self.event} "
            f"{self.from_value!r}->{self.to_value!r} actor={self.actor_staff_id}>"
        )
