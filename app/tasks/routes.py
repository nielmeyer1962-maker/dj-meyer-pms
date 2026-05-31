from __future__ import annotations

from flask import Blueprint, render_template
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.task import Task
from app.services.tasks.predicates import is_overdue
from app.utils.dates import today_sast

bp = Blueprint("tasks", __name__, url_prefix="/dashboard/tasks")


@bp.get("/")
def list_tasks():
    # selectinload client + assignee to avoid N+1 across the row loop, per the
    # Task model's relationship note.
    tasks = db.session.scalars(
        db.select(Task)
        .options(
            selectinload(Task.client),
            selectinload(Task.assignee),
        )
        .order_by(Task.due_date.asc())
    ).all()
    return render_template(
        "tasks/list.html",
        tasks=tasks,
        today=today_sast(),
        is_overdue=is_overdue,
    )
