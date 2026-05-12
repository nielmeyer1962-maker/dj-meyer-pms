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
    assert business_days.shift_to_prior_business_day(date(2026, 12, 25)) == date(
        2026, 12, 24
    )


def test_shift_sunday_2026_01_25_to_friday():
    """25 Jan 2026 is Sun → 24 Jan Sat → 23 Jan Fri."""
    assert business_days.shift_to_prior_business_day(date(2026, 1, 25)) == date(
        2026, 1, 23
    )


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
