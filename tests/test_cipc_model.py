from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
from app.models.client import Client, EntityType
from app.models.staff import Staff, StaffRole

# --- Helpers ---


def _make_client(legal_name: str = "CIPC Test Corp") -> Client:
    """Create and persist a minimal Client for FK use; returns the Client."""
    c = Client(legal_name=legal_name, entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    return c


def _make_staff(code: str = "TSEGO", full_name: str = "Tsego Mogale") -> Staff:
    s = Staff(code=code, full_name=full_name, role=StaffRole.SECRETARIAL)
    db.session.add(s)
    db.session.commit()
    return s


def _instance_kwargs(client_id: int, anniversary: date = date(2026, 3, 15)) -> dict:
    """Minimum-viable kwargs for a CIPCAnnualInstance — adjust per test."""
    return dict(
        client_id=client_id,
        anniversary_date=anniversary,
        due_date=anniversary,
    )


# --- Happy paths ---


def test_cipc_instance_persists(app):
    with app.app_context():
        c = _make_client()
        oi = CIPCAnnualInstance(**_instance_kwargs(c.id, date(2026, 3, 15)))
        db.session.add(oi)
        db.session.commit()
        assert oi.id is not None
        assert oi.anniversary_date == date(2026, 3, 15)
        assert oi.annual_turnover_cents is None


def test_status_defaults_to_generated(app):
    with app.app_context():
        c = _make_client()
        oi = CIPCAnnualInstance(**_instance_kwargs(c.id))
        db.session.add(oi)
        db.session.commit()
        assert oi.status is CIPCAnnualStatus.GENERATED


def test_timestamps_auto_populate(app):
    with app.app_context():
        c = _make_client()
        oi = CIPCAnnualInstance(**_instance_kwargs(c.id))
        db.session.add(oi)
        db.session.commit()
        assert oi.generated_at is not None
        assert oi.updated_at is not None


def test_six_states_in_declared_order(app):
    """The workflow enum is exactly the six ordered states, BO before AR."""
    assert [s.name for s in CIPCAnnualStatus] == [
        "GENERATED",
        "INVOICED",
        "INVOICE_PAID",
        "BO_SUBMITTED",
        "AR_SUBMITTED",
        "CLOSED",
    ]


def test_all_statuses_persist(app):
    """Every CIPCAnnualStatus value is storable — no enum-coercion surprises."""
    with app.app_context():
        c = _make_client()
        for i, status in enumerate(CIPCAnnualStatus, start=1):
            db.session.add(
                CIPCAnnualInstance(
                    status=status,
                    **_instance_kwargs(c.id, date(2020 + i, 3, 15)),
                )
            )
        db.session.commit()
        count = db.session.scalar(db.select(db.func.count()).select_from(CIPCAnnualInstance))
        assert count == len(CIPCAnnualStatus)


def test_annual_turnover_cents_stores_large_value(app):
    """Turnover is stored in cents as a BigInteger — R250m = 25_000_000_000 cents."""
    with app.app_context():
        c = _make_client()
        oi = CIPCAnnualInstance(annual_turnover_cents=25_000_000_000, **_instance_kwargs(c.id))
        db.session.add(oi)
        db.session.commit()
        db.session.refresh(oi)
        assert oi.annual_turnover_cents == 25_000_000_000


# --- Invariants ---


def test_unique_constraint_on_client_anniversary(app):
    """Generator idempotency: (client_id, anniversary_date) is unique."""
    with app.app_context():
        c = _make_client()
        kwargs = _instance_kwargs(c.id, date(2026, 3, 15))
        db.session.add(CIPCAnnualInstance(**kwargs))
        db.session.commit()

        db.session.add(CIPCAnnualInstance(**kwargs))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_client_fk_ondelete_restrict(app):
    """FK on client_id is RESTRICT so client deletion cannot orphan CIPC history."""
    fk = next(iter(CIPCAnnualInstance.__table__.c.client_id.foreign_keys))
    assert fk.ondelete == "RESTRICT"


# --- assignee_id ---


def test_assignee_id_nullable(app):
    with app.app_context():
        c = _make_client()
        oi = CIPCAnnualInstance(assignee_id=None, **_instance_kwargs(c.id))
        db.session.add(oi)
        db.session.commit()
        assert oi.id is not None
        assert oi.assignee_id is None


def test_assignee_id_persists_with_valid_staff_fk(app):
    with app.app_context():
        c = _make_client()
        s = _make_staff()
        oi = CIPCAnnualInstance(assignee_id=s.id, **_instance_kwargs(c.id))
        db.session.add(oi)
        db.session.commit()
        assert oi.assignee_id == s.id


def test_assignee_fk_set_null_on_staff_delete(app):
    """Hard-deleting a Staff row reverts assigned CIPC instances to assignee_id=None,
    not blocked. Requires SQLite PRAGMA foreign_keys = ON (see conftest)."""
    with app.app_context():
        c = _make_client()
        s = _make_staff()
        oi = CIPCAnnualInstance(assignee_id=s.id, **_instance_kwargs(c.id))
        db.session.add(oi)
        db.session.commit()
        assert oi.assignee_id == s.id

        db.session.delete(s)
        db.session.commit()
        db.session.refresh(oi)
        assert oi.assignee_id is None
