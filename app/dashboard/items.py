"""DashboardItem — the presentation-layer adapter that maps the two unrelated domain
models (ObligationInstance and CIPCAnnualInstance) onto one uniform dashboard row.

This is the seam the deadline dashboard renders through: the list/detail templates know
only DashboardItem, never the underlying models. It is deliberately dashboard-local
(nothing else consumes it) and Flask-free (no url_for / request), so it is a pure,
fully-unit-tested mapping.

Field bridging: obligations carry submission_due_date + a reporting period; the CIPC AR
carries a single due_date and no period. Both collapse to DashboardItem.due_date and a
display-only period_label.

Open / overdue are NOT recomputed here — they are delegated to the domain predicate
modules (services/obligations/predicates, services/cipc/predicates) so the dashboard and
the rest of the app can never disagree about what "overdue" means.

Actions are the per-status list of transition buttons. The Action.key is a semantic
transition name; mapping a key to a concrete Flask route endpoint is the template's job
(chunks 4/5), keeping this module endpoint-agnostic. Reassign is modelled separately via
`reassignable` because it is a modal + dropdown, not a one-click POST.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
from app.models.client import Client
from app.models.obligation import ObligationInstance, ObligationStatus
from app.models.staff import Staff
from app.services.cipc import predicates as cipc_predicates
from app.services.cipc.transitions import _DECLINABLE_FROM as _CIPC_DECLINABLE_FROM
from app.services.obligations import predicates as obligation_predicates

KIND_OBLIGATION = "obligation"
KIND_CIPC = "cipc"

CIPC_TYPE_LABEL = "CIPC AR"
# CIPC AR has no reporting period; the period column shows this placeholder.
_NO_PERIOD = "—"

# Obligation statuses that are finished work: no more transitions, not reassignable.
_OBLIGATION_TERMINAL = (ObligationStatus.PAID, ObligationStatus.EXEMPT)


@dataclass(frozen=True)
class Action:
    """One transition button on a dashboard row.

    key:   semantic transition name (e.g. "mark_submitted"); the template maps it to a
           route endpoint, keeping this module Flask-free.
    label: button text.
    style: Bootstrap variant suffix used as btn-outline-<style>.
    """

    key: str
    label: str
    style: str


@dataclass(frozen=True)
class DashboardItem:
    """One uniform dashboard row, mapped from either domain model."""

    kind: str  # KIND_OBLIGATION | KIND_CIPC — drives which routes the template builds
    id: int
    client: Client | None
    type_label: str  # "VAT201" / "EMP201" / "CIPC AR"
    period_label: str  # obligations: period_end ISO; CIPC: "—"
    due_date: date
    status_name: str
    assignee: Staff | None
    is_overdue: bool
    is_open: bool
    notes: str | None
    actions: tuple[Action, ...]
    reassignable: bool


# --- Per-status action lists. These mirror the transition state graphs; a status with no
#     legal transitions (terminal) maps to an empty tuple. ---

_OBLIGATION_ACTIONS: dict[ObligationStatus, tuple[Action, ...]] = {
    ObligationStatus.PENDING: (
        Action("mark_in_progress", "Start", "info"),
        Action("mark_submitted", "Mark submitted", "primary"),
        Action("mark_exempt", "Mark exempt", "warning"),
    ),
    ObligationStatus.IN_PROGRESS: (
        Action("mark_submitted", "Mark submitted", "primary"),
        Action("revert_to_pending", "Revert to pending", "secondary"),
        Action("mark_exempt", "Mark exempt", "warning"),
    ),
    ObligationStatus.SUBMITTED: (
        Action("mark_paid", "Mark paid", "success"),
        Action("mark_exempt", "Mark exempt", "warning"),
    ),
    ObligationStatus.PAID: (),
    ObligationStatus.EXEMPT: (),
}

# The single forward transition offered from each CIPC status (its successor edge).
# Statuses absent from this map (CLOSED, DECLINED) have no forward transition.
_CIPC_ADVANCE: dict[CIPCAnnualStatus, Action] = {
    CIPCAnnualStatus.GENERATED: Action("mark_invoiced", "Mark invoiced", "primary"),
    CIPCAnnualStatus.INVOICED: Action("mark_invoice_paid", "Mark invoice paid", "success"),
    CIPCAnnualStatus.INVOICE_PAID: Action("mark_bo_submitted", "Mark BO submitted", "primary"),
    CIPCAnnualStatus.BO_SUBMITTED: Action("mark_ar_submitted", "Mark AR submitted", "primary"),
    CIPCAnnualStatus.AR_SUBMITTED: Action("mark_closed", "Mark closed", "success"),
}

# "Service declined" off-ramp — offered exactly on the pre-filing states. Sourced from the
# transitions module so the button set can never drift from what mark_declined accepts.
_CIPC_DECLINE = Action("mark_declined", "Service declined", "danger")


def from_obligation(instance: ObligationInstance, today: date) -> DashboardItem:
    """Map an ObligationInstance to a DashboardItem. `today` drives the overdue badge."""
    status = instance.status
    non_terminal = status not in _OBLIGATION_TERMINAL
    return DashboardItem(
        kind=KIND_OBLIGATION,
        id=instance.id,
        client=instance.client,
        type_label=instance.obligation_type.name,
        period_label=instance.period_end.isoformat(),
        due_date=instance.submission_due_date,
        status_name=status.name,
        assignee=instance.assignee,
        is_overdue=obligation_predicates.is_overdue(instance, today),
        is_open=non_terminal,
        notes=instance.notes,
        actions=_OBLIGATION_ACTIONS[status],
        reassignable=non_terminal,
    )


def from_cipc(instance: CIPCAnnualInstance, today: date) -> DashboardItem:
    """Map a CIPCAnnualInstance to a DashboardItem. `today` drives the overdue badge."""
    status = instance.status
    actions: list[Action] = []
    advance = _CIPC_ADVANCE.get(status)
    if advance is not None:
        actions.append(advance)
    if status in _CIPC_DECLINABLE_FROM:
        actions.append(_CIPC_DECLINE)
    return DashboardItem(
        kind=KIND_CIPC,
        id=instance.id,
        client=instance.client,
        type_label=CIPC_TYPE_LABEL,
        period_label=_NO_PERIOD,
        due_date=instance.due_date,
        status_name=status.name,
        assignee=instance.assignee,
        is_overdue=cipc_predicates.is_overdue(instance, today),
        is_open=cipc_predicates.is_open(instance),
        notes=instance.notes,
        actions=tuple(actions),
        reassignable=cipc_predicates.is_open(instance),
    )
