from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

# The firm operates in Africa/Johannesburg. All stored timestamps remain UTC tz-aware;
# this module exists so any "today" comparison against a SARS/CIPC deadline shifts to
# SAST in exactly one place. A deadline reached at 23:59 SAST is not overdue at 22:00
# UTC the next day.
_SAST = ZoneInfo("Africa/Johannesburg")


def today_sast() -> date:
    return datetime.now(_SAST).date()
