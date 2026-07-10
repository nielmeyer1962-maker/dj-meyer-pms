"""VAT201 obligation generator.

Returns list[ObligationInstance] without committing. The caller (Ticket 3c
regenerate service) decides whether to add/commit or to diff against existing
rows to avoid the unique-constraint violation.

Authoritative sources for due-date logic (user-verified):
  - VAT tax periods (Categories A–E):
    https://www.sars.gov.za/types-of-tax/value-added-tax/tax-periods-for-vat-vendors/
  - VAT201 due-date rule (eFiling = last business day of following month;
    manual = 25th of following month):
    https://www.sars.gov.za/individuals/i-need-help-with-my-tax/calendar/
  - Weekend / SA public holiday: if a due date falls on a Sat/Sun/SA public
    holiday it shifts to the last business day PRIOR.
"""

from __future__ import annotations

import calendar
from datetime import date

from app.models.client import Client, VatCategory, VatSubmissionMethod
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.utils.business_days import (
    last_business_day_of_month,
    shift_to_prior_business_day,
)
from app.utils.dates import today_sast

# Months whose last day is a period end, per category.
# A: bi-monthly with odd-end months. B: bi-monthly with even-end months.
# C: monthly. D: six-monthly ending Feb and Aug. E: annual — raises below.
_CATEGORY_END_MONTHS: dict[VatCategory, frozenset[int]] = {
    VatCategory.A: frozenset({1, 3, 5, 7, 9, 11}),
    VatCategory.B: frozenset({2, 4, 6, 8, 10, 12}),
    VatCategory.C: frozenset(range(1, 13)),
    VatCategory.D: frozenset({2, 8}),
}

# Period length in months — used to compute period_start.
_CATEGORY_PERIOD_LENGTH_MONTHS: dict[VatCategory, int] = {
    VatCategory.A: 2,
    VatCategory.B: 2,
    VatCategory.C: 1,
    VatCategory.D: 6,
}


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


def _period_start_for(period_end: date, category: VatCategory) -> date:
    """First day of the tax period whose final day is period_end."""
    length = _CATEGORY_PERIOD_LENGTH_MONTHS[category]
    return _first_of_month(period_end, -(length - 1))


def _due_date_for(period_end: date, method: VatSubmissionMethod) -> date:
    """VAT201 due date for a given period_end and submission method."""
    if period_end.month == 12:
        following_year = period_end.year + 1
        following_month = 1
    else:
        following_year = period_end.year
        following_month = period_end.month + 1

    if method is VatSubmissionMethod.EFILING:
        # last_business_day_of_month already returns a business day — no further shift.
        return last_business_day_of_month(following_year, following_month)
    return shift_to_prior_business_day(date(following_year, following_month, 25))


def _period_ends_in_window(today: date, months_ahead: int, category: VatCategory) -> list[date]:
    """Period-end dates within [today, today + months_ahead months], ascending."""
    window_end = _add_months_clamped(today, months_ahead)
    end_months = _CATEGORY_END_MONTHS[category]

    results: list[date] = []
    cursor = today.replace(day=1)
    while cursor <= window_end:
        if cursor.month in end_months:
            period_end = _last_day_of_month(cursor.year, cursor.month)
            if today <= period_end <= window_end:
                results.append(period_end)
        cursor = _first_of_month(cursor, 1)
    return results


def generate_vat201(
    client: Client,
    months_ahead: int = 12,
    today: date | None = None,
) -> list[ObligationInstance]:
    """Generate VAT201 obligation instances for a client.

    Returns the instances WITHOUT adding them to a session. The caller decides
    whether to session.add_all() and commit, or diff against existing rows to
    avoid the (client_id, obligation_type, period_end) unique-constraint violation.

    Pre-condition gate — returns [] when the client isn't ready to generate:
      - client.has_vat is False, OR
      - client.vat_category is None, OR
      - client.vat_submission_method is None.

    Category E raises NotImplementedError("Category E pending domain confirmation")
    until a Cat E vendor is on the books and the rule is confirmed.

    The today parameter exists solely for test determinism. In production, leave
    it as None and the function uses today_sast().
    """
    if not client.active:
        return []
    if not client.has_vat or client.vat_category is None or client.vat_submission_method is None:
        return []

    if client.vat_category is VatCategory.E:
        raise NotImplementedError("Category E pending domain confirmation")

    if today is None:
        today = today_sast()

    method = client.vat_submission_method
    instances: list[ObligationInstance] = []
    for period_end in _period_ends_in_window(today, months_ahead, client.vat_category):
        period_start = _period_start_for(period_end, client.vat_category)
        due = _due_date_for(period_end, method)
        instances.append(
            ObligationInstance(
                client_id=client.id,
                obligation_type=ObligationType.VAT201,
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
