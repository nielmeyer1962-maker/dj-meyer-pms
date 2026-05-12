from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType


# --- Helpers ---


def _make_client(legal_name: str = "VAT Test Corp") -> Client:
    """Create and persist a minimal Client for FK use; returns the Client."""
    c = Client(legal_name=legal_name, entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    return c


def _instance_kwargs(client_id: int, period_end: date) -> dict:
    """Minimum-viable kwargs for an ObligationInstance — adjust per test."""
    return dict(
        client_id=client_id,
        obligation_type=ObligationType.VAT201,
        period_start=date(period_end.year, period_end.month, 1),
        period_end=period_end,
        submission_due_date=period_end,
        payment_due_date=period_end,
    )


# --- Happy paths ---


def test_obligation_instance_persists(app):
    with app.app_context():
        c = _make_client()
        oi = ObligationInstance(**_instance_kwargs(c.id, date(2026, 4, 30)))
        db.session.add(oi)
        db.session.commit()
        assert oi.id is not None
        assert oi.obligation_type is ObligationType.VAT201
        assert oi.period_start == date(2026, 4, 1)
        assert oi.period_end == date(2026, 4, 30)


def test_status_defaults_to_pending(app):
    with app.app_context():
        c = _make_client()
        oi = ObligationInstance(**_instance_kwargs(c.id, date(2026, 4, 30)))
        db.session.add(oi)
        db.session.commit()
        assert oi.status is ObligationStatus.PENDING


def test_timestamps_auto_populate(app):
    with app.app_context():
        c = _make_client()
        oi = ObligationInstance(**_instance_kwargs(c.id, date(2026, 4, 30)))
        db.session.add(oi)
        db.session.commit()
        assert oi.generated_at is not None
        assert oi.updated_at is not None


def test_all_obligation_statuses_persist(app):
    """Every ObligationStatus value is storable — no enum-coercion surprises."""
    with app.app_context():
        c = _make_client()
        for i, status in enumerate(ObligationStatus, start=1):
            db.session.add(
                ObligationInstance(
                    status=status,
                    **_instance_kwargs(c.id, date(2026, i, 28)),
                )
            )
        db.session.commit()
        count = db.session.scalar(
            db.select(db.func.count()).select_from(ObligationInstance)
        )
        assert count == len(ObligationStatus)


# --- Invariants ---


def test_unique_constraint_on_client_type_period(app):
    """Generator idempotency: (client_id, obligation_type, period_end) is unique."""
    with app.app_context():
        c = _make_client()
        kwargs = _instance_kwargs(c.id, date(2026, 4, 30))
        db.session.add(ObligationInstance(**kwargs))
        db.session.commit()

        db.session.add(ObligationInstance(**kwargs))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_client_fk_ondelete_restrict(app):
    """FK on client_id is RESTRICT so client deletion cannot orphan submission history."""
    fk = next(iter(ObligationInstance.__table__.c.client_id.foreign_keys))
    assert fk.ondelete == "RESTRICT"
