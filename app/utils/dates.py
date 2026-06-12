from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

# The firm operates in Africa/Johannesburg. All stored timestamps remain UTC tz-aware;
# this module exists so any "today" comparison against a SARS/CIPC deadline shifts to
# SAST in exactly one place. A deadline reached at 23:59 SAST is not overdue at 22:00
# UTC the next day.
_SAST = ZoneInfo("Africa/Johannesburg")


def today_sast() -> date:
    return datetime.now(_SAST).date()


def to_sast(dt: datetime) -> datetime:
    """Convert a stored timestamp to SAST for display. Postgres returns tz-aware UTC;
    SQLite drops the tzinfo, so a naive value is assumed to be UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(_SAST)
