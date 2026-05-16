from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.models.staff import Staff, StaffRole

# Frozen "today" used everywhere a view filter or OVERDUE comparison needs it.
TODAY = date(2026, 5, 13)


# --- Fixtures: a small world with one client, two staff, four obligations ---


@pytest.fixture
def world(app):
    """Builds: client + (Niel, Tsego) + 4 obligations covering PENDING/SUBMITTED
    and a mix of past/today/future due dates. Returns int IDs only — never ORM
    objects — so tests can never trip on DetachedInstanceError from nested
    app_context blocks. The outer `app` fixture already holds an app_context
    open for the duration of the test."""
    c = Client(legal_name="Acme Pty Ltd", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    niel = Staff(code="NIEL", full_name="Niel Meyer", role=StaffRole.TAX)
    tsego = Staff(code="TSEGO", full_name="Tsego", role=StaffRole.SECRETARIAL)
    db.session.add_all([niel, tsego])
    db.session.commit()

    def _make(status, due, period_end, assignee_id=None):
        oi = ObligationInstance(
            client_id=c.id,
            obligation_type=ObligationType.VAT201,
            period_start=date(period_end.year, period_end.month, 1),
            period_end=period_end,
            submission_due_date=due,
            payment_due_date=due,
            status=status,
            assignee_id=assignee_id,
        )
        db.session.add(oi)
        return oi

    pending_overdue = _make(
        ObligationStatus.PENDING, TODAY - timedelta(days=5), date(2026, 1, 31), niel.id
    )
    pending_future = _make(
        ObligationStatus.PENDING, TODAY + timedelta(days=3), date(2026, 2, 28), tsego.id
    )
    submitted = _make(
        ObligationStatus.SUBMITTED, TODAY + timedelta(days=10), date(2026, 3, 31), niel.id
    )
    unassigned = _make(
        ObligationStatus.PENDING, TODAY + timedelta(days=20), date(2026, 4, 30), None
    )
    db.session.commit()
    return {
        "client_id": c.id,
        "niel_id": niel.id,
        "tsego_id": tsego.id,
        "pending_overdue_id": pending_overdue.id,
        "pending_future_id": pending_future.id,
        "submitted_id": submitted.id,
        "unassigned_id": unassigned.id,
    }


@pytest.fixture(autouse=True)
def _freeze_today():
    """today_sast() is patched in the dashboard route module for every test."""
    with patch("app.dashboard.routes.today_sast", return_value=TODAY):
        yield


# --- GET /dashboard/ — render + filters ---


def test_list_renders_200_and_includes_all_obligations(client, world):
    resp = client.get("/dashboard/")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Acme Pty Ltd" in body
    assert "OVERDUE" in body  # the pending_overdue row gets the badge


def test_filter_by_status_pending(client, world):
    resp = client.get("/dashboard/?status=PENDING")
    assert resp.status_code == 200
    body = resp.data.decode()
    # PENDING rows visible (3); SUBMITTED row excluded.
    # period_end dates are unique per row and absent from filter dropdowns.
    assert "2026-01-31" in body  # pending_overdue
    assert "2026-02-28" in body  # pending_future
    assert "2026-04-30" in body  # unassigned (also PENDING)
    assert "2026-03-31" not in body  # submitted row excluded


def test_filter_by_assignee_code(client, world):
    resp = client.get("/dashboard/?assignee=NIEL")
    assert resp.status_code == 200
    body = resp.data.decode()
    # Niel's rows: 2026-01-31 (pending_overdue) + 2026-03-31 (submitted)
    assert "2026-01-31" in body
    assert "2026-03-31" in body
    # Tsego's + unassigned rows excluded
    assert "2026-02-28" not in body
    assert "2026-04-30" not in body


def test_filter_by_assignee_unassigned_sentinel(client, world):
    resp = client.get("/dashboard/?assignee=__unassigned__")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Unassigned" in body
    # only the unassigned obligation should appear (period_end 2026-04-30)
    assert "2026-04-30" in body
    assert "2026-01-31" not in body  # pending_overdue (Niel's) excluded


def test_filter_view_overdue(client, world):
    resp = client.get("/dashboard/?view=overdue")
    assert resp.status_code == 200
    body = resp.data.decode()
    # only pending_overdue qualifies (PENDING + due < today)
    assert "2026-01-31" in body
    assert "2026-02-28" not in body
    assert "2026-03-31" not in body
    assert "2026-04-30" not in body


def test_filter_view_this_week(client, world):
    resp = client.get("/dashboard/?view=this_week")
    assert resp.status_code == 200
    body = resp.data.decode()
    # pending_future (due TODAY+3) qualifies; the +10 / +20 / past rows do not.
    assert "2026-02-28" in body
    assert "2026-01-31" not in body
    assert "2026-03-31" not in body
    assert "2026-04-30" not in body


# --- POST mark-* — legal + illegal transitions ---


def test_mark_submitted_on_pending_advances_and_redirects(client, world):
    resp = client.post(f"/dashboard/obligations/{world['pending_overdue_id']}/mark-submitted")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard/")
    oi = db.session.get(ObligationInstance, world["pending_overdue_id"])
    assert oi.status is ObligationStatus.SUBMITTED


def test_mark_submitted_on_submitted_flashes_no_change(client, world):
    submitted_id = world["submitted_id"]
    resp = client.post(
        f"/dashboard/obligations/{submitted_id}/mark-submitted", follow_redirects=True
    )
    assert resp.status_code == 200
    assert b"cannot mark_submitted" in resp.data
    oi = db.session.get(ObligationInstance, submitted_id)
    assert oi.status is ObligationStatus.SUBMITTED  # unchanged


def test_mark_paid_on_submitted_advances(client, world):
    submitted_id = world["submitted_id"]
    resp = client.post(f"/dashboard/obligations/{submitted_id}/mark-paid")
    assert resp.status_code == 302
    oi = db.session.get(ObligationInstance, submitted_id)
    assert oi.status is ObligationStatus.PAID


def test_mark_paid_on_pending_flashes(client, world):
    pending_id = world["pending_overdue_id"]
    resp = client.post(f"/dashboard/obligations/{pending_id}/mark-paid", follow_redirects=True)
    assert resp.status_code == 200
    assert b"cannot mark_paid" in resp.data


def test_mark_exempt_from_pending_and_submitted(client, world):
    p_id = world["pending_overdue_id"]
    s_id = world["submitted_id"]
    assert client.post(f"/dashboard/obligations/{p_id}/mark-exempt").status_code == 302
    assert client.post(f"/dashboard/obligations/{s_id}/mark-exempt").status_code == 302
    assert db.session.get(ObligationInstance, p_id).status is ObligationStatus.EXEMPT
    assert db.session.get(ObligationInstance, s_id).status is ObligationStatus.EXEMPT


# --- POST reassign ---


def test_reassign_to_valid_staff(client, world):
    oi_id = world["pending_overdue_id"]
    tsego_id = world["tsego_id"]
    resp = client.post(
        f"/dashboard/obligations/{oi_id}/reassign", data={"assignee_id": str(tsego_id)}
    )
    assert resp.status_code == 302
    oi = db.session.get(ObligationInstance, oi_id)
    assert oi.assignee_id == tsego_id


def test_reassign_to_unassigned_sets_null(client, world):
    oi_id = world["pending_overdue_id"]
    resp = client.post(f"/dashboard/obligations/{oi_id}/reassign", data={"assignee_id": ""})
    assert resp.status_code == 302
    oi = db.session.get(ObligationInstance, oi_id)
    assert oi.assignee_id is None


def test_reassign_to_nonexistent_staff_400(client, world):
    oi_id = world["pending_overdue_id"]
    resp = client.post(f"/dashboard/obligations/{oi_id}/reassign", data={"assignee_id": "9999"})
    assert resp.status_code == 400


def test_reassign_to_inactive_staff_400(client, world):
    oi_id = world["pending_overdue_id"]
    niel_id = world["niel_id"]
    s = db.session.get(Staff, niel_id)
    s.active = False
    db.session.commit()
    resp = client.post(
        f"/dashboard/obligations/{oi_id}/reassign",
        data={"assignee_id": str(niel_id)},
    )
    assert resp.status_code == 400


# --- Filter-state preservation across actions (locked decision §11) ---


def test_post_redirect_preserves_query_string(client, world):
    oi_id = world["pending_overdue_id"]
    resp = client.post(
        f"/dashboard/obligations/{oi_id}/mark-submitted?status=PENDING&assignee=NIEL"
    )
    assert resp.status_code == 302
    loc = resp.headers["Location"]
    assert "status=PENDING" in loc
    assert "assignee=NIEL" in loc


# --- CSRF: locally re-enabled for this one test ---


def test_post_without_csrf_token_rejected(app, world):
    """Per the recommended-and-approved approach: flip CSRF on for this test only,
    then assert a tokenless POST returns 400."""
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        c = app.test_client()
        oi_id = world["pending_overdue_id"]
        resp = c.post(f"/dashboard/obligations/{oi_id}/mark-submitted")
        assert resp.status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


# --- GET /dashboard/obligations/<id> — detail page (Ticket 3c §C2) ---


def test_detail_renders_200_with_obligation_data(client, world):
    """Detail page shows the obligation's key fields: status, dates, client, assignee."""
    oi_id = world["pending_overdue_id"]
    resp = client.get(f"/dashboard/obligations/{oi_id}")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Acme Pty Ltd" in body
    assert "2026-01-31" in body  # period_end of pending_overdue
    assert "VAT201" in body
    assert "PENDING" in body
    assert "NIEL" in body  # assignee


def test_detail_renders_overdue_badge_when_pending_and_past(client, world):
    """A PENDING row with submission_due_date < TODAY shows the OVERDUE badge —
    the same is_overdue() helper that drives the list-page badge."""
    oi_id = world["pending_overdue_id"]
    resp = client.get(f"/dashboard/obligations/{oi_id}")
    assert resp.status_code == 200
    assert b"OVERDUE" in resp.data


def test_detail_renders_unassigned_when_no_assignee(client, world):
    oi_id = world["unassigned_id"]
    resp = client.get(f"/dashboard/obligations/{oi_id}")
    assert resp.status_code == 200
    assert b"Unassigned" in resp.data


def test_detail_returns_404_for_nonexistent_id(client, world):
    resp = client.get("/dashboard/obligations/99999")
    assert resp.status_code == 404
