from __future__ import annotations

from datetime import date

import pytest

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.services.obligations.predicates import is_overdue, overdue_filter

TODAY = date(2026, 5, 13)
YESTERDAY = date(2026, 5, 12)
TOMORROW = date(2026, 5, 14)


def _make_client(legal_name: str = "Overdue Test Corp") -> Client:
    c = Client(legal_name=legal_name, entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    return c


def _make_instance(
    client_id: int,
    status: ObligationStatus,
    due: date,
    period_end: date | None = None,
) -> ObligationInstance:
    """Persist an ObligationInstance with the given status and due date."""
    pe = period_end or due
    oi = ObligationInstance(
        client_id=client_id,
        obligation_type=ObligationType.VAT201,
        period_start=date(pe.year, pe.month, 1),
        period_end=pe,
        submission_due_date=due,
        payment_due_date=due,
        status=status,
    )
    db.session.add(oi)
    db.session.commit()
    return oi


# --- is_overdue (Python eval) ---


@pytest.mark.parametrize(
    "status,due,expected",
    [
        (ObligationStatus.PENDING, YESTERDAY, True),
        (ObligationStatus.PENDING, TODAY, False),  # strict <, due today is not overdue
        (ObligationStatus.PENDING, TOMORROW, False),
        # IN_PROGRESS is an open status: started work can still be late.
        (ObligationStatus.IN_PROGRESS, YESTERDAY, True),
        (ObligationStatus.IN_PROGRESS, TODAY, False),
        (ObligationStatus.IN_PROGRESS, TOMORROW, False),
        (ObligationStatus.SUBMITTED, YESTERDAY, False),
        (ObligationStatus.PAID, YESTERDAY, False),
        (ObligationStatus.EXEMPT, YESTERDAY, False),
    ],
)
def test_is_overdue_matrix(app, status, due, expected):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, status, due)
        assert is_overdue(oi, TODAY) is expected


# --- overdue_filter (SQL eval) ---


def test_overdue_filter_matches_open_past_statuses(app):
    """SQL predicate must match Python predicate semantically — a divergence between
    them would be a silent dashboard bug. Seeds one row per (status x past/today/future)
    combination relevant to the predicate and asserts exactly the open (PENDING /
    IN_PROGRESS) + past rows match."""
    with app.app_context():
        c = _make_client()

        # Each row uses a unique period_end to satisfy the
        # (client_id, obligation_type, period_end) unique constraint.
        pending_past = _make_instance(
            c.id, ObligationStatus.PENDING, YESTERDAY, period_end=date(2026, 1, 31)
        )
        in_progress_past = _make_instance(
            c.id, ObligationStatus.IN_PROGRESS, YESTERDAY, period_end=date(2026, 7, 31)
        )
        _make_instance(c.id, ObligationStatus.PENDING, TODAY, period_end=date(2026, 2, 28))
        _make_instance(c.id, ObligationStatus.PENDING, TOMORROW, period_end=date(2026, 3, 31))
        _make_instance(c.id, ObligationStatus.IN_PROGRESS, TOMORROW, period_end=date(2026, 8, 31))
        _make_instance(c.id, ObligationStatus.SUBMITTED, YESTERDAY, period_end=date(2026, 4, 30))
        _make_instance(c.id, ObligationStatus.PAID, YESTERDAY, period_end=date(2026, 5, 31))
        _make_instance(c.id, ObligationStatus.EXEMPT, YESTERDAY, period_end=date(2026, 6, 30))

        results = db.session.scalars(
            db.select(ObligationInstance).where(overdue_filter(TODAY))
        ).all()

        assert {r.id for r in results} == {pending_past.id, in_progress_past.id}
