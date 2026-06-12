"""EMP201 obligation generator (Monthly Employer Declaration: PAYE / UIF / SDL).

Returns list[ObligationInstance] without committing, mirroring generate_vat201.
The caller (Ticket 3c regenerate service) decides whether to add/commit or to
diff against existing rows to avoid the unique-constraint violation.

Authoritative source for due-date logic (user-verified):
  SARS — "Completing the Monthly Employer Declaration (EMP201)":
  https://www.sars.gov.za/types-of-tax/pay-as-you-earn/completing-the-monthly-employer-declaration-emp201/

  - Period: calendar month, regardless of the employer's pay frequency.
  - Due date: the EMP201 and its payment are due within 7 days after month-end,
    i.e. the 7th of the following month.
  - Weekend / SA public holiday: if the 7th falls on a Sat/Sun/SA public holiday
    the due date moves BACKWARD to the last business day BEFORE the 7th (not
    forward). The Sunday→Monday public-holiday substitution is applied by the
    shared ZA holiday calendar in app.utils.business_days.
  - It is both a declaration and a payment, so submission_due_date ==
    payment_due_date (a payment leg; is_done therefore requires PAID).
"""

from __future__ import annotations

import calendar
from datetime import date

from app.models.client import Client
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.utils.business_days import shift_to_prior_business_day
from app.utils.dates import today_sast


def _first_of_month(d: date, delta_months: int) -> date:
    """First day of the month delta_months from d.month (signed)."""
    total = d.year * 12 + (d.month - 1) + delta_months
    new_year, new_month_idx = divmod(total, 12)
    return date(new_year, new_month_idx + 1, 1)


def _last_day_of_month(year: int, month: int) -> date:
    _, last = calendar.monthrange(year, month)
    return date(year, month, last)


def _add_months_clamped(d: date, delta_months: int) -> date:
    """Add delta_months to d, clamping day to month-end if the new month is shorter."""
    total = d.year * 12 + (d.month - 1) + delta_months
    new_year, new_month_idx = divmod(total, 12)
    new_month = new_month_idx + 1
    _, last_day = calendar.monthrange(new_year, new_month)
    return date(new_year, new_month, min(d.day, last_day))


def _due_date_for(period_end: date) -> date:
    """EMP201 due date: the 7th of the following month, rolled BACKWARD to the
    last business day before it when the 7th is a weekend or SA public holiday."""
    if period_end.month == 12:
        following_year = period_end.year + 1
        following_month = 1
    else:
        following_year = period_end.year
        following_month = period_end.month + 1
    return shift_to_prior_business_day(date(following_year, following_month, 7))


def _period_ends_in_window(today: date, months_ahead: int) -> list[date]:
    """Calendar-month period-end dates within [today, today + months_ahead months]."""
    window_end = _add_months_clamped(today, months_ahead)
    results: list[date] = []
    cursor = today.replace(day=1)
    while cursor <= window_end:
        period_end = _last_day_of_month(cursor.year, cursor.month)
        if today <= period_end <= window_end:
            results.append(period_end)
        cursor = _first_of_month(cursor, 1)
    return results


def generate_emp201(
    client: Client,
    months_ahead: int = 12,
    today: date | None = None,
) -> list[ObligationInstance]:
    """Generate EMP201 obligation instances for a PAYE-registered client.

    Returns the instances WITHOUT adding them to a session. The caller decides
    whether to session.add_all() and commit, or diff against existing rows to
    avoid the (client_id, obligation_type, period_end) unique-constraint violation.

    Pre-condition gate — returns [] when the client isn't registered for PAYE
    (client.has_paye is False), mirroring how generate_vat201 gates on has_vat.

    The today parameter exists solely for test determinism. In production, leave
    it as None and the function uses today_sast().
    """
    if not client.active:
        return []
    if not client.has_paye:
        return []

    if today is None:
        today = today_sast()

    instances: list[ObligationInstance] = []
    for period_end in _period_ends_in_window(today, months_ahead):
        period_start = period_end.replace(day=1)
        due = _due_date_for(period_end)
        instances.append(
            ObligationInstance(
                client_id=client.id,
                obligation_type=ObligationType.EMP201,
                period_start=period_start,
                period_end=period_end,
                submission_due_date=due,
                payment_due_date=due,
                # Set explicitly so callers see PENDING on un-committed instances;
                # mapped_column(default=...) only applies at INSERT flush time.
                status=ObligationStatus.PENDING,
            )
        )
    return instances
