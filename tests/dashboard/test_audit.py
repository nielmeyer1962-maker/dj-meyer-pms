from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.models.staff import Staff, StaffRole
from app.models.status_event import (
    EVENT_REASSIGN,
    EVENT_TRANSITION,
    KIND_CIPC,
    KIND_OBLIGATION,
    StatusEvent,
)


def _client_row() -> Client:
    c = Client(legal_name="Acme Pty Ltd", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    return c


def _obligation(client_id: int, status=ObligationStatus.PENDING) -> ObligationInstance:
    oi = ObligationInstance(
        client_id=client_id,
        obligation_type=ObligationType.VAT201,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        submission_due_date=date(2026, 2, 28),
        payment_due_date=date(2026, 2, 28),
        status=status,
    )
    db.session.add(oi)
    db.session.commit()
    return oi


def _cipc(client_id: int, status=CIPCAnnualStatus.GENERATED) -> CIPCAnnualInstance:
    inst = CIPCAnnualInstance(
        client_id=client_id,
        anniversary_date=date(2025, 3, 15),
        due_date=date(2026, 3, 15),
        status=status,
    )
    db.session.add(inst)
    db.session.commit()
    return inst


def _events(kind: str, instance_id: int) -> list[StatusEvent]:
    return list(
        db.session.scalars(
            db.select(StatusEvent).where(
                StatusEvent.kind == kind, StatusEvent.instance_id == instance_id
            )
        )
    )


def _auth_staff_id() -> int:
    return db.session.scalar(db.select(Staff.id).where(Staff.email == "auth@test.local"))


# --- obligation transitions ---


def test_transition_writes_exactly_one_event_with_actor(app, client):
    with app.app_context():
        oid = _obligation(_client_row().id).id
    client.post(f"/dashboard/obligations/{oid}/mark-submitted")
    with app.app_context():
        evs = _events(KIND_OBLIGATION, oid)
        assert len(evs) == 1
        e = evs[0]
        assert (e.event, e.from_value, e.to_value) == (EVENT_TRANSITION, "PENDING", "SUBMITTED")
        assert e.actor_staff_id == _auth_staff_id()


def test_refused_transition_writes_no_event(app, client):
    with app.app_context():
        oid = _obligation(_client_row().id).id  # PENDING
    # mark-paid requires SUBMITTED → refused
    client.post(f"/dashboard/obligations/{oid}/mark-paid")
    with app.app_context():
        assert _events(KIND_OBLIGATION, oid) == []
        assert db.session.get(ObligationInstance, oid).status is ObligationStatus.PENDING


def test_reassign_writes_event_with_staff_codes(app, client):
    with app.app_context():
        oid = _obligation(_client_row().id).id
        niel = Staff(code="NIEL", full_name="Niel", email="niel@x.co", role=StaffRole.TAX)
        db.session.add(niel)
        db.session.commit()
        niel_id = niel.id
    client.post(f"/dashboard/obligations/{oid}/reassign", data={"assignee_id": str(niel_id)})
    with app.app_context():
        evs = _events(KIND_OBLIGATION, oid)
        assert len(evs) == 1
        assert (evs[0].event, evs[0].from_value, evs[0].to_value) == (
            EVENT_REASSIGN,
            "unassigned",
            "NIEL",
        )


# --- CIPC transitions ---


def test_cipc_transition_writes_one_cipc_event(app, client):
    with app.app_context():
        cid = _cipc(_client_row().id).id
    client.post(f"/dashboard/cipc/{cid}/mark-invoiced")
    with app.app_context():
        evs = _events(KIND_CIPC, cid)
        assert len(evs) == 1
        assert (evs[0].event, evs[0].from_value, evs[0].to_value) == (
            EVENT_TRANSITION,
            "GENERATED",
            "INVOICED",
        )


def test_cipc_refused_transition_writes_no_event(app, client):
    with app.app_context():
        cid = _cipc(_client_row().id).id  # GENERATED
    # mark-closed needs AR_SUBMITTED → refused
    client.post(f"/dashboard/cipc/{cid}/mark-closed")
    with app.app_context():
        assert _events(KIND_CIPC, cid) == []


def test_cipc_reassign_writes_event(app, client):
    with app.app_context():
        cid = _cipc(_client_row().id).id
        tsego = Staff(code="TSEGO", full_name="Tsego", email="t@x.co", role=StaffRole.SECRETARIAL)
        db.session.add(tsego)
        db.session.commit()
        tsego_id = tsego.id
    client.post(f"/dashboard/cipc/{cid}/reassign", data={"assignee_id": str(tsego_id)})
    with app.app_context():
        evs = _events(KIND_CIPC, cid)
        assert len(evs) == 1
        assert (evs[0].event, evs[0].to_value) == (EVENT_REASSIGN, "TSEGO")
