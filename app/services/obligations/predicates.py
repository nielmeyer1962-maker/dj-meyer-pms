from __future__ import annotations

from datetime import date

from sqlalchemy import ColumnElement, and_

from app.models.obligation import ObligationInstance, ObligationStatus

# OVERDUE is never stored. Per the Ticket 3a state-graph decision it is a read-time
# predicate: PENDING AND submission_due_date < today_in_Africa_Johannesburg. Strict
# less-than — a row whose submission_due_date equals today is "due today", not yet
# overdue. The dashboard evaluates this in two contexts (Python per-row badge and
# SQL WHERE), so we expose two co-located functions instead of a hybrid_property
# whose .expression() half would need a class-method shim that obscures the call
# site. `today` is always a required parameter so callers pass today_sast()
# explicitly — no implicit module-level clock state.


def is_overdue(instance: ObligationInstance, today: date) -> bool:
    return instance.status is ObligationStatus.PENDING and instance.submission_due_date < today


def overdue_filter(today: date) -> ColumnElement[bool]:
    return and_(
        ObligationInstance.status == ObligationStatus.PENDING,
        ObligationInstance.submission_due_date < today,
    )
