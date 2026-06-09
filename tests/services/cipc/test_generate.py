from datetime import date

import pytest

from app.extensions import db
from app.models.cipc import CIPCAnnualStatus
from app.models.client import Client, EntityType
from app.services.cipc.generate import generate_cipc_annual


def _make_client(
    *,
    entity_type: EntityType = EntityType.PTY_LTD,
    anniversary_month: int | None = 3,
    anniversary_day: int | None = 16,
    legal_name: str = "CIPC Gen Corp",
) -> Client:
    c = Client(
        legal_name=legal_name,
        entity_type=entity_type,
        cipc_anniversary_month=anniversary_month,
        cipc_anniversary_day=anniversary_day,
    )
    db.session.add(c)
    db.session.commit()
    return c


# --- Gating ---


@pytest.mark.parametrize(
    "entity_type",
    [EntityType.INDIVIDUAL, EntityType.SOLE_PROP, EntityType.TRUST, EntityType.PARTNERSHIP],
)
def test_non_filing_entity_generates_nothing(app, entity_type):
    with app.app_context():
        c = _make_client(entity_type=entity_type)
        assert generate_cipc_annual(c, today=date(2026, 2, 1)) == []


def test_missing_anniversary_generates_nothing(app):
    with app.app_context():
        c = _make_client(anniversary_month=None, anniversary_day=None)
        assert generate_cipc_annual(c, today=date(2026, 2, 1)) == []


# --- Surfacing (current cycle = most recent anniversary surfaced at -45 days) ---


def test_surfaced_upcoming_anniversary(app):
    """today 2026-02-01, anniversary 16 Mar (surface 30 Jan) → the upcoming 2026-03-16
    anniversary is current; company due = 30 business days = 2026-04-30."""
    with app.app_context():
        c = _make_client()
        instances = generate_cipc_annual(c, today=date(2026, 2, 1))
        assert len(instances) == 1
        inst = instances[0]
        assert inst.anniversary_date == date(2026, 3, 16)
        assert inst.due_date == date(2026, 4, 30)
        assert inst.status is CIPCAnnualStatus.GENERATED
        assert inst.client_id == c.id


def test_surface_boundary_exactly_45_days_before(app):
    """today == anniversary − 45 (2026-01-30) → the upcoming anniversary surfaces."""
    with app.app_context():
        c = _make_client()
        instances = generate_cipc_annual(c, today=date(2026, 1, 30))
        assert len(instances) == 1
        assert instances[0].anniversary_date == date(2026, 3, 16)


def test_one_day_before_surfacing_is_previous_cycle(app):
    """today == anniversary − 46 (2026-01-29): the upcoming anniversary has NOT surfaced,
    so the current cycle is still last year's anniversary (2025-03-16). The windows tile
    with no gap — exactly one instance is always current."""
    with app.app_context():
        c = _make_client()
        instances = generate_cipc_annual(c, today=date(2026, 1, 29))
        assert len(instances) == 1
        assert instances[0].anniversary_date == date(2025, 3, 16)


def test_just_after_anniversary_still_current_cycle(app):
    """today shortly after the anniversary → that anniversary is the current cycle."""
    with app.app_context():
        c = _make_client()
        instances = generate_cipc_annual(c, today=date(2026, 3, 20))
        assert len(instances) == 1
        assert instances[0].anniversary_date == date(2026, 3, 16)


# --- Entity-type due dates ---


def test_cc_uses_month_end_rule(app):
    """A CC, anniversary 15 Mar → due = last day of the following month = 30 Apr 2026."""
    with app.app_context():
        c = _make_client(entity_type=EntityType.CC, anniversary_day=15)
        instances = generate_cipc_annual(c, today=date(2026, 2, 1))
        assert len(instances) == 1
        assert instances[0].anniversary_date == date(2026, 3, 15)
        assert instances[0].due_date == date(2026, 4, 30)


@pytest.mark.parametrize("entity_type", [EntityType.PTY_LTD, EntityType.INC, EntityType.NPC])
def test_company_types_use_business_day_rule(app, entity_type):
    with app.app_context():
        c = _make_client(entity_type=entity_type)
        instances = generate_cipc_annual(c, today=date(2026, 2, 1))
        assert len(instances) == 1
        assert instances[0].due_date == date(2026, 4, 30)


# --- Assignee passthrough ---


def test_assignee_id_is_stamped(app):
    with app.app_context():
        c = _make_client()
        instances = generate_cipc_annual(c, today=date(2026, 2, 1), assignee_id=99)
        assert instances[0].assignee_id == 99
