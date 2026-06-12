from __future__ import annotations

from app.extensions import db
from app.models.staff import Staff

# The authenticated `client` fixture logs in as auth@test.local with this password.
FIXTURE_PW = "fixture-password-123"


def _auth_staff() -> Staff:
    return db.session.scalar(db.select(Staff).where(Staff.email == "auth@test.local"))


def test_account_password_page_renders(client):
    assert client.get("/account/password").status_code == 200


def test_change_password_happy_path(app, client):
    resp = client.post(
        "/account/password",
        data={
            "current_password": FIXTURE_PW,
            "new_password": "brand-new-pw-99",
            "confirm_password": "brand-new-pw-99",
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        assert _auth_staff().check_password("brand-new-pw-99")


def test_wrong_current_password_rejected(app, client):
    resp = client.post(
        "/account/password",
        data={
            "current_password": "not-my-password",
            "new_password": "brand-new-pw-99",
            "confirm_password": "brand-new-pw-99",
        },
    )
    assert resp.status_code == 200
    assert b"Current password is incorrect." in resp.data
    with app.app_context():
        assert _auth_staff().check_password(FIXTURE_PW)  # unchanged


def test_short_new_password_rejected(client):
    resp = client.post(
        "/account/password",
        data={"current_password": FIXTURE_PW, "new_password": "short", "confirm_password": "short"},
    )
    assert resp.status_code == 200
    assert b"is-invalid" in resp.data


def test_mismatched_confirm_rejected(client):
    resp = client.post(
        "/account/password",
        data={
            "current_password": FIXTURE_PW,
            "new_password": "brand-new-pw-99",
            "confirm_password": "different-pw-99",
        },
    )
    assert resp.status_code == 200
    assert b"Passwords must match." in resp.data


def test_account_password_requires_login(anon_client):
    assert "/login" in anon_client.get("/account/password").headers["Location"]
