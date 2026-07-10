import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.app_setting import (
    APP_SETTING_SEED,
    KEY_ITR12_NONPROVISIONAL_DAY,
    KEY_ITR12_NONPROVISIONAL_MONTH,
    KEY_ITR12_PROVISIONAL_DAY,
    KEY_ITR12_PROVISIONAL_MONTH,
    AppSetting,
    DeadlineDM,
)

# --- AppSetting model ---


def test_app_setting_persists_and_round_trips(app):
    with app.app_context():
        db.session.add(AppSetting(key="some_key", value="some_value"))
        db.session.commit()
        row = db.session.scalar(db.select(AppSetting).where(AppSetting.key == "some_key"))
        assert row.value == "some_value"


def test_app_setting_key_is_unique(app):
    with app.app_context():
        db.session.add(AppSetting(key="dup", value="a"))
        db.session.commit()
        db.session.add(AppSetting(key="dup", value="b"))
        with pytest.raises(IntegrityError):
            db.session.commit()


# --- DeadlineDM validation ---


def test_deadline_dm_accepts_valid_day_month():
    d = DeadlineDM(day=23, month=10)
    assert (d.day, d.month) == (23, 10)


@pytest.mark.parametrize("day", [0, 32, -1])
def test_deadline_dm_rejects_out_of_range_day(day):
    with pytest.raises(ValueError):
        DeadlineDM(day=day, month=10)


@pytest.mark.parametrize("month", [0, 13, -1])
def test_deadline_dm_rejects_out_of_range_month(month):
    with pytest.raises(ValueError):
        DeadlineDM(day=23, month=month)


# --- Seed constant: the single source of truth ---


def test_app_setting_seed_has_the_four_itr12_deadline_keys():
    seeded = {row["key"]: row["value"] for row in APP_SETTING_SEED}
    assert seeded == {
        KEY_ITR12_NONPROVISIONAL_DAY: "23",
        KEY_ITR12_NONPROVISIONAL_MONTH: "10",
        KEY_ITR12_PROVISIONAL_DAY: "20",
        KEY_ITR12_PROVISIONAL_MONTH: "1",
    }


def test_app_setting_seed_keys_are_unique():
    keys = [row["key"] for row in APP_SETTING_SEED]
    assert len(keys) == len(set(keys))
