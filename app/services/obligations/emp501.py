"""EMP501 employer-reconciliation generator (bi-annual PAYE / UIF / SDL reconciliation).

Returns list[ObligationInstance] without committing, mirroring the other generators. The
caller (regenerate service) decides whether to add/commit or diff against existing rows to
avoid the (client_id, obligation_type, period_end) unique-constraint violation.

Two reconciliations per SA tax year (1 March – end February — the FIXED statutory tax
year, NOT the client's financial year-end):

  - Interim (EMP501_INTERIM): covers 1 Mar – 31 Aug; submission due 31 October.
  - Annual  (EMP501_ANNUAL):  covers the full tax year 1 Mar – 28/29 Feb; due 31 May.

period_end is the end of the reconciliation PERIOD (31 Aug / end-February); the due date is
the separate statutory deadline (31 Oct / 31 May) rolled BACKWARD to the last business day
on/before it (SARS deadlines on a weekend / SA public holiday move backward — the EMP201
rule, not the IT14/IT12 forward roll). EMP501 is file-only (PAYE/UIF/SDL is paid monthly
via EMP201), so payment_due_date is set equal to submission_due_date — the schema column is
non-nullable, the ITR14/ITR12 convention.

Horizon (deterministic for reference date `today`):
  - current tax-year end = the first end-of-February on/after today.
  - Current tax year: emit BOTH reconciliations unconditionally (one already past-due is
    still this year's outstanding work; the regenerate prune is past-due-safe).
  - Prior tax year: emit a reconciliation ONLY while its rolled due date is still
    today-or-future — the cross-year overlap (e.g. just after end-February the prior tax
    year's 31 May annual reconciliation is not yet due).

The today parameter exists solely for test determinism; production callers leave it None.
"""

from __future__ import annotations

import calendar
from datetime import date

from app.models.client import Client
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.utils.business_days import shift_to_prior_business_day
from app.utils.dates import today_sast


def _tax_year_end_for(year: int) -> date:
    """End of the SA tax year falling in `year` — the last day of that year's February
    (28 or 29), so leap years are handled correctly."""
    return date(year, 2, calendar.monthrange(year, 2)[1])


def _reconciliations(tax_year_end: date) -> list[tuple[ObligationType, date, date, date]]:
    """For the tax year ending `tax_year_end`, return
    [(obligation_type, period_start, period_end, submission_due), ...] for the interim and
    annual reconciliations. Due dates are already rolled backward off weekends/holidays."""
    end_year = tax_year_end.year
    start_year = end_year - 1
    ty_start = date(start_year, 3, 1)
    return [
        (
            ObligationType.EMP501_INTERIM,
            ty_start,
            date(start_year, 8, 31),
            shift_to_prior_business_day(date(start_year, 10, 31)),
        ),
        (
            ObligationType.EMP501_ANNUAL,
            ty_start,
            tax_year_end,
            shift_to_prior_business_day(date(end_year, 5, 31)),
        ),
    ]


def _instance(
    client: Client,
    obligation_type: ObligationType,
    period_start: date,
    period_end: date,
    due: date,
) -> ObligationInstance:
    return ObligationInstance(
        client_id=client.id,
        obligation_type=obligation_type,
        period_start=period_start,
        period_end=period_end,
        submission_due_date=due,
        # File-only: the column is non-nullable, so mirror submission_due_date (the
        # ITR14/ITR12 convention). EMP501 has no payment leg.
        payment_due_date=due,
        # Explicit so callers see PENDING on un-committed instances; the column default
        # only applies at INSERT flush time.
        status=ObligationStatus.PENDING,
    )


def generate_emp501(client: Client, today: date | None = None) -> list[ObligationInstance]:
    """Generate EMP501 reconciliation instances for a PAYE-registered client.

    Returns instances WITHOUT adding them to a session. Gates on client.has_paye
    (mirroring generate_emp201). See the module docstring for the period/due-date rules
    and the generation horizon.
    """
    if not client.active:
        return []
    if not client.has_paye:
        return []

    if today is None:
        today = today_sast()

    current_tax_year_end = _tax_year_end_for(today.year)
    if current_tax_year_end < today:
        current_tax_year_end = _tax_year_end_for(today.year + 1)
    prior_tax_year_end = _tax_year_end_for(current_tax_year_end.year - 1)

    instances: list[ObligationInstance] = []

    # Current tax year: both reconciliations, unconditionally.
    for obligation_type, period_start, period_end, due in _reconciliations(current_tax_year_end):
        instances.append(_instance(client, obligation_type, period_start, period_end, due))

    # Prior tax year: only reconciliations whose due date is still today-or-future.
    for obligation_type, period_start, period_end, due in _reconciliations(prior_tax_year_end):
        if due >= today:
            instances.append(_instance(client, obligation_type, period_start, period_end, due))

    return instances
