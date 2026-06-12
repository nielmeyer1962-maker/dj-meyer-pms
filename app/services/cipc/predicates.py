from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import ColumnElement, and_, or_

from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus

# Read-time predicates for the CIPC Annual Return, mirroring
# services/obligations/predicates.py: nothing here is stored, every function takes an
# explicit `today` (no implicit module-level clock), and each predicate is exposed in two
# co-located forms — a Python per-row form for the dashboard badge and a SQL form for the
# WHERE clause — so the two never silently diverge.
#
# Two distinctions, per the locked dashboard decision:
#   open    = status NOT IN {CLOSED, DECLINED}.  Both terminal states are "done" work:
#             CLOSED = the AR was filed, DECLINED = the service was never taken up.
#   overdue = due_date < today AND status NOT IN {AR_SUBMITTED, CLOSED, DECLINED}.
#             AR_SUBMITTED is excluded on top of the terminal pair: once the Annual
#             Return is filed the deadline is met even though the row isn't CLOSED yet,
#             so a filed-but-not-closed row is never "overdue".
# Strict less-than — a row due exactly today is "due today", not yet overdue.

# Terminal statuses: a row here is finished and no longer open work on the dashboard.
_TERMINAL_STATUSES = (CIPCAnnualStatus.CLOSED, CIPCAnnualStatus.DECLINED)

# Statuses still in flight for overdue purposes — the pre-filing states. Equivalent to
# the locked rule "NOT IN {AR_SUBMITTED, CLOSED, DECLINED}", expressed positively to
# mirror obligations._OPEN_STATUSES.
_OVERDUE_OPEN_STATUSES = (
    CIPCAnnualStatus.GENERATED,
    CIPCAnnualStatus.INVOICED,
    CIPCAnnualStatus.INVOICE_PAID,
    CIPCAnnualStatus.BO_SUBMITTED,
)


def is_open(instance: CIPCAnnualInstance) -> bool:
    return instance.status not in _TERMINAL_STATUSES


def open_filter() -> ColumnElement[bool]:
    return CIPCAnnualInstance.status.notin_(_TERMINAL_STATUSES)


def is_overdue(instance: CIPCAnnualInstance, today: date) -> bool:
    return instance.status in _OVERDUE_OPEN_STATUSES and instance.due_date < today


def overdue_filter(today: date) -> ColumnElement[bool]:
    return and_(
        CIPCAnnualInstance.status.in_(_OVERDUE_OPEN_STATUSES),
        CIPCAnnualInstance.due_date < today,
    )


def due_window_filter(today: date, days: int) -> ColumnElement[bool]:
    """CIPC equivalent of obligations.due_window_filter: overdue OR due within the next
    `days` days inclusive. Mirrors the obligation version exactly, against due_date and
    the CIPC overdue predicate, so the two row sources window identically."""
    horizon = today + timedelta(days=days)
    return or_(
        overdue_filter(today),
        and_(
            CIPCAnnualInstance.due_date >= today,
            CIPCAnnualInstance.due_date <= horizon,
        ),
    )
