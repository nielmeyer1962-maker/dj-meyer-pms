from datetime import date

import pytest

from app.extensions import db
from app.models.app_setting import APP_SETTING_SEED, AppSetting
from app.models.client import Client, EntityType
from app.models.obligation import ObligationStatus, ObligationType
from app.services.obligations.it12 import generate_it12


def _seed_settings() -> None:
    """Seed the ITR12 deadlines (SQLite create_all does not run the seeding migration)."""
    for row in APP_SETTING_SEED:
        db.session.add(AppSetting(**row))
    db.session.commit()


def _make_individual(
    *,
    has_income_tax: bool = True,
    provisional: bool = False,
    legal_name: str = "Smit, J",
) -> Client:
    c = Client(
        legal_name=legal_name,
        entity_type=EntityType.INDIVIDUAL,
        has_income_tax=has_income_tax,
        has_provisional_tax=provisional,
    )
    db.session.add(c)
    db.session.commit()
    return c


# --- gating ---


@pytest.mark.parametrize(
    "entity_type",
    [
        EntityType.PTY_LTD,
        EntityType.CC,
        EntityType.INC,
        EntityType.NPC,
        EntityType.TRUST,
        EntityType.SOLE_PROP,
        EntityType.PARTNERSHIP,
    ],
)
def test_non_individual_generates_nothing(app, entity_type):
    """ITR12 is the individual return; every non-individual entity produces nothing."""
    with app.app_context():
        c = Client(
            legal_name=f"{entity_type.name} Co",
            entity_type=entity_type,
            has_income_tax=True,
        )
        db.session.add(c)
        db.session.commit()
        assert generate_it12(c, today=date(2026, 6, 11)) == []


def test_no_income_tax_registration_generates_nothing(app):
    with app.app_context():
        c = _make_individual(has_income_tax=False, legal_name="No IT Individual")
        assert generate_it12(c, today=date(2026, 6, 11)) == []


def test_individual_generates_one_instance(app):
    with app.app_context():
        _seed_settings()
        c = _make_individual()
        instances = generate_it12(c, today=date(2026, 6, 11))
        assert len(instances) == 1
        assert instances[0].obligation_type is ObligationType.ITR12


# --- period_end: latest closed year of assessment (leap year + 1-March boundary) ---


def test_period_end_after_year_end_uses_this_february(app):
    """Mid-2026 → the YoA that closed 28 Feb 2026 (1 Mar 2025 – 28 Feb 2026)."""
    with app.app_context():
        _seed_settings()
        inst = generate_it12(_make_individual(), today=date(2026, 6, 11))[0]
        assert inst.period_end == date(2026, 2, 28)
        assert inst.period_start == date(2025, 3, 1)


def test_period_end_on_first_march_uses_just_closed_year(app):
    """1 March 2026: the YoA ending 28 Feb 2026 has just closed → it is the period."""
    with app.app_context():
        _seed_settings()
        inst = generate_it12(_make_individual(), today=date(2026, 3, 1))[0]
        assert inst.period_end == date(2026, 2, 28)
        assert inst.period_start == date(2025, 3, 1)


def test_period_end_before_year_end_uses_prior_february(app):
    """Mid-Feb 2026 (the current YoA is still open) → the latest CLOSED YoA ended
    28 Feb 2025."""
    with app.app_context():
        _seed_settings()
        inst = generate_it12(_make_individual(), today=date(2026, 2, 15))[0]
        assert inst.period_end == date(2025, 2, 28)
        assert inst.period_start == date(2024, 3, 1)


def test_period_end_is_leap_aware(app):
    """A leap year of assessment ends 29 February."""
    with app.app_context():
        _seed_settings()
        inst = generate_it12(_make_individual(), today=date(2024, 6, 1))[0]
        assert inst.period_end == date(2024, 2, 29)
        assert inst.period_start == date(2023, 3, 1)


# --- deadline selection + first occurrence strictly after period_end ---


def test_non_provisional_due_is_23_october_same_year(app):
    """Non-provisional individual, YoA 2026 → 23 Oct 2026 (a Friday, no roll)."""
    with app.app_context():
        _seed_settings()
        inst = generate_it12(_make_individual(provisional=False), today=date(2026, 6, 11))[0]
        assert inst.submission_due_date == date(2026, 10, 23)


def test_provisional_due_is_20_january_following_year(app):
    """Provisional individual, YoA 2026 → 20 Jan 2027: the first 20 January STRICTLY
    AFTER 28 Feb 2026 falls in the next calendar year (20 Jan 2026 is before period_end)."""
    with app.app_context():
        _seed_settings()
        inst = generate_it12(_make_individual(provisional=True), today=date(2026, 6, 11))[0]
        assert inst.submission_due_date == date(2027, 1, 20)


# --- business-day forward roll ---


def test_non_provisional_due_rolls_forward_off_weekend(app):
    """YoA 2027 → 23 Oct 2027 is a Saturday → rolls FORWARD to Mon 25 Oct 2027."""
    with app.app_context():
        _seed_settings()
        inst = generate_it12(_make_individual(provisional=False), today=date(2027, 6, 1))[0]
        assert inst.period_end == date(2027, 2, 28)
        assert inst.submission_due_date == date(2027, 10, 25)


def test_provisional_due_rolls_forward_off_weekend(app):
    """YoA 2028 (leap, period_end 29 Feb 2028) → 20 Jan 2029 is a Saturday → Mon 22 Jan."""
    with app.app_context():
        _seed_settings()
        inst = generate_it12(_make_individual(provisional=True), today=date(2028, 6, 1))[0]
        assert inst.period_end == date(2028, 2, 29)
        assert inst.submission_due_date == date(2029, 1, 22)


# --- build invariants ---


def test_build_invariants(app):
    """File-only: payment_due_date == submission_due_date, status PENDING, type ITR12,
    client_id wired through."""
    with app.app_context():
        _seed_settings()
        c = _make_individual()
        inst = generate_it12(c, today=date(2026, 6, 11))[0]
        assert inst.client_id == c.id
        assert inst.obligation_type is ObligationType.ITR12
        assert inst.payment_due_date == inst.submission_due_date
        assert inst.status is ObligationStatus.PENDING
