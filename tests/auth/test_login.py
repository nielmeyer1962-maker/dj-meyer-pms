from __future__ import annotations

from app.extensions import db
from app.models.staff import Staff, StaffRole

PW = "correct-horse-battery"


def _staff(*, email="user@test.local", active=True, with_password=True, code="USR") -> Staff:
    s = Staff(code=code, full_name="A User", email=email, role=StaffRole.TAX, active=active)
    if with_password:
        s.set_password(PW)
    db.session.add(s)
    db.session.commit()
    return s


# --- the login wall ---


def test_anonymous_request_redirects_to_login(anon_client):
    resp = anon_client.get("/dashboard/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_health_route_stays_public(anon_client):
    """'/' remains the bare health line, reachable without login."""
    resp = anon_client.get("/")
    assert resp.status_code == 200
    assert b"ok" in resp.data


def test_login_page_is_public(anon_client):
    assert anon_client.get("/login").status_code == 200


# --- credentials ---


def test_valid_login_redirects_to_dashboard(app, anon_client):
    with app.app_context():
        _staff()
    resp = anon_client.post("/login", data={"email": "user@test.local", "password": PW})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard/")


def test_bad_password_rejected(app, anon_client):
    with app.app_context():
        _staff()
    resp = anon_client.post(
        "/login", data={"email": "user@test.local", "password": "wrong"}, follow_redirects=True
    )
    assert resp.status_code == 200
    assert b"Invalid email or password." in resp.data
    # still anonymous → a guarded page bounces to login
    assert "/login" in anon_client.get("/dashboard/").headers["Location"]


def test_unknown_email_rejected_with_same_message(app, anon_client):
    resp = anon_client.post(
        "/login", data={"email": "nobody@test.local", "password": PW}, follow_redirects=True
    )
    assert b"Invalid email or password." in resp.data


def test_inactive_staff_rejected(app, anon_client):
    with app.app_context():
        _staff(email="gone@test.local", active=False, code="OLD")
    resp = anon_client.post(
        "/login", data={"email": "gone@test.local", "password": PW}, follow_redirects=True
    )
    assert b"Invalid email or password." in resp.data


def test_staff_without_password_hash_rejected(app, anon_client):
    with app.app_context():
        _staff(email="nohash@test.local", with_password=False, code="NOH")
    resp = anon_client.post(
        "/login", data={"email": "nohash@test.local", "password": PW}, follow_redirects=True
    )
    assert b"Invalid email or password." in resp.data


# --- logout ---


def test_logout_ends_session(client):
    """The authenticated `client` can reach the dashboard, then logout bounces future
    requests back to the login wall."""
    assert client.get("/dashboard/").status_code == 200
    resp = client.post("/logout")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert "/login" in client.get("/dashboard/").headers["Location"]
