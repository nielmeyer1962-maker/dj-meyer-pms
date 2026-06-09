from datetime import date

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import ObligationStatus, ObligationType
from app.services.obligations.emp201 import generate_emp201


def _make_persisted_client(
    *, has_paye: bool = True, legal_name: str = "EMP201 Test Corp"
) -> Client:
    """Construct and commit a Client with the given PAYE registration. Caller holds
    app_context."""
    c = Client(
        legal_name=legal_name,
        entity_type=EntityType.PTY_LTD,
        has_paye=has_paye,
    )
    db.session.add(c)
    db.session.commit()
    return c


def _assert_emp201_instance(
    instance,
    *,
    client_id: int,
    period_start: date,
    period_end: date,
    due_date: date,
) -> None:
    """All invariants asserted on a single generated ObligationInstance."""
    assert instance.client_id == client_id
    assert instance.obligation_type is ObligationType.EMP201
    assert instance.period_start == period_start
    assert instance.period_end == period_end
    # EMP201 is a declaration + payment, so the two due dates coincide.
    assert instance.submission_due_date == due_date
    assert instance.payment_due_date == due_date
    assert instance.status is ObligationStatus.PENDING


# --- due-date logic (period_end → 7th of following month, backward rollback) ---


def test_normal_month_jan_2025_due_fri_7_feb(app):
    """Jan 2025 period → due Fri 7 Feb 2025 (a business day, no rollback)."""
    with app.app_context():
        client = _make_persisted_client()
        instances = generate_emp201(client, months_ahead=1, today=date(2025, 1, 1))
        assert len(instances) == 1
        _assert_emp201_instance(
            instances[0],
            client_id=client.id,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            due_date=date(2025, 2, 7),
        )


def test_saturday_rollback_feb_2026_due_fri_6_mar(app):
    """Feb 2026 period → 7 Mar 2026 is a Saturday → rolls BACK to Fri 6 Mar 2026."""
    with app.app_context():
        client = _make_persisted_client()
        instances = generate_emp201(client, months_ahead=1, today=date(2026, 2, 1))
        assert len(instances) == 1
        _assert_emp201_instance(
            instances[0],
            client_id=client.id,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
            due_date=date(2026, 3, 6),
        )


def test_sunday_rollback_may_2026_due_fri_5_jun(app):
    """May 2026 period → 7 Jun 2026 is a Sunday → rolls BACK to Fri 5 Jun 2026."""
    with app.app_context():
        client = _make_persisted_client()
        instances = generate_emp201(client, months_ahead=1, today=date(2026, 5, 1))
        assert len(instances) == 1
        _assert_emp201_instance(
            instances[0],
            client_id=client.id,
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
            due_date=date(2026, 6, 5),
        )


def test_public_holiday_rollback_mar_2034_due_thu_6_apr(app):
    """Mar 2034 period → 7 Apr 2034 is Good Friday (SA public holiday) → rolls BACK to
    the last business day before it, Thu 6 Apr 2034."""
    with app.app_context():
        client = _make_persisted_client()
        instances = generate_emp201(client, months_ahead=1, today=date(2034, 3, 1))
        assert len(instances) == 1
        _assert_emp201_instance(
            instances[0],
            client_id=client.id,
            period_start=date(2034, 3, 1),
            period_end=date(2034, 3, 31),
            due_date=date(2034, 4, 6),
        )


def test_december_period_rolls_into_january(app):
    """Dec 2025 period → due 7 Jan 2026 (Wed), crossing the year boundary cleanly."""
    with app.app_context():
        client = _make_persisted_client()
        instances = generate_emp201(client, months_ahead=1, today=date(2025, 12, 1))
        assert len(instances) == 1
        _assert_emp201_instance(
            instances[0],
            client_id=client.id,
            period_start=date(2025, 12, 1),
            period_end=date(2025, 12, 31),
            due_date=date(2026, 1, 7),
        )


# --- gating ---


def test_non_paye_client_generates_nothing(app):
    """A client not registered for PAYE produces no EMP201 instances."""
    with app.app_context():
        client = _make_persisted_client(has_paye=False, legal_name="No PAYE Corp")
        assert generate_emp201(client, today=date(2026, 1, 1)) == []


# --- generation window ---


def test_window_current_plus_12_months(app):
    """A 12-month window from the 1st yields one monthly instance per month.

    Window is [today, today + 12 months] via the same helper VAT201 uses. With
    today = 1 Jan 2026 the window ends 1 Jan 2027, so month-ends Jan–Dec 2026 (12)
    fall inside it; the 31 Jan 2027 month-end lands just past window_end and is
    excluded. Each instance is EMP201 with month-aligned bounds, in ascending order."""
    with app.app_context():
        client = _make_persisted_client()
        instances = generate_emp201(client, months_ahead=12, today=date(2026, 1, 1))
        assert len(instances) == 12
        period_ends = [i.period_end for i in instances]
        assert period_ends[0] == date(2026, 1, 31)
        assert period_ends[-1] == date(2026, 12, 31)
        assert period_ends == sorted(period_ends)
        assert all(i.obligation_type is ObligationType.EMP201 for i in instances)
        assert all(i.period_start.day == 1 for i in instances)
