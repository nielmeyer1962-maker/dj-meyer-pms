"""Generic application settings store — a flat key/value table for global, editable
configuration that isn't tied to a domain row (e.g. statutory filing deadlines).

Values are stored as strings; typed reads + validation live in the service layer
(app.services.settings). Defaults are seeded from APP_SETTING_SEED by migration — the
same single-source-of-truth discipline as CIPC_AR_FEE_SEED, so the migration and the
tests cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Unique business key (e.g. "itr12_provisional_deadline_day"); the value is free text
    # interpreted by the reader (int, date parts, etc.).
    key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)

    def __repr__(self) -> str:
        return f"<AppSetting {self.key}={self.value!r}>"


# --- ITR12 statutory filing deadlines, stored as day + month -------------------------
# Setting keys, centralised so the reader and the settings page can't typo the string.
KEY_ITR12_NONPROVISIONAL_DAY = "itr12_nonprovisional_deadline_day"
KEY_ITR12_NONPROVISIONAL_MONTH = "itr12_nonprovisional_deadline_month"
KEY_ITR12_PROVISIONAL_DAY = "itr12_provisional_deadline_day"
KEY_ITR12_PROVISIONAL_MONTH = "itr12_provisional_deadline_month"


@dataclass(frozen=True)
class DeadlineDM:
    """A day-of-month + month pair, validated on construction (day 1-31, month 1-12).

    Deliberately not calendar-aware (no year): a deadline like "23 October" is a recurring
    day+month. The generator combines it with a concrete year. Day 1-31 is a range check,
    not a per-month length check — the generator clamps when it lands the date in a year.
    """

    day: int
    month: int

    def __post_init__(self) -> None:
        if not 1 <= self.day <= 31:
            raise ValueError(f"deadline day must be 1-31, got {self.day}")
        if not 1 <= self.month <= 12:
            raise ValueError(f"deadline month must be 1-12, got {self.month}")


# User-confirmed defaults: non-provisional individuals file ITR12 by 23 October; those
# registered for provisional tax (client.has_provisional_tax) by 20 January. SARS filing-
# season dates are set by annual notice — re-verify on change; editable via the settings
# page (chunk 4).
DEFAULT_ITR12_NONPROVISIONAL = DeadlineDM(day=23, month=10)
DEFAULT_ITR12_PROVISIONAL = DeadlineDM(day=20, month=1)

# Canonical seed — the single source of truth imported by BOTH the seeding migration and
# the tests so they cannot drift. Generic store, so values are strings.
APP_SETTING_SEED: list[dict[str, str]] = [
    {"key": KEY_ITR12_NONPROVISIONAL_DAY, "value": str(DEFAULT_ITR12_NONPROVISIONAL.day)},
    {"key": KEY_ITR12_NONPROVISIONAL_MONTH, "value": str(DEFAULT_ITR12_NONPROVISIONAL.month)},
    {"key": KEY_ITR12_PROVISIONAL_DAY, "value": str(DEFAULT_ITR12_PROVISIONAL.day)},
    {"key": KEY_ITR12_PROVISIONAL_MONTH, "value": str(DEFAULT_ITR12_PROVISIONAL.month)},
]
