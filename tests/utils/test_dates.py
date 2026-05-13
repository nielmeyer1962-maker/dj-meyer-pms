from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import patch

from app.utils.dates import today_sast


def test_today_sast_returns_date():
    assert isinstance(today_sast(), date)


def test_today_sast_uses_sast_not_utc_around_midnight():
    """SAST is UTC+2. An instant at 21:59 UTC is still the previous day in UTC at
    23:59 SAST, but 22:01 UTC is already 00:01 SAST the next day. Guards against
    the easy mistake of reading datetime.utcnow().date() everywhere."""
    before_midnight_utc = datetime(2026, 5, 13, 21, 59, tzinfo=UTC)
    after_midnight_utc = datetime(2026, 5, 13, 22, 1, tzinfo=UTC)

    with patch("app.utils.dates.datetime") as mock_dt:
        mock_dt.now.return_value = before_midnight_utc.astimezone(
            __import__("app.utils.dates", fromlist=["_SAST"])._SAST
        )
        assert today_sast() == date(2026, 5, 13)

    with patch("app.utils.dates.datetime") as mock_dt:
        mock_dt.now.return_value = after_midnight_utc.astimezone(
            __import__("app.utils.dates", fromlist=["_SAST"])._SAST
        )
        assert today_sast() == date(2026, 5, 14)
