from datetime import date

import pytest

from app.models.client import EntityType
from app.services.cipc.due_dates import cipc_ar_due_date

# --- Company rule: 30 business days after the anniversary (Pty Ltd / INC / NPC) ---


@pytest.mark.parametrize("entity_type", [EntityType.PTY_LTD, EntityType.INC, EntityType.NPC])
def test_company_due_30_business_days_clean_span(entity_type):
    """Thu 2026-01-15 anniversary → Thu 2026-02-26 (30 business days, no holiday in span).
    All three company types share the rule."""
    assert cipc_ar_due_date(entity_type, date(2026, 1, 15)) == date(2026, 2, 26)


def test_company_due_30_business_days_across_holidays():
    """Mon 2026-03-16 anniversary → Thu 2026-04-30: Good Friday, Family Day and Freedom
    Day each fall in the 30-business-day span and push the deadline out."""
    assert cipc_ar_due_date(EntityType.PTY_LTD, date(2026, 3, 16)) == date(2026, 4, 30)


# --- CC rule: last day of the month following the anniversary month ---


def test_cc_due_last_day_of_following_month():
    """CC, anniversary in March → last day of April = 30 Apr 2026 (calendar, not
    business-day adjusted)."""
    assert cipc_ar_due_date(EntityType.CC, date(2026, 3, 15)) == date(2026, 4, 30)


def test_cc_due_following_month_year_rollover():
    """CC, anniversary in December → last day of the following January = 31 Jan 2027."""
    assert cipc_ar_due_date(EntityType.CC, date(2026, 12, 10)) == date(2027, 1, 31)


def test_cc_due_following_month_is_february():
    """CC, anniversary in January → last day of February (28 in non-leap 2026)."""
    assert cipc_ar_due_date(EntityType.CC, date(2026, 1, 20)) == date(2026, 2, 28)


# --- Non-filing entity types raise ---


@pytest.mark.parametrize(
    "entity_type",
    [EntityType.INDIVIDUAL, EntityType.SOLE_PROP, EntityType.TRUST, EntityType.PARTNERSHIP],
)
def test_non_filing_entity_types_raise(entity_type):
    """Entity types that do not file a CIPC AR raise rather than inventing a deadline."""
    with pytest.raises(ValueError):
        cipc_ar_due_date(entity_type, date(2026, 3, 15))
