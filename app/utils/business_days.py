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
