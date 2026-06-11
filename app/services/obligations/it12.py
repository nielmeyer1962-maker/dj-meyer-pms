"""ITR12 obligation generator (individual income-tax return).

Twin of generate_itr14: returns list[ObligationInstance] without committing, mirroring the
other generators. The caller (Ticket 3c regenerate service) decides whether to add/commit
or to diff against existing rows to avoid the unique-constraint violation.

Rule (user-confirmed):
  - Individuals only. period_end = end-February of the latest year of assessment that has
    CLOSED (the most recent end-Feb <= today; leap-year aware). The SA individual year of
    assessment runs 1 March -> end-February.
  - Deadline day+month comes from AppSetting, chosen by client.has_provisional_tax
    (provisional -> January; non-provisional -> October). The due date is the FIRST
    occurrence of that day+month STRICTLY AFTER period_end, then rolled FORWARD to the next
    business day off any weekend / SA public holiday. eFiling.
      e.g. YoA 2026 (period_end 28 Feb 2026): non-prov -> 23 Oct 2026; prov -> 20 Jan 2027.
  - One open ITR12 per individual, the current closed YoA only, emitted now so it sits
    PENDING from year-end through to the deadline. File-only (no payment leg), so
    payment_due_date mirrors submission_due_date and is_done resolves at SUBMITTED.
"""

from __future__ import annotations

import calendar
from datetime import date

from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.services.settings import get_itr12_deadline
from app.utils.business_days import shift_to_next_business_day


def _end_of_february(year: int) -> date:
    """The last day of February in `year`: 29 Feb in a leap year, else 28 Feb."""
    return date(year, 2, 29 if calendar.isleap(year) else 28)


def _day_month_in_year(year: int, month: int, day: int) -> date:
    """The given day+month landed in `year`, clamping the day to the month's length so a
    stored 31 (or 30) never raises in a short month."""
    _, last_day = calendar.monthrange(year, month)
    return date(year, month, min(day, last_day))


def generate_it12(
    client: Client,
    months_ahead: int = 12,
    today: date | None = None,
) -> list[ObligationInstance]:
    """Generate the ITR12 obligation for an individual's most-recently-closed YoA.

    Returns the instance(s) WITHOUT adding them to a session, mirroring generate_itr14.

    months_ahead is accepted for signature parity with the other generators (the regenerate
    caller passes today= by keyword) but is IGNORED: ITR12 period selection is the
    closed-year-of-assessment rule, not a forward window.

    Pre-condition gate — returns [] unless BOTH:
      - client.has_income_tax is True, and
      - client.entity_type is EntityType.INDIVIDUAL.

    The today parameter exists solely for test determinism; production leaves it None.
    """
    if not client.has_income_tax:
        return []
    if client.entity_type is not EntityType.INDIVIDUAL:
        return []

    if today is None:
        today = date.today()

    # period_end = end-Feb of the latest YoA that has closed. This year's end-Feb counts
    # only once it has arrived (<= today, so 1 March selects the just-closed YoA); before
    # then the latest closed YoA ended last February.
    this_year_end = _end_of_february(today.year)
    period_end = this_year_end if this_year_end <= today else _end_of_february(today.year - 1)
    # The YoA opened on 1 March of the prior calendar year.
    period_start = date(period_end.year - 1, 3, 1)

    # Deadline day+month, chosen by provisional status. due = first occurrence STRICTLY
    # AFTER period_end (January deadlines land in the following calendar year), forward-
    # rolled off weekends / SA public holidays.
    deadline = get_itr12_deadline(client.has_provisional_tax)
    due_raw = _day_month_in_year(period_end.year, deadline.month, deadline.day)
    if due_raw <= period_end:
        due_raw = _day_month_in_year(period_end.year + 1, deadline.month, deadline.day)
    due = shift_to_next_business_day(due_raw)

    return [
        ObligationInstance(
            client_id=client.id,
            obligation_type=ObligationType.ITR12,
            period_start=period_start,
            period_end=period_end,
            submission_due_date=due,
            payment_due_date=due,
            # Set explicitly so callers see PENDING on un-committed instances.
            status=ObligationStatus.PENDING,
        )
    ]
