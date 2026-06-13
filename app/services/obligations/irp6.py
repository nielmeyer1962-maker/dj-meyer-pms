"""IRP6 provisional-tax obligation generator.

Returns list[ObligationInstance] without committing, mirroring generate_emp201. The
caller (regenerate service) decides whether to add/commit or diff against existing rows
to avoid the (client_id, obligation_type, period_end) unique-constraint violation.

Provisional tax (IRP6) under the Income Tax Act has up to three payments per year of
assessment (YOA):

  - Window 01 (first period):  half-year estimate, due at the end of the 6th month of
    the YOA.
  - Window 02 (second period): full-year estimate, due at the YOA end.
  - Window 03 (third / voluntary "top-up"): an optional payment after year-end —
    6 months after a non-February year-end, or 7 months after a February year-end
    (the well-known 30 September date for Feb year-ends).

period_end carries the STABLE statutory base date for each window; submission_due_date
and payment_due_date are that base rolled BACKWARD to the last business day on/before it
(SARS payment deadlines that land on a weekend / SA public holiday move backward, the
same rule EMP201 uses — never the forward roll IT14/IT12 use). IRP6 is a payment-leg
type, so submission and payment fall on the same rolled date.

This is a TRACKING engine only: no amount, no 50%/top-up computation — just the deadlines
and which window each row is.

The today parameter exists solely for test determinism; production callers leave it None.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from app.models.client import Client
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.utils.business_days import shift_to_prior_business_day
from app.utils.dates import today_sast


def _last_day_of_month(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _year_end_for_year(year: int, month: int, day: int) -> date:
    """The client's financial year-end falling in `year`. February is normalised to the
    actual last day of that year's February (28 or 29), so the result is correct in a leap
    year regardless of the day stored on the client."""
    if month == 2:
        return _last_day_of_month(year, 2)
    return date(year, month, day)


def _month_offset(year: int, month: int, delta: int) -> tuple[int, int]:
    """(year, month) that is `delta` calendar months after the given (year, month),
    rolling across year boundaries. month is 1-12."""
    total = year * 12 + (month - 1) + delta
    y, m = divmod(total, 12)
    return y, m + 1


def _windows_for_yoa(yoa_end: date, month: int, day: int) -> tuple[date, list[tuple[str, date]]]:
    """For the YOA ending `yoa_end`, return (yoa_start, [(window_code, period_end), ...]).

    period_end is the statutory base date per window (not yet business-day rolled)."""
    yoa_start = _year_end_for_year(yoa_end.year - 1, month, day) + timedelta(days=1)

    # Window 01: last day of the 6th month of the YOA (= YOA_start.month + 5 months).
    y1, m1 = _month_offset(yoa_start.year, yoa_start.month, 5)
    p1 = _last_day_of_month(y1, m1)

    # Window 02: the YOA end itself.
    p2 = yoa_end

    # Window 03 (voluntary top-up): 7 months after a Feb year-end (→ 30 Sep), else 6.
    y3, m3 = _month_offset(yoa_end.year, yoa_end.month, 7 if month == 2 else 6)
    p3 = _last_day_of_month(y3, m3)

    return yoa_start, [("01", p1), ("02", p2), ("03", p3)]


def _instance(
    client: Client, yoa_start: date, window_code: str, period_end: date
) -> ObligationInstance:
    due = shift_to_prior_business_day(period_end)
    return ObligationInstance(
        client_id=client.id,
        obligation_type=ObligationType.IRP6,
        period_start=yoa_start,
        period_end=period_end,
        submission_due_date=due,
        payment_due_date=due,
        # Explicit so callers see PENDING on un-committed instances; the column default
        # only applies at INSERT flush time.
        status=ObligationStatus.PENDING,
        window_code=window_code,
    )


def generate_irp6(client: Client, today: date | None = None) -> list[ObligationInstance]:
    """Generate IRP6 obligation instances for a provisional-tax client.

    Returns instances WITHOUT adding them to a session. Gates on
    client.has_provisional_tax (mirroring how generate_emp201 gates on has_paye); also
    returns [] if the client has no financial year-end captured, since the windows can't
    be computed without one.

    Horizon (deterministic for reference date `today`):
      - current_yoa_end = the client's first year-end on/after today.
      - Current YOA (ending current_yoa_end): emit windows 01, 02, 03.
      - Prior YOA (ending one year earlier): emit window 03 ONLY, and only if its
        backward-rolled due date is still today-or-future (captures the cross-year top-up
        overlap, where last year's third payment is not yet due).
    """
    if not client.active:
        return []
    if not client.has_provisional_tax:
        return []
    if client.year_end_month is None or client.year_end_day is None:
        return []

    if today is None:
        today = today_sast()

    month, day = client.year_end_month, client.year_end_day

    current_yoa_end = _year_end_for_year(today.year, month, day)
    if current_yoa_end < today:
        current_yoa_end = _year_end_for_year(today.year + 1, month, day)
    prior_yoa_end = _year_end_for_year(current_yoa_end.year - 1, month, day)

    instances: list[ObligationInstance] = []

    # Current YOA: all three windows, unconditionally (a window already past-due is still
    # this year's obligation; the regenerate prune is past-due-safe and won't drop it).
    yoa_start, windows = _windows_for_yoa(current_yoa_end, month, day)
    for window_code, period_end in windows:
        instances.append(_instance(client, yoa_start, window_code, period_end))

    # Prior YOA: the voluntary third payment only, while it is still due-or-future.
    prior_start, prior_windows = _windows_for_yoa(prior_yoa_end, month, day)
    code3, p3 = prior_windows[2]
    if shift_to_prior_business_day(p3) >= today:
        instances.append(_instance(client, prior_start, code3, p3))

    return instances
