"""CIPC Annual Return deadline logic — ENTITY-TYPE DEPENDENT.

Authoritative source (user-verified vs CIPC, 2026): CIPC Annual Returns Information
Guide / FAQ, https://annualreturns.cipc.co.za/.

  - Companies (Pty Ltd, INC, NPC): the Annual Return is due within 30 BUSINESS days
    after the anniversary of the incorporation date.
  - Close corporations (CC): due the last day of the month FOLLOWING the anniversary
    month (the filing window runs from the first day of the anniversary month to the
    end of the following month).

Only entity types that actually file a CIPC AR are accepted; anything else raises
ValueError so a mis-gated caller fails loudly rather than inventing a deadline.
"""

from __future__ import annotations

import calendar
from datetime import date

from app.models.client import EntityType
from app.utils.business_days import add_business_days

# Entity types that file a CIPC Annual Return on the COMPANY rule (30 business days
# after the anniversary). CC is handled separately by the month-end rule.
_COMPANY_TYPES = frozenset({EntityType.PTY_LTD, EntityType.INC, EntityType.NPC})

# Business days after the incorporation anniversary for the company deadline.
_COMPANY_DUE_BUSINESS_DAYS = 30


def _last_day_of_following_month(anniversary: date) -> date:
    """Last calendar day of the month after the anniversary month (CC rule)."""
    if anniversary.month == 12:
        year, month = anniversary.year + 1, 1
    else:
        year, month = anniversary.year, anniversary.month + 1
    _, last_day = calendar.monthrange(year, month)
    return date(year, month, last_day)


def cipc_ar_due_date(entity_type: EntityType, anniversary: date) -> date:
    """CIPC Annual Return deadline for the given entity type and incorporation
    anniversary (the anniversary date falling in the relevant filing year).

    Companies (Pty Ltd / INC / NPC): 30 business days after the anniversary.
    Close corporations: the last calendar day of the month following the anniversary
    month — not business-day adjusted, per the CIPC CC rule as published.

    Raises ValueError for entity types that do not file a CIPC AR.
    """
    if entity_type in _COMPANY_TYPES:
        return add_business_days(anniversary, _COMPANY_DUE_BUSINESS_DAYS)
    if entity_type is EntityType.CC:
        return _last_day_of_following_month(anniversary)
    raise ValueError(f"{entity_type.name} does not file a CIPC annual return")
