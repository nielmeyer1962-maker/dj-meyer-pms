from __future__ import annotations

from app.extensions import db
from app.models.client import Client, EntityType

# A non-admin turned away from any admin-only route sees this flash (see
# app.auth.decorators.ADMIN_REQUIRED_MESSAGE) and is redirected, rather than hitting a 403.
_DENIED_FLASH = b"You need admin rights to do that."


# --- Settings blueprint is admin-only (whole blueprint) ---


def test_non_admin_settings_redirects_with_flash(client):
    resp = client.get("/settings/")
    assert resp.status_code == 302  # redirect, not a bare 403
    resp = client.get("/settings/", follow_redirects=True)
    assert resp.status_code == 200
    assert _DENIED_FLASH in resp.data


def test_admin_settings_allowed(admin_client):
    assert admin_client.get("/settings/").status_code == 200


# --- client archive is admin-only ---


def _make_client_row() -> Client:
    c = Client(legal_name="Archive Me Pty Ltd", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    return c


def test_non_admin_archive_redirects_with_flash(app, client):
    with app.app_context():
        c = _make_client_row()
        cid = c.id
    resp = client.post(f"/clients/{cid}/archive", follow_redirects=True)
    assert resp.status_code == 200
    assert _DENIED_FLASH in resp.data
    with app.app_context():
        assert db.session.get(Client, cid).active is True  # unchanged


def test_admin_archive_allowed(app, admin_client):
    with app.app_context():
        c = _make_client_row()
        cid = c.id
    resp = admin_client.post(f"/clients/{cid}/archive")
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Client, cid).active is False


# --- the Archive button itself is hidden from non-admins (matches the route guard) ---


def test_non_admin_does_not_see_archive_button(app, client):
    with app.app_context():
        c = _make_client_row()
        cid = c.id
    body = client.get("/clients/").data.decode()
    assert f"/clients/{cid}/archive" not in body


def test_admin_sees_archive_button(app, admin_client):
    with app.app_context():
        c = _make_client_row()
        cid = c.id
    body = admin_client.get("/clients/").data.decode()
    assert f"/clients/{cid}/archive" in body


# --- navbar hides the Settings link for non-admins ---


def test_navbar_hides_settings_for_non_admin(client):
    body = client.get("/dashboard/").data.decode()
    assert "/settings/" not in body


def test_navbar_shows_settings_for_admin(admin_client):
    body = admin_client.get("/dashboard/").data.decode()
    assert "/settings/" in body
