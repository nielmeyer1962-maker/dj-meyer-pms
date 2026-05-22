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
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.staff import Staff


class TaskStatus(enum.Enum):
    OPEN = "OPEN"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class Task(db.Model):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ON DELETE RESTRICT mirrors obligation_instances.client_id: never lose task
    # history because of an accidental client delete. Clients are archived via
    # active=False, not deleted.
    client_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # 200-char hard cap at the DB level; form-layer cap matches so over-long
    # input never reaches the database.
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Long-form detail. No DB cap; form-layer soft cap 4000 chars (same as
    # obligation_instances.notes).
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # User-supplied. No business-day calculation — unlike obligations.
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    # OVERDUE is derived at read time (status == OPEN AND due_date <
    # today_in_Africa_Johannesburg) — not stored. State graph is enforced only
    # by the Chunk 2 transitions service, never here.
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus),
        nullable=False,
        default=TaskStatus.OPEN,
    )
    # Nullable so the future task list can surface "Unassigned" as a first-class
    # filter category. ON DELETE SET NULL mirrors obligations: hard-deleting a
    # staff record reverts their open tasks to unassigned rather than blocking
    # the delete. Soft delete via Staff.active=False is the recommended routine
    # path.
    assignee_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("staff.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Free-form operational notes. Form-layer soft cap 4000 chars (same as
    # obligation_instances.notes).
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Free-text "who asked for this" — reception, the client themselves, a
    # partner. Single nullable field; a structured RequestSource enum is
    # deferred until demand surfaces.
    requested_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Stored UTC; display in Africa/Johannesburg when shown to users.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships (Python-only, no FK or schema change). selectinload these in
    # query-heavy paths like the task list to avoid N+1.
    client: Mapped[Client] = relationship("Client", lazy="select")
    assignee: Mapped[Staff | None] = relationship("Staff", lazy="select")

    __table_args__ = (
        # Supports the OVERDUE / "due soon" read-time predicates and the future
        # "OPEN tasks due in the next N days" list query.
        Index("ix_tasks_status_due_date", "status", "due_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<Task {self.id} {self.title!r} client={self.client_id} "
            f"due={self.due_date} status={self.status.name}>"
        )
