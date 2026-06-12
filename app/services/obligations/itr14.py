"""ITR14 obligation generator (company income-tax return).

Returns list[ObligationInstance] without committing, mirroring generate_emp201
and generate_vat201. The caller (Ticket 3c regenerate service) decides whether
to add/commit or to diff against existing rows to avoid the unique-constraint
violation.

Due-date rule (user-confirmed):
  - One ITR14 per company per financial year, for the most-recently-COMPLETED
    financial year (the open FY's return is not yet due, so it is not emitted).
  - period_end  = the company's financial year-end date for that completed year.
  - period_start = the day after the prior year-end (the first day of the FY).
  - submission_due_date = period_end + 12 months (same month/day next year,
    clamped to month length), then rolled FORWARD to the next business day if it
    lands on a weekend or SA public holiday. eFiling.
  - ITR14 is file-only (no payment leg), but payment_due_date is non-nullable in
    the schema, so it is set equal to submission_due_date (as VAT201/EMP201 do).

ITR14 applies only to companies (Pty Ltd, Inc, CC, NPC). Individuals and sole
props file ITR12, trusts file ITR12T, partnerships are transparent — all out of
scope here.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.utils.business_days import shift_to_next_business_day
from app.utils.dates import today_sast

# Entity types that file an ITR14 (company income-tax return).
_ITR14_ENTITY_TYPES: frozenset[EntityType] = frozenset(
    {EntityType.PTY_LTD, EntityType.INC, EntityType.CC, EntityType.NPC}
)


def _year_end_on(year: int, month: int, day: int) -> date:
    """The year-end date in `year`, clamping the day to the month's length so a
    stored 31 (or 29) never raises in a short month (e.g. Feb, 30-day months)."""
    _, last_day = calendar.monthrange(year, month)
    return date(year, month, min(day, last_day))


def generate_itr14(
    client: Client,
    months_ahead: int = 12,
    today: date | None = None,
) -> list[ObligationInstance]:
    """Generate the ITR14 obligation for a company's most-recently-completed FY.

    Returns the instance(s) WITHOUT adding them to a session. The caller decides
    whether to session.add_all() and commit, or diff against existing rows to
    avoid the (client_id, obligation_type, period_end) unique-constraint violation.

    months_ahead is accepted for signature compatibility with the other generators
    (the regenerate caller passes today= by keyword) but is IGNORED: ITR14 period
    selection is the completed-financial-year rule, not a forward window.

    Pre-condition gate — returns [] unless ALL of:
      - client.has_income_tax is True, and
      - client.entity_type is a company (Pty Ltd / Inc / CC / NPC), and
      - both client.year_end_month and client.year_end_day are set.

    The today parameter exists solely for test determinism. In production, leave
    it as None and the function uses today_sast().
    """
    if not client.active:
        return []
    if not client.has_income_tax:
        return []
    if client.entity_type not in _ITR14_ENTITY_TYPES:
        return []
    if client.year_end_month is None or client.year_end_day is None:
        return []

    if today is None:
        today = today_sast()

    month = client.year_end_month
    day = client.year_end_day

    # The most-recently-completed financial year. This year's year-end has only
    # passed if it is <= today; otherwise the completed FY ended last year.
    this_year_end = _year_end_on(today.year, month, day)
    if this_year_end <= today:
        period_end = this_year_end
    else:
        period_end = _year_end_on(today.year - 1, month, day)

    # period_start is the day after the prior year-end (first day of the FY).
    prior_year_end = _year_end_on(period_end.year - 1, month, day)
    period_start = prior_year_end + timedelta(days=1)

    # Due 12 months after year-end (same month/day next year, clamped), then rolled
    # FORWARD off any weekend / SA public holiday.
    due = shift_to_next_business_day(
        _year_end_on(period_end.year + 1, period_end.month, period_end.day)
    )

    return [
        ObligationInstance(
            client_id=client.id,
            obligation_type=ObligationType.ITR14,
            period_start=period_start,
            period_end=period_end,
            submission_due_date=due,
            payment_due_date=due,
            # Set explicitly so callers see PENDING on un-committed instances;
            # mapped_column(default=...) only applies at INSERT flush time.
            status=ObligationStatus.PENDING,
        )
    ]
