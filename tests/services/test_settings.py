import pytest

from app.extensions import db
from app.models.app_setting import APP_SETTING_SEED, AppSetting, DeadlineDM
from app.services.settings import get_itr12_deadline, get_setting, get_setting_int


def _seed(app):
    """Seed the AppSetting table from the canonical APP_SETTING_SEED (tests build the DB
    with create_all, which does not run the seeding migration)."""
    for row in APP_SETTING_SEED:
        db.session.add(AppSetting(**row))
    db.session.commit()


def test_get_setting_returns_value(app):
    with app.app_context():
        _seed(app)
        assert get_setting("itr12_nonprovisional_deadline_day") == "23"


def test_get_setting_int_parses(app):
    with app.app_context():
        _seed(app)
        assert get_setting_int("itr12_provisional_deadline_month") == 1


def test_get_setting_raises_keyerror_when_unset(app):
    with app.app_context():
        with pytest.raises(KeyError):
            get_setting("does_not_exist")


def test_get_itr12_deadline_non_provisional(app):
    """A non-provisional individual files by 23 October."""
    with app.app_context():
        _seed(app)
        assert get_itr12_deadline(provisional=False) == DeadlineDM(day=23, month=10)


def test_get_itr12_deadline_provisional(app):
    """A provisional individual files by 20 January."""
    with app.app_context():
        _seed(app)
        assert get_itr12_deadline(provisional=True) == DeadlineDM(day=20, month=1)
