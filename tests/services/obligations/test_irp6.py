from datetime import date

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import ObligationStatus, ObligationType
from app.services.obligations.irp6 import generate_irp6


def _make_client(
    *,
    has_provisional_tax: bool = True,
    year_end_month: int | None = 2,
    year_end_day: int | None = 28,
    active: bool = True,
    legal_name: str = "IRP6 Test Corp",
) -> Client:
    """Construct and commit a Client. Caller holds app_context."""
    c = Client(
        legal_name=legal_name,
        entity_type=EntityType.PTY_LTD,
        has_provisional_tax=has_provisional_tax,
        year_end_month=year_end_month,
        year_end_day=year_end_day,
        active=active,
    )
    db.session.add(c)
    db.session.commit()
    return c


# --- full sets ----------------------------------------------------------------------


def test_feb_year_end_full_set(app):
    """February year-end: the three current-YOA windows with correct statutory bases and
    backward-rolled due dates. today is chosen so the prior-year top-up has lapsed,
    leaving exactly the current YOA's 01/02/03."""
    with app.app_context():
        client = _make_client(year_end_month=2, year_end_day=28)
        instances = generate_irp6(client, today=date(2026, 11, 1))

        assert len(instances) == 3
        for inst in instances:
            assert inst.client_id == client.id
            assert inst.obligation_type is ObligationType.IRP6
            assert inst.status is ObligationStatus.PENDING
            assert inst.period_start == date(2026, 3, 1)  # YOA starts day after prev FE
            # Payment leg: submission and payment due coincide.
            assert inst.submission_due_date == inst.payment_due_date

        windows = {i.window_code: i for i in instances}
        # Window 01: last day of the 6th month of the YOA (= 31 Aug), a business day.
        assert windows["01"].period_end == date(2026, 8, 31)
        assert windows["01"].submission_due_date == date(2026, 8, 31)
        # Window 02: the YOA end (28 Feb 2027, a Sunday) → rolls back to Fri 26 Feb.
        assert windows["02"].period_end == date(2027, 2, 28)
        assert windows["02"].submission_due_date == date(2027, 2, 26)
        # Window 03: 7 months after a Feb year-end → 30 Sep, a business day.
        assert windows["03"].period_end == date(2027, 9, 30)
        assert windows["03"].submission_due_date == date(2027, 9, 30)


def test_non_feb_year_end_full_set_with_six_month_third(app):
    """June year-end: 01 at end of the 6th month (31 Dec), 02 at year-end (30 Jun), and
    the voluntary 03 SIX months after year-end (31 Dec) — not the Feb-only 7-month rule."""
    with app.app_context():
        client = _make_client(year_end_month=6, year_end_day=30)
        instances = generate_irp6(client, today=date(2026, 6, 13))

        assert len(instances) == 3
        windows = {i.window_code: i for i in instances}
        for inst in instances:
            assert inst.period_start == date(2025, 7, 1)

        assert windows["01"].period_end == date(2025, 12, 31)
        assert windows["01"].submission_due_date == date(2025, 12, 31)
        assert windows["02"].period_end == date(2026, 6, 30)
        assert windows["02"].submission_due_date == date(2026, 6, 30)
        assert windows["03"].period_end == date(2026, 12, 31)  # 6 months after 30 Jun
        assert windows["03"].submission_due_date == date(2026, 12, 31)


# --- business-day rolls -------------------------------------------------------------


def test_weekend_roll_back_to_friday(app):
    """A second-period base that lands on a Saturday rolls BACKWARD to the Friday
    (28 Feb 2026 is a Saturday → 27 Feb)."""
    with app.app_context():
        client = _make_client(year_end_month=2, year_end_day=28)
        instances = generate_irp6(client, today=date(2026, 1, 1))
        win02 = next(i for i in instances if i.window_code == "02")
        assert win02.period_end == date(2026, 2, 28)  # stable statutory base (Saturday)
        assert win02.submission_due_date == date(2026, 2, 27)  # Friday
        assert win02.payment_due_date == date(2026, 2, 27)


def test_public_holiday_roll_skips_good_friday(app):
    """A March year-end's second-period base of 31 Mar 2024 (a Sunday) rolls back over
    the weekend AND Good Friday (29 Mar 2024) to Thursday 28 Mar — proving the roll is
    public-holiday aware, not merely weekend aware."""
    with app.app_context():
        client = _make_client(year_end_month=3, year_end_day=31)
        instances = generate_irp6(client, today=date(2024, 1, 1))
        win02 = next(i for i in instances if i.window_code == "02")
        assert win02.period_end == date(2024, 3, 31)
        assert win02.submission_due_date == date(2024, 3, 28)


def test_leap_february_uses_29th(app):
    """A Feb year-end in a leap YOA puts the second-period base on 29 Feb, even though the
    client stores year_end_day=28 — the actual last day of February is used."""
    with app.app_context():
        client = _make_client(year_end_month=2, year_end_day=28)
        instances = generate_irp6(client, today=date(2027, 6, 1))
        win02 = next(i for i in instances if i.window_code == "02")
        assert win02.period_end == date(2028, 2, 29)  # 2028 is a leap year


# --- horizon ------------------------------------------------------------------------


def test_horizon_overlap_pulls_prior_yoa_third(app):
    """Just after a year-end, last year's voluntary third payment is not yet due, so it
    overlaps into the current view: 3 current-YOA windows + the prior-YOA 03 = 4 rows."""
    with app.app_context():
        client = _make_client(year_end_month=2, year_end_day=28)
        instances = generate_irp6(client, today=date(2026, 3, 5))

        assert len(instances) == 4
        thirds = [i for i in instances if i.window_code == "03"]
        assert len(thirds) == 2
        prior_third = next(i for i in thirds if i.period_end == date(2026, 9, 30))
        assert prior_third.period_start == date(2025, 3, 1)  # the PRIOR YOA
        assert prior_third.submission_due_date == date(2026, 9, 30)


def test_horizon_excludes_lapsed_prior_third(app):
    """Once the prior-YOA third payment's due date has passed, it drops out — only the
    current YOA's three windows remain."""
    with app.app_context():
        client = _make_client(year_end_month=2, year_end_day=28)
        instances = generate_irp6(client, today=date(2026, 11, 1))

        assert len(instances) == 3
        # No prior-YOA 03 (its 30 Sep 2026 due date has lapsed relative to 1 Nov 2026).
        assert not any(i.period_end == date(2026, 9, 30) for i in instances)


# --- gate ---------------------------------------------------------------------------


def test_gate_returns_empty_without_provisional_tax(app):
    with app.app_context():
        client = _make_client(has_provisional_tax=False)
        assert generate_irp6(client, today=date(2026, 6, 13)) == []


def test_gate_returns_empty_when_inactive(app):
    with app.app_context():
        client = _make_client(active=False)
        assert generate_irp6(client, today=date(2026, 6, 13)) == []


def test_gate_returns_empty_without_year_end(app):
    """A provisional-tax client with no captured year-end can't have windows computed."""
    with app.app_context():
        client = _make_client(year_end_month=None, year_end_day=None)
        assert generate_irp6(client, today=date(2026, 6, 13)) == []
