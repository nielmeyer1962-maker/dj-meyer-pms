from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.client import Client
from app.models.staff import Staff
from app.models.task import Task, TaskStatus
from app.services.tasks.predicates import is_overdue, overdue_filter
from app.tasks.forms import TaskForm
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


@bp.get("/<int:task_id>")
def task_detail(task_id: int):
    # selectinload client + assignee to mirror obligation_detail and avoid a
    # lazy second round-trip when the template reads the relationships.
    task = db.get_or_404(
        Task,
        task_id,
        options=[
            selectinload(Task.client),
            selectinload(Task.assignee),
        ],
    )
    return render_template(
        "tasks/detail.html",
        task=task,
        today=today_sast(),
        is_overdue=is_overdue,
    )


def _active_clients() -> list[Client]:
    """Active clients, ordered by legal_name — the live list the task form's
    client_id select is validated against (mirrors get_active_staff)."""
    return db.session.scalars(
        db.select(Client).where(Client.active.is_(True)).order_by(Client.legal_name)
    ).all()


def _populate_task_form_choices(
    form: TaskForm, active_clients: list[Client], active_staff: list[Staff]
) -> None:
    """Inject per-request choices for the two SelectFields. Both carry
    validate_choice=False; membership is enforced in the route by
    _assignment_targets_valid against these same live lists."""
    form.client_id.choices = [
        (
            str(c.id),
            c.legal_name if not c.trading_name else f"{c.legal_name} ({c.trading_name})",
        )
        for c in active_clients
    ]
    form.assignee_id.choices = [("", "— Unassigned —")] + [
        (str(s.id), f"{s.code} — {s.full_name}") for s in active_staff
    ]


def _assignment_targets_valid(
    form: TaskForm, active_clients: list[Client], active_staff: list[Staff]
) -> bool:
    """Reject a client_id/assignee_id not in the current active lists. Attaches
    field-level errors so they render inline like any other validation error."""
    ok = True
    if form.client_id.data not in {str(c.id) for c in active_clients}:
        form.client_id.errors.append("Select a current client.")
        ok = False
    if form.assignee_id.data and form.assignee_id.data not in {str(s.id) for s in active_staff}:
        form.assignee_id.errors.append("Select a current staff member.")
        ok = False
    return ok


@bp.route("/new", methods=["GET", "POST"])
def task_new():
    form = TaskForm()
    active_clients = _active_clients()
    active_staff = get_active_staff()
    _populate_task_form_choices(form, active_clients, active_staff)

    if form.validate_on_submit() and _assignment_targets_valid(form, active_clients, active_staff):
        task = Task(
            client_id=int(form.client_id.data),
            title=form.title.data,
            due_date=form.due_date.data,
            description=form.description.data or None,
            assignee_id=int(form.assignee_id.data) if form.assignee_id.data else None,
            notes=form.notes.data or None,
            requested_by=form.requested_by.data or None,
        )
        db.session.add(task)
        db.session.commit()
        flash(f"Task created: {task.title}", "success")
        return redirect(url_for("tasks.task_detail", task_id=task.id))

    return render_template(
        "tasks/form.html",
        form=form,
        title="New task",
        cancel_url=url_for("tasks.list_tasks"),
    )


@bp.route("/<int:task_id>/edit", methods=["GET", "POST"])
def task_edit(task_id: int):
    task = db.get_or_404(Task, task_id)
    form = TaskForm(obj=task)
    active_clients = _active_clients()
    active_staff = get_active_staff()
    _populate_task_form_choices(form, active_clients, active_staff)

    if request.method == "GET":
        # SelectField matches its string choice values, not the int FK columns
        # that obj= copied in (mirrors edit_client's enum-name coercion).
        form.client_id.data = str(task.client_id)
        form.assignee_id.data = str(task.assignee_id) if task.assignee_id else ""

    if form.validate_on_submit() and _assignment_targets_valid(form, active_clients, active_staff):
        task.client_id = int(form.client_id.data)
        task.title = form.title.data
        task.due_date = form.due_date.data
        task.description = form.description.data or None
        task.assignee_id = int(form.assignee_id.data) if form.assignee_id.data else None
        task.notes = form.notes.data or None
        task.requested_by = form.requested_by.data or None
        db.session.commit()
        flash(f"Task updated: {task.title}", "success")
        return redirect(url_for("tasks.task_detail", task_id=task.id))

    return render_template(
        "tasks/form.html",
        form=form,
        title="Edit task",
        cancel_url=url_for("tasks.task_detail", task_id=task.id),
    )
