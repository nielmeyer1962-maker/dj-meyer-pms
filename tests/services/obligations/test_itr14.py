from datetime import date

import pytest

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import ObligationStatus, ObligationType
from app.services.obligations.itr14 import generate_itr14


def _make_client(
    *,
    entity_type: EntityType = EntityType.PTY_LTD,
    has_income_tax: bool = True,
    year_end: tuple[int, int] | None = (2, 28),
    legal_name: str = "ITR14 Test Corp",
) -> Client:
    """Construct and commit a Client. year_end is a (month, day) pair or None.
    Caller holds app_context. Sets month before day to satisfy the year-end
    @validates ordering."""
    c = Client(legal_name=legal_name, entity_type=entity_type, has_income_tax=has_income_tax)
    if year_end is not None:
        c.year_end_month = year_end[0]
        c.year_end_day = year_end[1]
    db.session.add(c)
    db.session.commit()
    return c


# --- gating ---


@pytest.mark.parametrize(
    "entity_type",
    [
        EntityType.INDIVIDUAL,
        EntityType.SOLE_PROP,
        EntityType.TRUST,
        EntityType.PARTNERSHIP,
    ],
)
def test_non_company_entity_generates_nothing(app, entity_type):
    """ITR14 is a company return; individuals/sole props/trusts/partnerships file
    other returns and produce no ITR14 instance."""
    with app.app_context():
        client = _make_client(entity_type=entity_type, legal_name=f"{entity_type.name} Co")
        assert generate_itr14(client, today=date(2026, 6, 10)) == []


def test_no_income_tax_registration_generates_nothing(app):
    """A client not registered for income tax produces no ITR14 instance."""
    with app.app_context():
        client = _make_client(has_income_tax=False, legal_name="No IT Corp")
        assert generate_itr14(client, today=date(2026, 6, 10)) == []


def test_missing_year_end_generates_nothing(app):
    """Without a financial year-end there is no period to generate."""
    with app.app_context():
        client = _make_client(year_end=None, legal_name="No YE Corp")
        assert generate_itr14(client, today=date(2026, 6, 10)) == []


@pytest.mark.parametrize(
    "entity_type",
    [EntityType.PTY_LTD, EntityType.INC, EntityType.CC, EntityType.NPC],
)
def test_company_entity_generates_one_instance(app, entity_type):
    """Each company entity type produces exactly one ITR14 instance."""
    with app.app_context():
        client = _make_client(entity_type=entity_type, legal_name=f"{entity_type.name} Co")
        instances = generate_itr14(client, today=date(2026, 6, 10))
        assert len(instances) == 1
        assert instances[0].obligation_type is ObligationType.ITR14


# --- period selection (most-recently-completed financial year) ---


def test_period_fye_already_passed_uses_this_year(app):
    """Feb year-end, today 10 Jun 2026: FYE 28 Feb 2026 has passed → that completed
    FY (1 Mar 2025 – 28 Feb 2026) is the period."""
    with app.app_context():
        client = _make_client(year_end=(2, 28))
        instances = generate_itr14(client, today=date(2026, 6, 10))
        assert len(instances) == 1
        inst = instances[0]
        assert inst.period_end == date(2026, 2, 28)
        assert inst.period_start == date(2025, 3, 1)


def test_period_fye_not_yet_reached_uses_last_year(app):
    """Dec year-end, today 10 Jun 2026: FYE 31 Dec 2026 is still open → the completed
    FY ended 31 Dec 2025 (period 1 Jan 2025 – 31 Dec 2025)."""
    with app.app_context():
        client = _make_client(year_end=(12, 31))
        instances = generate_itr14(client, today=date(2026, 6, 10))
        assert len(instances) == 1
        inst = instances[0]
        assert inst.period_end == date(2025, 12, 31)
        assert inst.period_start == date(2025, 1, 1)


# --- due date: period_end + 12 months, FORWARD-rolled ---


def test_due_is_twelve_months_after_year_end_unchanged(app):
    """Dec 2025 year-end → due 31 Dec 2026, a Thursday business day, left unchanged."""
    with app.app_context():
        client = _make_client(year_end=(12, 31))
        inst = generate_itr14(client, today=date(2026, 6, 10))[0]
        assert inst.submission_due_date == date(2026, 12, 31)


def test_due_saturday_rolls_forward_to_monday(app):
    """Jun 2028 year-end → due_raw 30 Jun 2029 is a Saturday → rolls FORWARD to Mon
    2 Jul 2029 (1 Jul 2029 is a Sunday)."""
    with app.app_context():
        client = _make_client(year_end=(6, 30))
        inst = generate_itr14(client, today=date(2028, 8, 1))[0]
        assert inst.period_end == date(2028, 6, 30)
        assert inst.submission_due_date == date(2029, 7, 2)


def test_due_sunday_rolls_forward_to_monday(app):
    """Jun 2029 year-end → due_raw 30 Jun 2030 is a Sunday → rolls FORWARD to Mon
    1 Jul 2030."""
    with app.app_context():
        client = _make_client(year_end=(6, 30))
        inst = generate_itr14(client, today=date(2029, 8, 1))[0]
        assert inst.period_end == date(2029, 6, 30)
        assert inst.submission_due_date == date(2030, 7, 1)


def test_due_public_holiday_rolls_forward(app):
    """Apr 2024 year-end → due_raw 28 Apr 2025 is Freedom Day (observed, a Monday) →
    rolls FORWARD to Tue 29 Apr 2025."""
    with app.app_context():
        client = _make_client(year_end=(4, 28))
        inst = generate_itr14(client, today=date(2024, 7, 1))[0]
        assert inst.period_end == date(2024, 4, 28)
        assert inst.submission_due_date == date(2025, 4, 29)


# --- build invariants ---


def test_build_invariants(app):
    """payment_due_date == submission_due_date (file-only, but the column is
    non-nullable), status PENDING, type ITR14, client_id wired through."""
    with app.app_context():
        client = _make_client(year_end=(12, 31))
        inst = generate_itr14(client, today=date(2026, 6, 10))[0]
        assert inst.client_id == client.id
        assert inst.obligation_type is ObligationType.ITR14
        assert inst.payment_due_date == inst.submission_due_date
        assert inst.status is ObligationStatus.PENDING


# --- edge: 28-Feb year-end across leap and non-leap years ---


def test_feb_year_end_in_a_leap_year(app):
    """28 Feb year-end, today 1 Jun 2024: period_end 28 Feb 2024 (a leap year) →
    period_start 1 Mar 2023, due 28 Feb 2025 (a Friday)."""
    with app.app_context():
        client = _make_client(year_end=(2, 28))
        inst = generate_itr14(client, today=date(2024, 6, 1))[0]
        assert inst.period_end == date(2024, 2, 28)
        assert inst.period_start == date(2023, 3, 1)
        assert inst.submission_due_date == date(2025, 2, 28)


def test_feb_year_end_in_a_non_leap_year(app):
    """28 Feb year-end, today 1 Jun 2026 (non-leap): period_end 28 Feb 2026 →
    period_start 1 Mar 2025, due_raw 28 Feb 2027 (a Sunday) rolls FORWARD to Mon
    1 Mar 2027 — the non-leap counterpart to the leap-year case above."""
    with app.app_context():
        client = _make_client(year_end=(2, 28))
        inst = generate_itr14(client, today=date(2026, 6, 1))[0]
        assert inst.period_end == date(2026, 2, 28)
        assert inst.period_start == date(2025, 3, 1)
        assert inst.submission_due_date == date(2027, 3, 1)
