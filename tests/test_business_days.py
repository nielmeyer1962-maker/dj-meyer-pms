from datetime import date

import holidays

from app.utils import business_days

# --- Sanity check: the holidays package returns expected SA holidays ---


def test_freedom_day_2026_is_in_za_holidays():
    """27 April 2026 is Freedom Day per the holidays package."""
    sa = holidays.country_holidays("ZA")
    assert "Freedom Day" in sa[date(2026, 4, 27)]


def test_womens_day_2026_observed_on_monday():
    """9 Aug 2026 is a Sunday → Women's Day is observed Mon 10 Aug per Public Holidays Act §2(1)."""
    sa = holidays.country_holidays("ZA")
    assert "Women's Day (observed)" in sa[date(2026, 8, 10)]


# --- is_business_day ---


def test_is_business_day_saturday_false():
    """30 May 2026 is a Saturday."""
    assert business_days.is_business_day(date(2026, 5, 30)) is False


def test_is_business_day_sunday_false():
    """31 May 2026 is a Sunday."""
    assert business_days.is_business_day(date(2026, 5, 31)) is False


def test_is_business_day_christmas_friday_false():
    """25 Dec 2026 is a Friday, but Christmas Day — not a business day."""
    assert business_days.is_business_day(date(2026, 12, 25)) is False


def test_is_business_day_normal_tuesday_true():
    """26 May 2026 is a normal Tuesday."""
    assert business_days.is_business_day(date(2026, 5, 26)) is True


# --- last_business_day_of_month ---


def test_last_business_day_of_may_2026():
    """31 May 2026 is Sun, 30 May Sat → last business day is Fri 29 May."""
    assert business_days.last_business_day_of_month(2026, 5) == date(2026, 5, 29)


def test_last_business_day_of_april_2026():
    """30 April 2026 is Thursday and not a holiday — last day is itself."""
    assert business_days.last_business_day_of_month(2026, 4) == date(2026, 4, 30)


def test_last_business_day_of_january_2026():
    """31 Jan 2026 is Saturday → last business day is Fri 30 Jan."""
    assert business_days.last_business_day_of_month(2026, 1) == date(2026, 1, 30)


# --- shift_to_prior_business_day ---


def test_shift_christmas_2026_to_christmas_eve():
    """Christmas Day 2026 (Friday) → Thursday 24 Dec."""
    assert business_days.shift_to_prior_business_day(date(2026, 12, 25)) == date(2026, 12, 24)


def test_shift_sunday_2026_01_25_to_friday():
    """25 Jan 2026 is Sun → 24 Jan Sat → 23 Jan Fri."""
    assert business_days.shift_to_prior_business_day(date(2026, 1, 25)) == date(2026, 1, 23)


# --- shift_to_next_business_day ---


def test_shift_next_saturday_2026_05_30_to_monday():
    """30 May 2026 is Sat → 31 May Sun → Mon 1 Jun (a business day)."""
    assert business_days.shift_to_next_business_day(date(2026, 5, 30)) == date(2026, 6, 1)


def test_shift_next_sunday_2026_05_31_to_monday():
    """31 May 2026 is Sun → Mon 1 Jun."""
    assert business_days.shift_to_next_business_day(date(2026, 5, 31)) == date(2026, 6, 1)


def test_shift_next_freedom_day_2026_to_tuesday():
    """27 Apr 2026 (Mon) is Freedom Day → Tue 28 Apr (next business day)."""
    assert business_days.shift_to_next_business_day(date(2026, 4, 27)) == date(2026, 4, 28)


def test_shift_next_plain_business_day_unchanged():
    """26 May 2026 is a normal Tuesday → returned unchanged."""
    assert business_days.shift_to_next_business_day(date(2026, 5, 26)) == date(2026, 5, 26)


# --- Holiday cache ---


def test_holiday_cache_populates_once_per_year():
    """Cache stores the year's holiday set on first access; second call reuses the object."""
    business_days._HOLIDAY_CACHE.clear()

    business_days.last_business_day_of_month(2026, 5)
    assert 2026 in business_days._HOLIDAY_CACHE
    cached_set = business_days._HOLIDAY_CACHE[2026]

    # Second call for the same year must reuse the cached set object, not rebuild it.
    business_days.last_business_day_of_month(2026, 6)
    assert business_days._HOLIDAY_CACHE[2026] is cached_set


# --- add_business_days (forward counter; CIPC company deadline) ---


def test_add_business_days_friday_plus_one_is_monday():
    """Start is never counted: Fri 2026-03-13 + 1 business day = Mon 2026-03-16."""
    assert business_days.add_business_days(date(2026, 3, 13), 1) == date(2026, 3, 16)


def test_add_business_days_skips_public_holiday():
    """Fri 2026-04-24 + 1 bd skips the weekend and Mon 27 Apr (Freedom Day) → Tue 28."""
    assert business_days.add_business_days(date(2026, 4, 24), 1) == date(2026, 4, 28)


def test_add_business_days_30_no_holidays_in_span():
    """Thu 2026-01-15 + 30 bd = Thu 2026-02-26 (six clean weeks, no SA holiday between)."""
    assert business_days.add_business_days(date(2026, 1, 15), 30) == date(2026, 2, 26)


def test_add_business_days_30_across_easter_and_freedom_day():
    """Mon 2026-03-16 + 30 bd = Thu 2026-04-30: the span crosses Good Friday (3 Apr),
    Family Day (6 Apr) and Freedom Day (27 Apr), each pushing the count out a day."""
    assert business_days.add_business_days(date(2026, 3, 16), 30) == date(2026, 4, 30)


def test_add_business_days_rejects_non_positive():
    import pytest

    for bad in (0, -1):
        with pytest.raises(ValueError):
            business_days.add_business_days(date(2026, 1, 15), bad)
