from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.models.staff import Staff, StaffRole
from app.models.status_event import EVENT_TRANSITION, KIND_OBLIGATION, StatusEvent


def _obligation() -> int:
    c = Client(legal_name="Acme Pty Ltd", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    oi = ObligationInstance(
        client_id=c.id,
        obligation_type=ObligationType.VAT201,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        submission_due_date=date(2026, 2, 28),
        payment_due_date=date(2026, 2, 28),
        status=ObligationStatus.PENDING,
    )
    db.session.add(oi)
    db.session.commit()
    return oi.id


def test_detail_lists_events_newest_first_with_actor(app, client):
    with app.app_context():
        oid = _obligation()
    client.post(f"/dashboard/obligations/{oid}/mark-in-progress")
    client.post(f"/dashboard/obligations/{oid}/mark-submitted")

    body = client.get(f"/dashboard/obligations/{oid}").data.decode()
    assert "History" in body
    assert "Status: PENDING → IN_PROGRESS" in body
    assert "Status: IN_PROGRESS → SUBMITTED" in body
    # actor = the logged-in fixture staff
    assert "AUTH Test User" in body
    # newest first: the SUBMITTED transition appears before the IN_PROGRESS one
    assert body.index("IN_PROGRESS → SUBMITTED") < body.index("PENDING → IN_PROGRESS")


def test_detail_shows_dash_when_actor_deleted(app, client):
    with app.app_context():
        oid = _obligation()
        ghost = Staff(code="GHOST", full_name="Ghost", email="ghost@x.co", role=StaffRole.TAX)
        db.session.add(ghost)
        db.session.commit()
        db.session.add(
            StatusEvent(
                kind=KIND_OBLIGATION,
                instance_id=oid,
                event=EVENT_TRANSITION,
                from_value="PENDING",
                to_value="SUBMITTED",
                actor_staff_id=ghost.id,
            )
        )
        db.session.commit()
        db.session.delete(ghost)  # ON DELETE SET NULL nulls the event's actor
        db.session.commit()

    body = client.get(f"/dashboard/obligations/{oid}").data.decode()
    assert "Status: PENDING → SUBMITTED" in body
    assert "—" in body  # actor rendered as a dash


def test_detail_no_history_message(app, client):
    with app.app_context():
        oid = _obligation()
    body = client.get(f"/dashboard/obligations/{oid}").data.decode()
    assert "No history yet." in body
