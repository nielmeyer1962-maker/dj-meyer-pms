from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy.orm import selectinload

from app.dashboard.forms import NotesForm, ReassignForm
from app.extensions import db
from app.models.client import Client
from app.models.obligation import ObligationInstance, ObligationStatus
from app.models.staff import Staff
from app.services.obligations.predicates import is_overdue, overdue_filter
from app.services.obligations.transitions import (
    mark_exempt,
    mark_paid,
    mark_submitted,
)
from app.utils.dates import today_sast

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

UNASSIGNED_SENTINEL = "__unassigned__"


def _active_staff() -> list[Staff]:
    return db.session.scalars(
        db.select(Staff).where(Staff.active.is_(True)).order_by(Staff.code)
    ).all()


def _reassign_choices(active_staff: list[Staff]) -> list[tuple[str, str]]:
    """Modal dropdown choices: Unassigned sentinel + every active staff by code."""
    choices: list[tuple[str, str]] = [("", "— Unassigned —")]
    choices.extend((str(s.id), f"{s.code} — {s.full_name}") for s in active_staff)
    return choices


@bp.get("/")
def list_obligations():
    today = today_sast()
    active_staff = _active_staff()

    # --- Filter parsing — raw query-string per locked decision §9. ---
    status_arg = request.args.get("status", "").upper()
    assignee_arg = request.args.get("assignee", "")
    view_arg = request.args.get("view", "")

    stmt = (
        db.select(ObligationInstance)
        .options(
            selectinload(ObligationInstance.client),
            selectinload(ObligationInstance.assignee),
        )
        .join(Client, ObligationInstance.client_id == Client.id)
        .order_by(ObligationInstance.submission_due_date.asc(), Client.legal_name.asc())
    )

    # Status: stored values only. "OVERDUE" is not a valid Status choice — it lives in View.
    if status_arg in ObligationStatus.__members__:
        stmt = stmt.where(ObligationInstance.status == ObligationStatus[status_arg])

    # Assignee: Unassigned sentinel, or an active staff code.
    if assignee_arg == UNASSIGNED_SENTINEL:
        stmt = stmt.where(ObligationInstance.assignee_id.is_(None))
    elif assignee_arg:
        staff_match = next((s for s in active_staff if s.code == assignee_arg), None)
        if staff_match is not None:
            stmt = stmt.where(ObligationInstance.assignee_id == staff_match.id)

    # View: date-scoped derived slices. "All" means no extra clause.
    if view_arg == "this_week":
        stmt = stmt.where(
            ObligationInstance.submission_due_date >= today,
            ObligationInstance.submission_due_date <= today + timedelta(days=7),
        )
    elif view_arg == "next_30":
        stmt = stmt.where(
            ObligationInstance.submission_due_date >= today,
            ObligationInstance.submission_due_date <= today + timedelta(days=30),
        )
    elif view_arg == "overdue":
        stmt = stmt.where(overdue_filter(today))

    instances = db.session.scalars(stmt).all()

    reassign_form = ReassignForm()
    reassign_form.assignee_id.choices = _reassign_choices(active_staff)

    return render_template(
        "dashboard/list.html",
        instances=instances,
        active_staff=active_staff,
        unassigned_sentinel=UNASSIGNED_SENTINEL,
        today=today,
        is_overdue=is_overdue,
        reassign_form=reassign_form,
        # Echo current filter values so the form repaints with the user's selection.
        current_status=status_arg,
        current_assignee=assignee_arg,
        current_view=view_arg,
        statuses=list(ObligationStatus),
    )


@bp.get("/obligations/<int:obligation_id>")
def obligation_detail(obligation_id: int):
    instance = db.get_or_404(
        ObligationInstance,
        obligation_id,
        options=[
            selectinload(ObligationInstance.client),
            selectinload(ObligationInstance.assignee),
        ],
    )
    return render_template(
        "dashboard/detail.html",
        instance=instance,
        today=today_sast(),
        is_overdue=is_overdue,
        notes_form=NotesForm(notes=instance.notes),
    )


@bp.post("/obligations/<int:obligation_id>/notes")
def update_obligation_notes(obligation_id: int):
    instance = db.get_or_404(
        ObligationInstance,
        obligation_id,
        options=[
            selectinload(ObligationInstance.client),
            selectinload(ObligationInstance.assignee),
        ],
    )
    form = NotesForm()
    if not form.validate_on_submit():
        # Re-render so the user keeps their typed text + sees inline errors.
        return render_template(
            "dashboard/detail.html",
            instance=instance,
            today=today_sast(),
            is_overdue=is_overdue,
            notes_form=form,
        )
    raw = (form.notes.data or "").strip()
    instance.notes = raw if raw else None
    db.session.commit()
    flash(f"Obligation {instance.id} notes updated.", "success")
    return redirect(url_for("dashboard.obligation_detail", obligation_id=instance.id))


# --- Per-row action handlers. Each follows the same shape:
#     get-or-404 → call B1 → ValueError flash / success commit-and-flash →
#     redirect preserving request.args (locked decision §11). ---


def _redirect_to_list_preserving_filters():
    return redirect(url_for("dashboard.list_obligations", **request.args))


def _apply_transition(obligation_id: int, action) -> None:
    instance = db.get_or_404(ObligationInstance, obligation_id)
    try:
        action(instance)
    except ValueError as exc:
        flash(str(exc), "danger")
        return
    db.session.commit()
    flash(f"Obligation {instance.id} → {instance.status.name}.", "success")


@bp.post("/obligations/<int:obligation_id>/mark-submitted")
def mark_obligation_submitted(obligation_id: int):
    _apply_transition(obligation_id, mark_submitted)
    return _redirect_to_list_preserving_filters()


@bp.post("/obligations/<int:obligation_id>/mark-paid")
def mark_obligation_paid(obligation_id: int):
    _apply_transition(obligation_id, mark_paid)
    return _redirect_to_list_preserving_filters()


@bp.post("/obligations/<int:obligation_id>/mark-exempt")
def mark_obligation_exempt(obligation_id: int):
    _apply_transition(obligation_id, mark_exempt)
    return _redirect_to_list_preserving_filters()


@bp.post("/obligations/<int:obligation_id>/reassign")
def reassign_obligation(obligation_id: int):
    instance = db.get_or_404(ObligationInstance, obligation_id)
    raw = request.form.get("assignee_id", "")
    if raw == "":
        instance.assignee_id = None
    else:
        # Validate against the live staff table — must be an existing AND active
        # staff member. Inactive staff are hard-excluded from reassignment via
        # the API, not only from the dropdown.
        try:
            staff_id = int(raw)
        except ValueError:
            abort(400)
        staff = db.session.get(Staff, staff_id)
        if staff is None or not staff.active:
            abort(400)
        instance.assignee_id = staff.id
    db.session.commit()
    flash(f"Obligation {instance.id} reassigned.", "success")
    return _redirect_to_list_preserving_filters()
