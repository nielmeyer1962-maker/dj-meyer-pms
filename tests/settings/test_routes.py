from __future__ import annotations

from app.extensions import db
from app.models.app_setting import (
    APP_SETTING_SEED,
    KEY_ITR12_NONPROVISIONAL_DAY,
    KEY_ITR12_PROVISIONAL_MONTH,
    AppSetting,
)


def _seed_settings() -> None:
    for row in APP_SETTING_SEED:
        db.session.add(AppSetting(**row))
    db.session.commit()


def _value(key: str) -> str | None:
    row = db.session.scalar(db.select(AppSetting).where(AppSetting.key == key))
    return row.value if row else None


def test_get_renders_current_values(app, client):
    """The form repaints the stored deadlines (seeded 23 Oct / 20 Jan)."""
    with app.app_context():
        _seed_settings()
    resp = client.get("/settings/")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "ITR12 filing deadlines" in body
    assert 'value="23"' in body  # non-provisional day
    assert 'value="20"' in body  # provisional day


def test_get_renders_defaults_when_unseeded(app, client):
    """Even on a DB without the seed rows, the page renders the seeded defaults rather
    than 500-ing."""
    resp = client.get("/settings/")
    assert resp.status_code == 200
    assert 'value="23"' in resp.data.decode()


def test_post_valid_updates_settings(app, client):
    with app.app_context():
        _seed_settings()
    resp = client.post(
        "/settings/",
        data={
            "nonprovisional_day": "31",
            "nonprovisional_month": "10",
            "provisional_day": "15",
            "provisional_month": "2",
        },
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/settings/")
    with app.app_context():
        assert _value(KEY_ITR12_NONPROVISIONAL_DAY) == "31"
        assert _value(KEY_ITR12_PROVISIONAL_MONTH) == "2"


def test_post_creates_rows_when_unseeded(app, client):
    """A first save on an unseeded DB inserts the rows (upsert)."""
    resp = client.post(
        "/settings/",
        data={
            "nonprovisional_day": "23",
            "nonprovisional_month": "10",
            "provisional_day": "20",
            "provisional_month": "1",
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        assert _value(KEY_ITR12_NONPROVISIONAL_DAY) == "23"


def test_post_invalid_day_rerenders_with_error_no_write(app, client):
    """An out-of-range day fails server-side validation: re-render (200) with an error,
    and the stored value is unchanged."""
    with app.app_context():
        _seed_settings()
    resp = client.post(
        "/settings/",
        data={
            "nonprovisional_day": "99",  # out of 1-31
            "nonprovisional_month": "10",
            "provisional_day": "20",
            "provisional_month": "1",
        },
    )
    assert resp.status_code == 200
    assert "is-invalid" in resp.data.decode()
    with app.app_context():
        assert _value(KEY_ITR12_NONPROVISIONAL_DAY) == "23"  # unchanged


def test_post_invalid_month_rerenders_with_error(app, client):
    with app.app_context():
        _seed_settings()
    resp = client.post(
        "/settings/",
        data={
            "nonprovisional_day": "23",
            "nonprovisional_month": "13",  # out of 1-12
            "provisional_day": "20",
            "provisional_month": "1",
        },
    )
    assert resp.status_code == 200
    assert "is-invalid" in resp.data.decode()
