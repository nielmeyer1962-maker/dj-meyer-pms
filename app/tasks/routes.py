from __future__ import annotations

from flask import Blueprint, render_template, request
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.task import Task, TaskStatus
from app.services.tasks.predicates import is_overdue, overdue_filter
from app.utils.dates import today_sast
from app.utils.staff import UNASSIGNED_SENTINEL, get_active_staff

bp = Blueprint("tasks", __name__, url_prefix="/dashboard/tasks")


@bp.get("/")
def list_tasks():
    today = today_sast()
    active_staff = get_active_staff()

    # --- Filter parsing — mirrors list_obligations in app/dashboard/routes.py. ---
    status_arg = request.args.get("status", "").upper()
    assignee_arg = request.args.get("assignee", "")
    view_arg = request.args.get("view", "")

    # selectinload client + assignee to avoid N+1 across the row loop, per the
    # Task model's relationship note.
    stmt = (
        db.select(Task)
        .options(
            selectinload(Task.client),
            selectinload(Task.assignee),
        )
        .order_by(Task.due_date.asc())
    )

    # Status: stored values only.
    if status_arg in TaskStatus.__members__:
        stmt = stmt.where(Task.status == TaskStatus[status_arg])

    # Assignee: Unassigned sentinel, or an active staff code.
    if assignee_arg == UNASSIGNED_SENTINEL:
        stmt = stmt.where(Task.assignee_id.is_(None))
    elif assignee_arg:
        staff_match = next((s for s in active_staff if s.code == assignee_arg), None)
        if staff_match is not None:
            stmt = stmt.where(Task.assignee_id == staff_match.id)

    # View: only "overdue" for tasks (no this_week/next_30 — those are obligations-specific).
    if view_arg == "overdue":
        stmt = stmt.where(overdue_filter(today))

    tasks = db.session.scalars(stmt).all()

    return render_template(
        "tasks/list.html",
        tasks=tasks,
        today=today,
        is_overdue=is_overdue,
        active_staff=active_staff,
        statuses=list(TaskStatus),
        unassigned_sentinel=UNASSIGNED_SENTINEL,
        current_status=status_arg,
        current_assignee=assignee_arg,
        current_view=view_arg,
    )
