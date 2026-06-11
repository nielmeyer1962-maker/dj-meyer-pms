"""Typed reads over the generic AppSetting key/value store.

The model stores strings; callers want ints, deadlines, etc. These helpers centralise the
parsing/validation so the rest of the app never touches raw AppSetting rows. No Flask here
— pure data access, like the other service modules.
"""

from __future__ import annotations

from app.extensions import db
from app.models.app_setting import (
    KEY_ITR12_NONPROVISIONAL_DAY,
    KEY_ITR12_NONPROVISIONAL_MONTH,
    KEY_ITR12_PROVISIONAL_DAY,
    KEY_ITR12_PROVISIONAL_MONTH,
    AppSetting,
    DeadlineDM,
)


def get_setting(key: str) -> str:
    """Return the stored string value for key. Raises KeyError if the key is unset."""
    row = db.session.scalar(db.select(AppSetting).where(AppSetting.key == key))
    if row is None:
        raise KeyError(f"app setting {key!r} is not set")
    return row.value


def get_setting_int(key: str) -> int:
    return int(get_setting(key))


def set_setting(key: str, value: str) -> None:
    """Upsert a setting: update the row if the key exists, else insert it. The caller owns
    the commit."""
    row = db.session.scalar(db.select(AppSetting).where(AppSetting.key == key))
    if row is None:
        db.session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def get_itr12_deadline(provisional: bool) -> DeadlineDM:
    """The ITR12 filing deadline as a validated day+month, chosen by whether the individual
    is registered for provisional tax (client.has_provisional_tax). Provisional → January,
    else → October. Read from AppSetting so the firm can adjust it via the settings page."""
    if provisional:
        return DeadlineDM(
            day=get_setting_int(KEY_ITR12_PROVISIONAL_DAY),
            month=get_setting_int(KEY_ITR12_PROVISIONAL_MONTH),
        )
    return DeadlineDM(
        day=get_setting_int(KEY_ITR12_NONPROVISIONAL_DAY),
        month=get_setting_int(KEY_ITR12_NONPROVISIONAL_MONTH),
    )
