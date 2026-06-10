from __future__ import annotations

import calendar
from datetime import date, timedelta

import holidays

# Lazy module-level cache: year -> frozen set of SA public holiday dates for that year.
# Populated on first access per year and never invalidated within process lifetime.
# Querying multiple years (e.g. a 12-month window crossing a year boundary) hits two
# entries, not one shared mutable set — avoids cross-year pollution.
_HOLIDAY_CACHE: dict[int, set[date]] = {}


def _holidays_for(year: int) -> set[date]:
    cached = _HOLIDAY_CACHE.get(year)
    if cached is None:
        # holidays.country_holidays("ZA", years=year) precomputes the year's set;
        # taking .keys() forces materialisation and gives us plain date objects.
        cached = set(holidays.country_holidays("ZA", years=year).keys())
        _HOLIDAY_CACHE[year] = cached
    return cached


def is_business_day(d: date) -> bool:
    if d.weekday() >= 5:  # Saturday (5) or Sunday (6)
        return False
    return d not in _holidays_for(d.year)


def last_business_day_of_month(year: int, month: int) -> date:
    _, last_day = calendar.monthrange(year, month)
    return shift_to_prior_business_day(date(year, month, last_day))


def add_business_days(start: date, n: int) -> date:
    """Return the date n business days strictly AFTER start.

    The start date itself is never counted, so add_business_days(Friday, 1) is the
    following Monday. Weekends and SA public holidays are skipped. Used by the CIPC
    Annual Return company deadline (30 business days after the incorporation
    anniversary). Counterpart to shift_to_prior_business_day, which rolls backward.

    n must be >= 1. Bounded defensively: 30 business days never spans more than ~50
    calendar days even across a holiday-dense stretch, so the cap signals a bug or a
    holiday-data problem rather than ever tripping in normal use.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    d = start
    added = 0
    for _ in range(n * 2 + 30):
        d += timedelta(days=1)
        if is_business_day(d):
            added += 1
            if added == n:
                return d
    raise RuntimeError(
        f"add_business_days exceeded its iteration bound adding {n} business days to "
        f"{start.isoformat()} (now at {d.isoformat()}); check holiday data."
    )


def shift_to_prior_business_day(d: date) -> date:
    """Walk backwards day-by-day until d is a business day.

    Bounded at 14 iterations defensively — signals a bug or a holiday-data problem
    if exceeded (no real-world weekend-plus-holidays run reaches that length).
    """
    original = d
    for _ in range(14):
        if is_business_day(d):
            return d
        d -= timedelta(days=1)
    raise RuntimeError(
        f"shift_to_prior_business_day exceeded 14 iterations starting from "
        f"{original.isoformat()} (now at {d.isoformat()}); check holiday data."
    )


def shift_to_next_business_day(d: date) -> date:
    """Walk forwards day-by-day until d is a business day.

    Returns d unchanged if it is already a business day; otherwise rolls FORWARD
    to the next business day. Mirror of shift_to_prior_business_day (used where a
    deadline that lands on a weekend/SA public holiday moves to the next working
    day rather than the prior one). Bounded at 14 iterations defensively.
    """
    original = d
    for _ in range(14):
        if is_business_day(d):
            return d
        d += timedelta(days=1)
    raise RuntimeError(
        f"shift_to_next_business_day exceeded 14 iterations starting from "
        f"{original.isoformat()} (now at {d.isoformat()}); check holiday data."
    )
