from __future__ import annotations

from app.extensions import db
from app.models.staff import Staff, StaffRole
from app.models.status_event import (
    EVENT_REASSIGN,
    EVENT_TRANSITION,
    KIND_CIPC,
    KIND_OBLIGATION,
    StatusEvent,
)


def _staff() -> Staff:
    s = Staff(code="NIEL", full_name="Niel Meyer", role=StaffRole.TAX)
    db.session.add(s)
    db.session.commit()
    return s


def test_status_event_persists_with_defaults(app):
    with app.app_context():
        actor = _staff()
        e = StatusEvent(
            kind=KIND_OBLIGATION,
            instance_id=42,
            event=EVENT_TRANSITION,
            from_value="PENDING",
            to_value="SUBMITTED",
            actor_staff_id=actor.id,
        )
        db.session.add(e)
        db.session.commit()
        assert e.id is not None
        assert e.created_at is not None
        assert e.kind == KIND_OBLIGATION
        assert e.event == EVENT_TRANSITION


def test_status_event_nullable_values(app):
    """from_value/to_value/actor are all nullable (e.g. a reassign from unassigned, or an
    event whose actor was later deleted)."""
    with app.app_context():
        e = StatusEvent(kind=KIND_CIPC, instance_id=7, event=EVENT_REASSIGN)
        db.session.add(e)
        db.session.commit()
        assert e.from_value is None
        assert e.to_value is None
        assert e.actor_staff_id is None


def test_actor_set_null_on_staff_delete(app):
    """Hard-deleting the actor staff nulls actor_staff_id (history survives offboarding)."""
    with app.app_context():
        actor = _staff()
        e = StatusEvent(
            kind=KIND_OBLIGATION,
            instance_id=1,
            event=EVENT_TRANSITION,
            from_value="PENDING",
            to_value="EXEMPT",
            actor_staff_id=actor.id,
        )
        db.session.add(e)
        db.session.commit()
        event_id = e.id

        db.session.delete(actor)
        db.session.commit()

        refreshed = db.session.get(StatusEvent, event_id)
        assert refreshed is not None
        assert refreshed.actor_staff_id is None
