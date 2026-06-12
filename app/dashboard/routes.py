from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import selectinload

from app.dashboard.forms import NotesForm, ReassignForm
from app.dashboard.items import CIPC_TYPE_LABEL, from_cipc, from_obligation
from app.extensions import db
from app.models.cipc import CIPCAnnualInstance
from app.models.client import Client
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.models.staff import Staff
from app.models.status_event import (
    EVENT_REASSIGN,
    EVENT_TRANSITION,
    KIND_CIPC,
    KIND_OBLIGATION,
    StatusEvent,
)
from app.services.cipc.predicates import overdue_filter as cipc_overdue_filter
from app.services.cipc.transitions import (
    mark_ar_submitted as cipc_mark_ar_submitted,
)
from app.services.cipc.transitions import (
    mark_bo_submitted as cipc_mark_bo_submitted,
)
from app.services.cipc.transitions import (
    mark_closed as cipc_mark_closed,
)
from app.services.cipc.transitions import (
    mark_declined as cipc_mark_declined,
)
from app.services.cipc.transitions import (
    mark_invoice_paid as cipc_mark_invoice_paid,
)
from app.services.cipc.transitions import (
    mark_invoiced as cipc_mark_invoiced,
)
from app.services.obligations.predicates import is_overdue, overdue_filter
from app.services.obligations.transitions import (
    mark_exempt,
    mark_in_progress,
    mark_paid,
    mark_submitted,
    revert_to_pending,
)
from app.utils.dates import to_sast, today_sast
from app.utils.staff import UNASSIGNED_SENTINEL, get_active_staff

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

# Maps a DashboardItem.Action.key to the Flask endpoint that performs it, one map per
# DashboardItem.kind. Lives here (the presentation wiring) rather than in the Flask-free
# adapter; the list template resolves each action button through the map for its kind.
_OBLIGATION_ACTION_ENDPOINTS = {
    "mark_in_progress": "dashboard.mark_obligation_in_progress",
    "mark_submitted": "dashboard.mark_obligation_submitted",
    "revert_to_pending": "dashboard.revert_obligation_to_pending",
    "mark_exempt": "dashboard.mark_obligation_exempt",
    "mark_paid": "dashboard.mark_obligation_paid",
}
_CIPC_ACTION_ENDPOINTS = {
    "mark_invoiced": "dashboard.mark_cipc_invoiced",
    "mark_invoice_paid": "dashboard.mark_cipc_invoice_paid",
    "mark_bo_submitted": "dashboard.mark_cipc_bo_submitted",
    "mark_ar_submitted": "dashboard.mark_cipc_ar_submitted",
    "mark_closed": "dashboard.mark_cipc_closed",
    "mark_declined": "dashboard.mark_cipc_declined",
}

# The Type filter spans both row kinds: the ObligationType names narrow obligations, and
# this sentinel selects the CIPC Annual Return (which has no ObligationType).
_CIPC_TYPE_ARG = "CIPC_AR"


def _reassign_choices(active_staff: list[Staff]) -> list[tuple[str, str]]:
    """Modal dropdown choices: Unassigned sentinel + every active staff by code."""
    choices: list[tuple[str, str]] = [("", "— Unassigned —")]
    choices.extend((str(s.id), f"{s.code} — {s.full_name}") for s in active_staff)
    return choices


@bp.get("/")
def list_obligations():
    today = today_sast()
    active_staff = get_active_staff()

    # --- Filter parsing — raw query-string per locked decision §9. ---
    status_arg = request.args.get("status", "").upper()
    assignee_arg = request.args.get("assignee", "")
    view_arg = request.args.get("view", "")
    type_arg = request.args.get("type", "")
    client_arg = request.args.get("client", "")

    # Client dropdown lists active clients only; the filter narrows both row kinds to one.
    all_clients = db.session.scalars(
        db.select(Client).where(Client.active.is_(True)).order_by(Client.legal_name)
    ).all()
    client_id_filter = next(
        (cl.id for cl in all_clients if str(cl.id) == client_arg),
        None,
    )

    stmt = (
        db.select(ObligationInstance)
        .options(
            selectinload(ObligationInstance.client),
            selectinload(ObligationInstance.assignee),
        )
        .join(Client, ObligationInstance.client_id == Client.id)
        .where(Client.active.is_(True))
        .order_by(ObligationInstance.submission_due_date.asc(), Client.legal_name.asc())
    )

    # Status: stored values only. "OVERDUE" is not a valid Status choice — it lives in View.
    if status_arg in ObligationStatus.__members__:
        stmt = stmt.where(ObligationInstance.status == ObligationStatus[status_arg])

    # Type: an ObligationType name narrows obligations to that type.
    if type_arg in ObligationType.__members__:
        stmt = stmt.where(ObligationInstance.obligation_type == ObligationType[type_arg])

    # Client: narrow to a single client (applies to both row kinds).
    if client_id_filter is not None:
        stmt = stmt.where(ObligationInstance.client_id == client_id_filter)

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

    # Map each ObligationInstance to the uniform DashboardItem the template renders. The
    # query (filters, ordering, selectinload) is unchanged — only the row shape is.
    # Obligations are dropped entirely when the Type filter selects the CIPC AR.
    if type_arg == "" or type_arg in ObligationType.__members__:
        items = [from_obligation(oi, today) for oi in db.session.scalars(stmt).all()]
    else:
        items = []

    # Fold the CIPC Annual Returns into the same list. CIPC visibility is governed by the
    # Type filter ALONE: included when Type is unset/All or the CIPC AR sentinel, excluded
    # only when Type names a specific ObligationType (VAT201/EMP201). The Status filter
    # narrows the obligation query only and never includes or excludes CIPC, so a
    # type=CIPC AR view is never blanked by a stray Status value. Assignee + View filters
    # apply to both, via the CIPC column equivalents (due_date, overdue predicate).
    if type_arg in ("", _CIPC_TYPE_ARG):
        cipc_stmt = (
            db.select(CIPCAnnualInstance)
            .options(
                selectinload(CIPCAnnualInstance.client),
                selectinload(CIPCAnnualInstance.assignee),
            )
            .join(Client, CIPCAnnualInstance.client_id == Client.id)
            .where(Client.active.is_(True))
        )
        if client_id_filter is not None:
            cipc_stmt = cipc_stmt.where(CIPCAnnualInstance.client_id == client_id_filter)
        if assignee_arg == UNASSIGNED_SENTINEL:
            cipc_stmt = cipc_stmt.where(CIPCAnnualInstance.assignee_id.is_(None))
        elif assignee_arg:
            staff_match = next((s for s in active_staff if s.code == assignee_arg), None)
            if staff_match is not None:
                cipc_stmt = cipc_stmt.where(CIPCAnnualInstance.assignee_id == staff_match.id)

        if view_arg == "this_week":
            cipc_stmt = cipc_stmt.where(
                CIPCAnnualInstance.due_date >= today,
                CIPCAnnualInstance.due_date <= today + timedelta(days=7),
            )
        elif view_arg == "next_30":
            cipc_stmt = cipc_stmt.where(
                CIPCAnnualInstance.due_date >= today,
                CIPCAnnualInstance.due_date <= today + timedelta(days=30),
            )
        elif view_arg == "overdue":
            cipc_stmt = cipc_stmt.where(cipc_overdue_filter(today))

        items.extend(from_cipc(ci, today) for ci in db.session.scalars(cipc_stmt).all())

    # Merge-sort the two row sources by due date, then client name — the same ordering the
    # obligation-only list used before CIPC was folded in.
    items.sort(key=lambda it: (it.due_date, it.client.legal_name if it.client else ""))

    reassign_form = ReassignForm()
    reassign_form.assignee_id.choices = _reassign_choices(active_staff)

    return render_template(
        "dashboard/list.html",
        items=items,
        obligation_action_endpoints=_OBLIGATION_ACTION_ENDPOINTS,
        cipc_action_endpoints=_CIPC_ACTION_ENDPOINTS,
        active_staff=active_staff,
        unassigned_sentinel=UNASSIGNED_SENTINEL,
        reassign_form=reassign_form,
        # Echo current filter values so the form repaints with the user's selection.
        current_status=status_arg,
        current_assignee=assignee_arg,
        current_view=view_arg,
        current_type=type_arg,
        current_client=client_arg,
        clients=all_clients,
        statuses=list(ObligationStatus),
        # Type choices span both kinds: each ObligationType, plus the CIPC AR sentinel.
        type_choices=[(t.name, t.name) for t in ObligationType]
        + [(_CIPC_TYPE_ARG, CIPC_TYPE_LABEL)],
    )


def _describe_event(e: StatusEvent) -> str:
    verb = "Status" if e.event == EVENT_TRANSITION else "Reassigned"
    return f"{verb}: {e.from_value} → {e.to_value}"


def _obligation_history(instance_id: int) -> list[dict]:
    """This obligation's audit events, newest first, as display-ready rows."""
    events = db.session.scalars(
        db.select(StatusEvent)
        .options(selectinload(StatusEvent.actor))
        .where(StatusEvent.kind == KIND_OBLIGATION, StatusEvent.instance_id == instance_id)
        .order_by(StatusEvent.created_at.desc(), StatusEvent.id.desc())
    ).all()
    return [
        {
            "when": to_sast(e.created_at).strftime("%Y-%m-%d %H:%M"),
            "actor": e.actor.full_name if e.actor else "—",
            "description": _describe_event(e),
        }
        for e in events
    ]


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
    today = today_sast()
    active_staff = get_active_staff()
    reassign_form = ReassignForm(assignee_id=str(instance.assignee_id or ""))
    reassign_form.assignee_id.choices = _reassign_choices(active_staff)
    return render_template(
        "dashboard/detail.html",
        instance=instance,
        # The action set + reassignable gating render through the same DashboardItem
        # adapter as the list page, so file-only types (ITR14) are terminal at SUBMITTED
        # instead of being offered "Mark paid". Display fields stay on `instance` because
        # the detail page shows period_start / payment_due_date, which the item omits.
        item=from_obligation(instance, today),
        obligation_action_endpoints=_OBLIGATION_ACTION_ENDPOINTS,
        today=today,
        is_overdue=is_overdue,
        notes_form=NotesForm(notes=instance.notes),
        reassign_form=reassign_form,
        history=_obligation_history(instance.id),
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
        today = today_sast()
        active_staff = get_active_staff()
        reassign_form = ReassignForm(assignee_id=str(instance.assignee_id or ""))
        reassign_form.assignee_id.choices = _reassign_choices(active_staff)
        return render_template(
            "dashboard/detail.html",
            instance=instance,
            item=from_obligation(instance, today),
            obligation_action_endpoints=_OBLIGATION_ACTION_ENDPOINTS,
            today=today,
            is_overdue=is_overdue,
            notes_form=form,
            reassign_form=reassign_form,
            history=_obligation_history(instance.id),
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


def _redirect_after_action(instance_id: int):
    """Honor the hidden `next` field: detail-page forms set next=detail to bounce
    back to /dashboard/obligations/<id>; list-page forms omit it and fall through
    to the filter-preserving list redirect (locked decision §11)."""
    if request.form.get("next") == "detail":
        return redirect(url_for("dashboard.obligation_detail", obligation_id=instance_id))
    return _redirect_to_list_preserving_filters()


def _stage_status_event(
    kind: str, instance_id: int, event: str, from_value: str | None, to_value: str | None
) -> None:
    """Stage (don't commit) an audit row so it commits in the SAME transaction as the
    change it records — the event and the change are atomic. The caller commits once."""
    actor_id = current_user.id if current_user.is_authenticated else None
    db.session.add(
        StatusEvent(
            kind=kind,
            instance_id=instance_id,
            event=event,
            from_value=from_value,
            to_value=to_value,
            actor_staff_id=actor_id,
        )
    )


def _apply_transition(obligation_id: int, action) -> None:
    instance = db.get_or_404(ObligationInstance, obligation_id)
    from_status = instance.status.name
    try:
        action(instance)
    except ValueError as exc:
        # Refused transition: roll back any partial mutation and write NO event.
        db.session.rollback()
        flash(str(exc), "danger")
        return
    _stage_status_event(
        KIND_OBLIGATION, instance.id, EVENT_TRANSITION, from_status, instance.status.name
    )
    db.session.commit()
    flash(f"Obligation {instance.id} → {instance.status.name}.", "success")


@bp.post("/obligations/<int:obligation_id>/mark-in-progress")
def mark_obligation_in_progress(obligation_id: int):
    _apply_transition(obligation_id, mark_in_progress)
    return _redirect_after_action(obligation_id)


@bp.post("/obligations/<int:obligation_id>/revert-to-pending")
def revert_obligation_to_pending(obligation_id: int):
    _apply_transition(obligation_id, revert_to_pending)
    return _redirect_after_action(obligation_id)


@bp.post("/obligations/<int:obligation_id>/mark-submitted")
def mark_obligation_submitted(obligation_id: int):
    _apply_transition(obligation_id, mark_submitted)
    return _redirect_after_action(obligation_id)


@bp.post("/obligations/<int:obligation_id>/mark-paid")
def mark_obligation_paid(obligation_id: int):
    _apply_transition(obligation_id, mark_paid)
    return _redirect_after_action(obligation_id)


@bp.post("/obligations/<int:obligation_id>/mark-exempt")
def mark_obligation_exempt(obligation_id: int):
    _apply_transition(obligation_id, mark_exempt)
    return _redirect_after_action(obligation_id)


def _parse_assignee_id(raw: str) -> int | None:
    """Resolve a reassign form value to a staff id, or None for Unassigned. Validates
    against the live staff table — must be an existing AND active staff member; inactive
    or unknown ids abort(400). Inactive staff are hard-excluded from reassignment via the
    API, not only from the dropdown."""
    if raw == "":
        return None
    try:
        staff_id = int(raw)
    except ValueError:
        abort(400)
    staff = db.session.get(Staff, staff_id)
    if staff is None or not staff.active:
        abort(400)
    return staff.id


def _assignee_code(staff_id: int | None) -> str:
    """The staff code for an assignee id, or 'unassigned' for None."""
    if staff_id is None:
        return "unassigned"
    staff = db.session.get(Staff, staff_id)
    return staff.code if staff is not None else "unassigned"


@bp.post("/obligations/<int:obligation_id>/reassign")
def reassign_obligation(obligation_id: int):
    instance = db.get_or_404(ObligationInstance, obligation_id)
    from_code = _assignee_code(instance.assignee_id)
    # _parse_assignee_id aborts(400) on an invalid target — before any event/commit, so a
    # rejected reassign writes nothing.
    new_id = _parse_assignee_id(request.form.get("assignee_id", ""))
    instance.assignee_id = new_id
    _stage_status_event(
        KIND_OBLIGATION, instance.id, EVENT_REASSIGN, from_code, _assignee_code(new_id)
    )
    db.session.commit()
    flash(f"Obligation {instance.id} reassigned.", "success")
    return _redirect_after_action(obligation_id)


# --- CIPC Annual Return action handlers. Same shape as the obligation handlers, but the
#     CIPC AR has no detail page, so every action redirects to the filter-preserving list.
#     mark_declined is the "Service declined" off-ramp. ---


def _apply_cipc_transition(cipc_id: int, action) -> None:
    instance = db.get_or_404(CIPCAnnualInstance, cipc_id)
    from_status = instance.status.name
    try:
        action(instance)
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return
    _stage_status_event(KIND_CIPC, instance.id, EVENT_TRANSITION, from_status, instance.status.name)
    db.session.commit()
    flash(f"CIPC AR {instance.id} → {instance.status.name}.", "success")


@bp.post("/cipc/<int:cipc_id>/mark-invoiced")
def mark_cipc_invoiced(cipc_id: int):
    _apply_cipc_transition(cipc_id, cipc_mark_invoiced)
    return _redirect_to_list_preserving_filters()


@bp.post("/cipc/<int:cipc_id>/mark-invoice-paid")
def mark_cipc_invoice_paid(cipc_id: int):
    _apply_cipc_transition(cipc_id, cipc_mark_invoice_paid)
    return _redirect_to_list_preserving_filters()


@bp.post("/cipc/<int:cipc_id>/mark-bo-submitted")
def mark_cipc_bo_submitted(cipc_id: int):
    _apply_cipc_transition(cipc_id, cipc_mark_bo_submitted)
    return _redirect_to_list_preserving_filters()


@bp.post("/cipc/<int:cipc_id>/mark-ar-submitted")
def mark_cipc_ar_submitted(cipc_id: int):
    _apply_cipc_transition(cipc_id, cipc_mark_ar_submitted)
    return _redirect_to_list_preserving_filters()


@bp.post("/cipc/<int:cipc_id>/mark-closed")
def mark_cipc_closed(cipc_id: int):
    _apply_cipc_transition(cipc_id, cipc_mark_closed)
    return _redirect_to_list_preserving_filters()


@bp.post("/cipc/<int:cipc_id>/mark-declined")
def mark_cipc_declined(cipc_id: int):
    _apply_cipc_transition(cipc_id, cipc_mark_declined)
    return _redirect_to_list_preserving_filters()


@bp.post("/cipc/<int:cipc_id>/reassign")
def reassign_cipc(cipc_id: int):
    instance = db.get_or_404(CIPCAnnualInstance, cipc_id)
    from_code = _assignee_code(instance.assignee_id)
    new_id = _parse_assignee_id(request.form.get("assignee_id", ""))
    instance.assignee_id = new_id
    _stage_status_event(KIND_CIPC, instance.id, EVENT_REASSIGN, from_code, _assignee_code(new_id))
    db.session.commit()
    flash(f"CIPC AR {instance.id} reassigned.", "success")
    return _redirect_to_list_preserving_filters()
