from __future__ import annotations

from datetime import date

from sqlalchemy import ColumnElement, and_

from app.models.obligation import ObligationInstance, ObligationStatus

# OVERDUE is never stored. Per the Ticket 3a state-graph decision it is a read-time
# predicate: status in {PENDING, IN_PROGRESS} AND submission_due_date <
# today_in_Africa_Johannesburg. Work that is in progress can still be late, so
# IN_PROGRESS counts as overdue exactly like PENDING. Strict less-than — a row whose
# submission_due_date equals today is "due today", not yet overdue. The dashboard
# evaluates this in two contexts (Python per-row badge and SQL WHERE), so we expose
# two co-located functions instead of a hybrid_property whose .expression() half would
# need a class-method shim that obscures the call site. `today` is always a required
# parameter so callers pass today_sast() explicitly — no implicit module-level clock
# state.

_OPEN_STATUSES = (ObligationStatus.PENDING, ObligationStatus.IN_PROGRESS)


def is_overdue(instance: ObligationInstance, today: date) -> bool:
    return instance.status in _OPEN_STATUSES and instance.submission_due_date < today


def overdue_filter(today: date) -> ColumnElement[bool]:
    return and_(
        ObligationInstance.status.in_(_OPEN_STATUSES),
        ObligationInstance.submission_due_date < today,
    )
