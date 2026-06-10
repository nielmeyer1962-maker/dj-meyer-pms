from __future__ import annotations

from datetime import date

import pytest

from app.extensions import db
from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
from app.models.client import Client, EntityType
from app.services.cipc.predicates import (
    is_open,
    is_overdue,
    open_filter,
    overdue_filter,
)

TODAY = date(2026, 5, 13)
YESTERDAY = date(2026, 5, 12)
TOMORROW = date(2026, 5, 14)


def _make_client(legal_name: str = "CIPC Predicate Corp") -> Client:
    c = Client(legal_name=legal_name, entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    return c


def _make_instance(
    client_id: int,
    status: CIPCAnnualStatus,
    due: date,
    anniversary: date | None = None,
) -> CIPCAnnualInstance:
    """Persist a CIPCAnnualInstance with the given status and due date. The unique
    (client_id, anniversary_date) constraint means each row needs a distinct anniversary;
    default it off the due date."""
    inst = CIPCAnnualInstance(
        client_id=client_id,
        anniversary_date=anniversary or due,
        due_date=due,
        status=status,
    )
    db.session.add(inst)
    db.session.commit()
    return inst


# --- is_open (Python eval): only CLOSED / DECLINED are closed ---


@pytest.mark.parametrize(
    "status,expected",
    [
        (CIPCAnnualStatus.GENERATED, True),
        (CIPCAnnualStatus.INVOICED, True),
        (CIPCAnnualStatus.INVOICE_PAID, True),
        (CIPCAnnualStatus.BO_SUBMITTED, True),
        (CIPCAnnualStatus.AR_SUBMITTED, True),  # filed but not yet CLOSED is still open
        (CIPCAnnualStatus.CLOSED, False),
        (CIPCAnnualStatus.DECLINED, False),
    ],
)
def test_is_open_matrix(app, status, expected):
    with app.app_context():
        c = _make_client()
        inst = _make_instance(c.id, status, TODAY)
        assert is_open(inst) is expected


# --- is_overdue (Python eval): past due AND status NOT IN {AR_SUBMITTED, CLOSED, DECLINED} ---


@pytest.mark.parametrize(
    "status,due,expected",
    [
        (CIPCAnnualStatus.GENERATED, YESTERDAY, True),
        (CIPCAnnualStatus.GENERATED, TODAY, False),  # strict <, due today is not overdue
        (CIPCAnnualStatus.GENERATED, TOMORROW, False),
        (CIPCAnnualStatus.INVOICED, YESTERDAY, True),
        (CIPCAnnualStatus.INVOICE_PAID, YESTERDAY, True),
        (CIPCAnnualStatus.BO_SUBMITTED, YESTERDAY, True),
        # Once the AR is filed the deadline is met — never overdue even if past.
        (CIPCAnnualStatus.AR_SUBMITTED, YESTERDAY, False),
        (CIPCAnnualStatus.CLOSED, YESTERDAY, False),
        (CIPCAnnualStatus.DECLINED, YESTERDAY, False),
    ],
)
def test_is_overdue_matrix(app, status, due, expected):
    with app.app_context():
        c = _make_client()
        inst = _make_instance(c.id, status, due)
        assert is_overdue(inst, TODAY) is expected


# --- SQL filters must match the Python predicates semantically ---


def test_open_filter_matches_non_terminal_rows(app):
    with app.app_context():
        c = _make_client()
        generated = _make_instance(c.id, CIPCAnnualStatus.GENERATED, TODAY, date(2025, 1, 1))
        ar_submitted = _make_instance(c.id, CIPCAnnualStatus.AR_SUBMITTED, TODAY, date(2025, 2, 1))
        _make_instance(c.id, CIPCAnnualStatus.CLOSED, TODAY, date(2025, 3, 1))
        _make_instance(c.id, CIPCAnnualStatus.DECLINED, TODAY, date(2025, 4, 1))

        results = db.session.scalars(db.select(CIPCAnnualInstance).where(open_filter())).all()

        assert {r.id for r in results} == {generated.id, ar_submitted.id}


def test_overdue_filter_matches_open_past_statuses(app):
    """SQL predicate must match Python predicate: only the pre-filing statuses with a
    past due date qualify. AR_SUBMITTED/CLOSED/DECLINED and today/future rows excluded."""
    with app.app_context():
        c = _make_client()

        generated_past = _make_instance(
            c.id, CIPCAnnualStatus.GENERATED, YESTERDAY, date(2025, 1, 1)
        )
        bo_past = _make_instance(c.id, CIPCAnnualStatus.BO_SUBMITTED, YESTERDAY, date(2025, 2, 1))
        _make_instance(c.id, CIPCAnnualStatus.GENERATED, TODAY, date(2025, 3, 1))
        _make_instance(c.id, CIPCAnnualStatus.GENERATED, TOMORROW, date(2025, 4, 1))
        _make_instance(c.id, CIPCAnnualStatus.AR_SUBMITTED, YESTERDAY, date(2025, 5, 1))
        _make_instance(c.id, CIPCAnnualStatus.CLOSED, YESTERDAY, date(2025, 6, 1))
        _make_instance(c.id, CIPCAnnualStatus.DECLINED, YESTERDAY, date(2025, 7, 1))

        results = db.session.scalars(
            db.select(CIPCAnnualInstance).where(overdue_filter(TODAY))
        ).all()

        assert {r.id for r in results} == {generated_past.id, bo_past.id}
