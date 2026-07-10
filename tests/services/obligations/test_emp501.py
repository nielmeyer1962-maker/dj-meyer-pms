from datetime import date

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import ObligationStatus, ObligationType
from app.services.obligations.emp501 import generate_emp501


def _make_client(
    *,
    has_paye: bool = True,
    active: bool = True,
    legal_name: str = "EMP501 Test Corp",
) -> Client:
    """Persist a client with the given PAYE registration. Caller holds app_context."""
    c = Client(
        legal_name=legal_name,
        entity_type=EntityType.PTY_LTD,
        has_paye=has_paye,
        active=active,
    )
    db.session.add(c)
    db.session.commit()
    return c


def _by_type(instances) -> dict[ObligationType, list]:
    out: dict[ObligationType, list] = {}
    for inst in instances:
        out.setdefault(inst.obligation_type, []).append(inst)
    return out


# --- full set -----------------------------------------------------------------------


def test_full_set_mid_tax_year(app):
    """Mid tax year: exactly the current tax year's interim + annual reconciliations, with
    the correct periods and backward-rolled due dates (31 Oct 2026 is a Saturday → Fri)."""
    with app.app_context():
        client = _make_client()
        instances = generate_emp501(client, today=date(2026, 6, 13))

        assert len(instances) == 2
        for inst in instances:
            assert inst.client_id == client.id
            assert inst.status is ObligationStatus.PENDING
            assert inst.period_start == date(2026, 3, 1)  # tax year starts 1 March
            # File-only: the two due dates coincide (no payment leg).
            assert inst.payment_due_date == inst.submission_due_date

        by_type = _by_type(instances)
        interim = by_type[ObligationType.EMP501_INTERIM][0]
        assert interim.period_end == date(2026, 8, 31)  # covers 1 Mar – 31 Aug
        assert interim.submission_due_date == date(2026, 10, 30)  # 31 Oct 2026 (Sat) → Fri

        annual = by_type[ObligationType.EMP501_ANNUAL][0]
        assert annual.period_end == date(2027, 2, 28)  # full tax year to end-Feb
        assert annual.submission_due_date == date(2027, 5, 31)  # 31 May 2027 (Mon), no roll


# --- backward roll ------------------------------------------------------------------


def test_annual_due_rolls_back_off_weekend(app):
    """31 May 2026 is a Sunday → the annual reconciliation due date rolls BACKWARD to
    Friday 29 May."""
    with app.app_context():
        client = _make_client()
        instances = generate_emp501(client, today=date(2025, 11, 15))
        annual = _by_type(instances)[ObligationType.EMP501_ANNUAL][0]
        assert annual.period_end == date(2026, 2, 28)
        assert annual.submission_due_date == date(2026, 5, 29)  # backward off the Sunday
        assert annual.payment_due_date == date(2026, 5, 29)


def test_leap_tax_year_annual_uses_29_feb(app):
    """A leap tax year puts the annual reconciliation's period_end on 29 February."""
    with app.app_context():
        client = _make_client()
        instances = generate_emp501(client, today=date(2027, 6, 1))
        annual = _by_type(instances)[ObligationType.EMP501_ANNUAL][0]
        assert annual.period_end == date(2028, 2, 29)  # 2028 is a leap year


# --- horizon ------------------------------------------------------------------------


def test_current_interim_emitted_even_when_due_has_passed(app):
    """The current tax year's interim is emitted unconditionally, so a just-passed
    interim deadline (31 Oct 2025) is still surfaced as outstanding work."""
    with app.app_context():
        client = _make_client()
        instances = generate_emp501(client, today=date(2025, 11, 15))
        interim = _by_type(instances)[ObligationType.EMP501_INTERIM][0]
        assert interim.period_end == date(2025, 8, 31)
        assert interim.submission_due_date == date(2025, 10, 31)  # already past on 15 Nov
        assert len(instances) == 2  # current interim + current annual, no prior overlap


def test_horizon_overlap_pulls_prior_year_annual(app):
    """Just after a tax-year-end, the prior tax year's annual reconciliation (due 31 May)
    is not yet due, so it overlaps: current interim + current annual + prior annual."""
    with app.app_context():
        client = _make_client()
        instances = generate_emp501(client, today=date(2026, 3, 10))

        assert len(instances) == 3
        annuals = _by_type(instances)[ObligationType.EMP501_ANNUAL]
        assert len(annuals) == 2
        prior = next(a for a in annuals if a.period_end == date(2026, 2, 28))
        assert prior.period_start == date(2025, 3, 1)  # the PRIOR tax year
        assert prior.submission_due_date == date(2026, 5, 29)


def test_horizon_excludes_lapsed_prior_year(app):
    """Once the prior tax year's annual due date has passed, it drops out — only the
    current tax year's two reconciliations remain."""
    with app.app_context():
        client = _make_client()
        instances = generate_emp501(client, today=date(2026, 6, 1))

        assert len(instances) == 2
        # No prior-year annual (its 29 May 2026 due date has lapsed on 1 June 2026).
        assert not any(i.period_end == date(2026, 2, 28) for i in instances)


# --- gate ---------------------------------------------------------------------------


def test_gate_returns_empty_without_paye(app):
    with app.app_context():
        client = _make_client(has_paye=False)
        assert generate_emp501(client, today=date(2026, 6, 13)) == []


def test_gate_returns_empty_when_inactive(app):
    with app.app_context():
        client = _make_client(active=False)
        assert generate_emp501(client, today=date(2026, 6, 13)) == []
