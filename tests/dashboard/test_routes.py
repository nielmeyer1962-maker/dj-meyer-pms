from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
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


def test_filter_window_overdue(client, world):
    resp = client.get("/dashboard/?window=overdue")
    assert resp.status_code == 200
    body = resp.data.decode()
    # only pending_overdue qualifies (PENDING + due < today)
    assert "2026-01-31" in body
    assert "2026-02-28" not in body
    assert "2026-03-31" not in body
    assert "2026-04-30" not in body


def test_filter_window_this_week(client, world):
    resp = client.get("/dashboard/?window=this_week")
    assert resp.status_code == 200
    body = resp.data.decode()
    # New semantics: "this week" = overdue OR due within 7 days. So pending_future
    # (due TODAY+3, 2026-02-28) AND the overdue row (2026-01-31) both qualify; the
    # +10 / +20 rows fall outside the window.
    assert "2026-02-28" in body
    assert "2026-01-31" in body  # overdue is folded into every forward window
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


# --- POST mark-in-progress / revert-to-pending (mark_in_progress feature) ---


def test_mark_in_progress_on_pending_advances_and_redirects(client, world):
    pending_id = world["pending_overdue_id"]
    resp = client.post(f"/dashboard/obligations/{pending_id}/mark-in-progress")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard/")
    oi = db.session.get(ObligationInstance, pending_id)
    assert oi.status is ObligationStatus.IN_PROGRESS


def test_mark_in_progress_on_submitted_flashes_no_change(client, world):
    submitted_id = world["submitted_id"]
    resp = client.post(
        f"/dashboard/obligations/{submitted_id}/mark-in-progress", follow_redirects=True
    )
    assert resp.status_code == 200
    assert b"cannot mark_in_progress" in resp.data
    oi = db.session.get(ObligationInstance, submitted_id)
    assert oi.status is ObligationStatus.SUBMITTED  # unchanged


def test_mark_submitted_on_in_progress_advances(client, world):
    """IN_PROGRESS is an accepted prior for mark_submitted (no detour via PENDING)."""
    oi_id = world["pending_overdue_id"]
    client.post(f"/dashboard/obligations/{oi_id}/mark-in-progress")
    resp = client.post(f"/dashboard/obligations/{oi_id}/mark-submitted")
    assert resp.status_code == 302
    assert db.session.get(ObligationInstance, oi_id).status is ObligationStatus.SUBMITTED


def test_revert_to_pending_on_in_progress_advances(client, world):
    oi_id = world["pending_overdue_id"]
    client.post(f"/dashboard/obligations/{oi_id}/mark-in-progress")
    resp = client.post(f"/dashboard/obligations/{oi_id}/revert-to-pending")
    assert resp.status_code == 302
    assert db.session.get(ObligationInstance, oi_id).status is ObligationStatus.PENDING


def test_revert_to_pending_on_pending_flashes_no_change(client, world):
    pending_id = world["pending_overdue_id"]
    resp = client.post(
        f"/dashboard/obligations/{pending_id}/revert-to-pending", follow_redirects=True
    )
    assert resp.status_code == 200
    assert b"cannot revert_to_pending" in resp.data
    assert db.session.get(ObligationInstance, pending_id).status is ObligationStatus.PENDING


def test_list_renders_start_button_on_pending_rows(client, world):
    """PENDING rows expose the Start (mark-in-progress) action."""
    resp = client.get("/dashboard/")
    body = resp.data.decode()
    pending_id = world["pending_overdue_id"]
    assert f"/dashboard/obligations/{pending_id}/mark-in-progress" in body
    assert ">Start<" in body


def test_list_renders_in_progress_actions(client, world):
    """An IN_PROGRESS row offers Mark submitted, Revert to pending and Mark exempt."""
    oi_id = world["pending_overdue_id"]
    client.post(f"/dashboard/obligations/{oi_id}/mark-in-progress")
    resp = client.get("/dashboard/")
    body = resp.data.decode()
    assert f"/dashboard/obligations/{oi_id}/revert-to-pending" in body
    assert "IN_PROGRESS" in body


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


# --- POST /dashboard/obligations/<id>/notes — notes save (Ticket 3c §C2) ---


def test_save_notes_with_non_empty_text_persists_and_redirects(client, world):
    """Happy path: non-empty notes persist, redirect to detail, success flash."""
    oi_id = world["pending_overdue_id"]
    resp = client.post(
        f"/dashboard/obligations/{oi_id}/notes",
        data={"notes": "Awaiting client signature on VAT201."},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/dashboard/obligations/{oi_id}")
    assert db.session.get(ObligationInstance, oi_id).notes == (
        "Awaiting client signature on VAT201."
    )


def test_save_notes_with_whitespace_only_persists_none(client, world):
    """Whitespace-only input becomes None — no empty-string rows in the DB."""
    oi_id = world["pending_overdue_id"]
    # Seed an existing note so we can confirm the wipe.
    client.post(f"/dashboard/obligations/{oi_id}/notes", data={"notes": "preset"})
    assert db.session.get(ObligationInstance, oi_id).notes == "preset"

    resp = client.post(
        f"/dashboard/obligations/{oi_id}/notes",
        data={"notes": "   \n\t "},
    )
    assert resp.status_code == 302
    assert db.session.get(ObligationInstance, oi_id).notes is None


def test_save_notes_over_4000_chars_rejects_with_form_error_no_db_write(client, world):
    """4001 chars fails server-side validation: re-render with inline error, no DB write."""
    oi_id = world["pending_overdue_id"]
    before = db.session.get(ObligationInstance, oi_id).notes
    resp = client.post(
        f"/dashboard/obligations/{oi_id}/notes",
        data={"notes": "a" * 4001},
    )
    # Re-renders the detail page (not a redirect).
    assert resp.status_code == 200
    body = resp.data.decode()
    # Bootstrap inline-error marker and WTForms Length default message.
    assert "is-invalid" in body
    assert "4000" in body  # WTForms Length default includes the limit
    # And the typed text survives the re-render so the user doesn't lose it.
    assert "a" * 4001 in body
    # DB unchanged.
    assert db.session.get(ObligationInstance, oi_id).notes == before


def test_save_notes_without_csrf_token_rejected(app, world):
    """POST /notes without a CSRF token returns 400 when CSRF is enabled."""
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        c = app.test_client()
        oi_id = world["pending_overdue_id"]
        resp = c.post(
            f"/dashboard/obligations/{oi_id}/notes",
            data={"notes": "anything"},
        )
        assert resp.status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


# --- next=detail round-trips (Ticket 3c §C2 MC4) ---


def test_mark_submitted_with_next_detail_redirects_to_detail(client, world):
    oi_id = world["pending_overdue_id"]
    resp = client.post(
        f"/dashboard/obligations/{oi_id}/mark-submitted",
        data={"next": "detail"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/dashboard/obligations/{oi_id}")


def test_mark_paid_with_next_detail_redirects_to_detail(client, world):
    oi_id = world["submitted_id"]
    resp = client.post(
        f"/dashboard/obligations/{oi_id}/mark-paid",
        data={"next": "detail"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/dashboard/obligations/{oi_id}")


def test_mark_exempt_with_next_detail_redirects_to_detail(client, world):
    oi_id = world["pending_overdue_id"]
    resp = client.post(
        f"/dashboard/obligations/{oi_id}/mark-exempt",
        data={"next": "detail"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/dashboard/obligations/{oi_id}")


def test_reassign_with_next_detail_redirects_to_detail(client, world):
    oi_id = world["pending_overdue_id"]
    tsego_id = world["tsego_id"]
    resp = client.post(
        f"/dashboard/obligations/{oi_id}/reassign",
        data={"assignee_id": str(tsego_id), "next": "detail"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/dashboard/obligations/{oi_id}")


# --- List page renders detail link per row (Ticket 3c §C2 MC4) ---


def test_list_renders_detail_link_for_each_row(client, world):
    """Every row's ID cell wraps the obligation id in an anchor pointing at the
    detail page — the entry point relied on by MC4's next=detail flow."""
    resp = client.get("/dashboard/")
    assert resp.status_code == 200
    body = resp.data.decode()
    for key in ("pending_overdue_id", "pending_future_id", "submitted_id", "unassigned_id"):
        oi_id = world[key]
        assert f'href="/dashboard/obligations/{oi_id}"' in body


# --- CIPC Annual Returns folded into the dashboard (chunk 5) ---


@pytest.fixture
def cipc_world(app):
    """A CIPC-only world: one client + Tsego + four CIPCAnnualInstances spanning the
    workflow and a mix of past/future due dates. Returns int IDs only (same discipline
    as `world`). Due dates are relative to the frozen TODAY."""
    c = Client(legal_name="Beta Holdings Pty Ltd", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    tsego = Staff(code="TSEGO", full_name="Tsego Mogale", role=StaffRole.SECRETARIAL)
    db.session.add(tsego)
    db.session.commit()

    def _mk(status, due, anniversary, assignee_id=None):
        inst = CIPCAnnualInstance(
            client_id=c.id,
            anniversary_date=anniversary,
            due_date=due,
            status=status,
            assignee_id=assignee_id,
        )
        db.session.add(inst)
        return inst

    generated_overdue = _mk(
        CIPCAnnualStatus.GENERATED, TODAY - timedelta(days=5), date(2025, 1, 10), tsego.id
    )
    invoiced_future = _mk(
        CIPCAnnualStatus.INVOICED, TODAY + timedelta(days=10), date(2025, 2, 10), tsego.id
    )
    ar_submitted_past = _mk(
        CIPCAnnualStatus.AR_SUBMITTED, TODAY - timedelta(days=2), date(2025, 3, 10), tsego.id
    )
    closed_unassigned = _mk(
        CIPCAnnualStatus.CLOSED, TODAY + timedelta(days=20), date(2025, 4, 10), None
    )
    db.session.commit()
    return {
        "client_id": c.id,
        "tsego_id": tsego.id,
        "generated_overdue_id": generated_overdue.id,
        "invoiced_future_id": invoiced_future.id,
        "ar_submitted_past_id": ar_submitted_past.id,
        "closed_unassigned_id": closed_unassigned.id,
    }


def test_list_includes_cipc_rows(client, cipc_world):
    resp = client.get("/dashboard/")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Beta Holdings Pty Ltd" in body
    assert "CIPC AR" in body
    # The generated row is past-due and pre-filing → OVERDUE badge.
    assert "OVERDUE" in body


def test_list_renders_cipc_action_buttons(client, cipc_world):
    """A GENERATED row exposes its forward transition plus the Service-declined off-ramp;
    CIPC rows have no detail anchor (no detail page yet)."""
    resp = client.get("/dashboard/")
    body = resp.data.decode()
    gid = cipc_world["generated_overdue_id"]
    assert f"/dashboard/cipc/{gid}/mark-invoiced" in body
    assert f"/dashboard/cipc/{gid}/mark-declined" in body
    assert "Service declined" in body
    assert f'href="/dashboard/obligations/{gid}"' not in body


def test_mark_cipc_invoiced_advances_and_redirects(client, cipc_world):
    gid = cipc_world["generated_overdue_id"]
    resp = client.post(f"/dashboard/cipc/{gid}/mark-invoiced")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard/")
    assert db.session.get(CIPCAnnualInstance, gid).status is CIPCAnnualStatus.INVOICED


def test_mark_cipc_invoiced_illegal_flashes_no_change(client, cipc_world):
    ar_id = cipc_world["ar_submitted_past_id"]
    resp = client.post(f"/dashboard/cipc/{ar_id}/mark-invoiced", follow_redirects=True)
    assert resp.status_code == 200
    assert b"cannot mark_invoiced" in resp.data
    assert db.session.get(CIPCAnnualInstance, ar_id).status is CIPCAnnualStatus.AR_SUBMITTED


def test_mark_cipc_declined_from_generated(client, cipc_world):
    gid = cipc_world["generated_overdue_id"]
    resp = client.post(f"/dashboard/cipc/{gid}/mark-declined")
    assert resp.status_code == 302
    assert db.session.get(CIPCAnnualInstance, gid).status is CIPCAnnualStatus.DECLINED


def test_mark_cipc_declined_illegal_once_filed(client, cipc_world):
    """AR already filed: the Service-declined off-ramp is closed."""
    ar_id = cipc_world["ar_submitted_past_id"]
    resp = client.post(f"/dashboard/cipc/{ar_id}/mark-declined", follow_redirects=True)
    assert resp.status_code == 200
    assert b"cannot mark_declined" in resp.data
    assert db.session.get(CIPCAnnualInstance, ar_id).status is CIPCAnnualStatus.AR_SUBMITTED


def test_mark_cipc_closed_from_ar_submitted(client, cipc_world):
    ar_id = cipc_world["ar_submitted_past_id"]
    resp = client.post(f"/dashboard/cipc/{ar_id}/mark-closed")
    assert resp.status_code == 302
    assert db.session.get(CIPCAnnualInstance, ar_id).status is CIPCAnnualStatus.CLOSED


def test_cipc_action_redirect_preserves_filters(client, cipc_world):
    gid = cipc_world["generated_overdue_id"]
    resp = client.post(f"/dashboard/cipc/{gid}/mark-invoiced?assignee=TSEGO&window=overdue")
    assert resp.status_code == 302
    loc = resp.headers["Location"]
    assert "assignee=TSEGO" in loc
    assert "window=overdue" in loc


def test_cipc_reassign_to_unassigned_sets_null(client, cipc_world):
    gid = cipc_world["generated_overdue_id"]
    resp = client.post(f"/dashboard/cipc/{gid}/reassign", data={"assignee_id": ""})
    assert resp.status_code == 302
    assert db.session.get(CIPCAnnualInstance, gid).assignee_id is None


def test_cipc_reassign_to_nonexistent_staff_400(client, cipc_world):
    gid = cipc_world["generated_overdue_id"]
    resp = client.post(f"/dashboard/cipc/{gid}/reassign", data={"assignee_id": "9999"})
    assert resp.status_code == 400


def test_status_filter_leaves_cipc_visible(client, cipc_world):
    """The Status filter narrows obligation rows ONLY — it never includes or excludes
    CIPC. With a CIPC row in the set, type=All & status=PENDING still returns the CIPC
    row. Asserts on a CIPC due-date string (a row-only marker)."""
    resp = client.get("/dashboard/?status=PENDING")
    assert resp.status_code == 200
    assert "2026-05-08" in resp.data.decode()  # generated_overdue due date, TODAY-5


def test_cipc_ar_ignores_status(client, cipc_world):
    """type=CIPC_AR shows the CIPC rows regardless of a stray Status value — never a blank
    list. CIPC visibility is governed by the Type filter alone."""
    # window=all so the past-but-filed AR_SUBMITTED row isn't bounded out by the default
    # d60 window — this test is about the Status filter, not the date window.
    resp = client.get("/dashboard/?type=CIPC_AR&status=PENDING&window=all")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "2026-05-08" in body  # generated_overdue still visible
    assert "2026-05-11" in body  # ar_submitted_past still visible


def test_window_overdue_includes_only_overdue_cipc(client, cipc_world):
    """window=overdue keeps the pre-filing past-due row; the past-but-filed AR_SUBMITTED
    row and the future INVOICED row are excluded."""
    resp = client.get("/dashboard/?window=overdue")
    body = resp.data.decode()
    assert "2026-05-08" in body  # generated_overdue, due TODAY-5
    assert "2026-05-11" not in body  # ar_submitted_past (filed → not overdue)
    assert "2026-05-23" not in body  # invoiced_future


def test_assignee_filter_applies_to_cipc(client, cipc_world):
    resp = client.get("/dashboard/?assignee=TSEGO")
    body = resp.data.decode()
    assert "2026-05-08" in body  # generated_overdue (Tsego)
    assert "2026-06-02" not in body  # closed_unassigned (no assignee) excluded


# --- Type filter spanning obligations + CIPC (chunk 6a) ---


@pytest.fixture
def mixed_world(app):
    """One client with a VAT201 obligation, an EMP201 obligation, and a CIPC AR — each on
    a distinct due date so a row can be identified by its date string regardless of the
    type-dropdown option labels (which always contain VAT201/EMP201/CIPC AR)."""
    c = Client(legal_name="Acme Pty Ltd", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    niel = Staff(code="NIEL", full_name="Niel Meyer", role=StaffRole.TAX)
    db.session.add(niel)
    db.session.commit()

    vat = ObligationInstance(
        client_id=c.id,
        obligation_type=ObligationType.VAT201,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        submission_due_date=date(2026, 1, 31),
        payment_due_date=date(2026, 1, 31),
        status=ObligationStatus.PENDING,
        assignee_id=niel.id,
    )
    emp = ObligationInstance(
        client_id=c.id,
        obligation_type=ObligationType.EMP201,
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
        submission_due_date=date(2026, 2, 28),
        payment_due_date=date(2026, 2, 28),
        status=ObligationStatus.PENDING,
        assignee_id=niel.id,
    )
    cipc = CIPCAnnualInstance(
        client_id=c.id,
        anniversary_date=date(2025, 3, 15),
        due_date=date(2026, 3, 15),
        status=CIPCAnnualStatus.GENERATED,
        assignee_id=niel.id,
    )
    db.session.add_all([vat, emp, cipc])
    db.session.commit()
    # Distinct date markers: VAT 2026-01-31, EMP 2026-02-28, CIPC 2026-03-15.
    return {"vat_due": "2026-01-31", "emp_due": "2026-02-28", "cipc_due": "2026-03-15"}


def test_type_filter_unset_shows_all_kinds(client, mixed_world):
    body = client.get("/dashboard/").data.decode()
    assert mixed_world["vat_due"] in body
    assert mixed_world["emp_due"] in body
    assert mixed_world["cipc_due"] in body


def test_type_filter_vat201_shows_only_vat(client, mixed_world):
    body = client.get("/dashboard/?type=VAT201").data.decode()
    assert mixed_world["vat_due"] in body
    assert mixed_world["emp_due"] not in body
    assert mixed_world["cipc_due"] not in body


def test_type_filter_emp201_shows_only_emp(client, mixed_world):
    body = client.get("/dashboard/?type=EMP201").data.decode()
    assert mixed_world["emp_due"] in body
    assert mixed_world["vat_due"] not in body
    assert mixed_world["cipc_due"] not in body


def test_type_filter_cipc_ar_shows_only_cipc_and_excludes_obligations(client, mixed_world):
    body = client.get("/dashboard/?type=CIPC_AR").data.decode()
    assert mixed_world["cipc_due"] in body
    assert mixed_world["vat_due"] not in body
    assert mixed_world["emp_due"] not in body


def test_type_filter_repaints_selection(client, mixed_world):
    body = client.get("/dashboard/?type=CIPC_AR").data.decode()
    assert '<option value="CIPC_AR" selected>CIPC AR</option>' in body


def test_type_filter_preserved_across_action_redirect(client, world):
    oi_id = world["pending_overdue_id"]
    resp = client.post(f"/dashboard/obligations/{oi_id}/mark-submitted?type=VAT201")
    assert resp.status_code == 302
    assert "type=VAT201" in resp.headers["Location"]


# --- Client filter spanning obligations + CIPC (chunk 6b) ---


@pytest.fixture
def two_client_world(app):
    """Two clients: A with a VAT201 obligation, B with a VAT201 obligation AND a CIPC AR.
    Rows are identified by distinct due-date strings (client legal names always appear in
    the Client dropdown, so they aren't usable as row markers)."""
    a = Client(legal_name="Acme Pty Ltd", entity_type=EntityType.PTY_LTD)
    b = Client(legal_name="Beta Holdings Pty Ltd", entity_type=EntityType.PTY_LTD)
    db.session.add_all([a, b])
    niel = Staff(code="NIEL", full_name="Niel Meyer", role=StaffRole.TAX)
    db.session.add(niel)
    db.session.commit()

    def _vat(client_id, period_end):
        return ObligationInstance(
            client_id=client_id,
            obligation_type=ObligationType.VAT201,
            period_start=date(period_end.year, period_end.month, 1),
            period_end=period_end,
            submission_due_date=period_end,
            payment_due_date=period_end,
            status=ObligationStatus.PENDING,
            assignee_id=niel.id,
        )

    db.session.add_all(
        [
            _vat(a.id, date(2026, 1, 31)),  # A marker
            _vat(b.id, date(2026, 2, 28)),  # B marker
            CIPCAnnualInstance(  # B's CIPC marker
                client_id=b.id,
                anniversary_date=date(2025, 3, 15),
                due_date=date(2026, 3, 15),
                status=CIPCAnnualStatus.GENERATED,
                assignee_id=niel.id,
            ),
        ]
    )
    db.session.commit()
    return {
        "a_id": a.id,
        "b_id": b.id,
        "a_due": "2026-01-31",
        "b_due": "2026-02-28",
        "b_cipc_due": "2026-03-15",
    }


def test_client_filter_shows_only_that_client(client, two_client_world):
    body = client.get(f"/dashboard/?client={two_client_world['a_id']}").data.decode()
    assert two_client_world["a_due"] in body
    assert two_client_world["b_due"] not in body
    assert two_client_world["b_cipc_due"] not in body


def test_client_filter_applies_to_cipc(client, two_client_world):
    body = client.get(f"/dashboard/?client={two_client_world['b_id']}").data.decode()
    assert two_client_world["b_due"] in body
    assert two_client_world["b_cipc_due"] in body  # B's CIPC row included
    assert two_client_world["a_due"] not in body


def test_client_filter_repaints_selection(client, two_client_world):
    a_id = two_client_world["a_id"]
    body = client.get(f"/dashboard/?client={a_id}").data.decode()
    assert f'<option value="{a_id}" selected>Acme Pty Ltd</option>' in body


def test_invalid_client_filter_is_ignored(client, two_client_world):
    """An unknown or non-numeric client id falls through to no filter (all rows shown)."""
    for bad in ("99999", "not-a-number"):
        body = client.get(f"/dashboard/?client={bad}").data.decode()
        assert two_client_world["a_due"] in body
        assert two_client_world["b_due"] in body
        assert two_client_world["b_cipc_due"] in body


def test_client_filter_preserved_across_action_redirect(client, world):
    oi_id = world["pending_overdue_id"]
    client_id = world["client_id"]
    resp = client.post(f"/dashboard/obligations/{oi_id}/mark-submitted?client={client_id}")
    assert resp.status_code == 302
    assert f"client={client_id}" in resp.headers["Location"]


# --- ITR14 (file-only) surfaces on the dashboard (Ticket 4a chunk 4) ---


@pytest.fixture
def itr14_world(app):
    """One client with a single PENDING ITR14 obligation, plus a CIPC AR so the
    type=ITR14 filter's CIPC-exclusion can be asserted. Distinct due-date markers."""
    c = Client(legal_name="Gamma Pty Ltd", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    niel = Staff(code="NIEL", full_name="Niel Meyer", role=StaffRole.TAX)
    db.session.add(niel)
    db.session.commit()

    itr14 = ObligationInstance(
        client_id=c.id,
        obligation_type=ObligationType.ITR14,
        period_start=date(2025, 3, 1),
        period_end=date(2026, 2, 28),
        submission_due_date=date(2027, 3, 1),
        payment_due_date=date(2027, 3, 1),
        status=ObligationStatus.PENDING,
        assignee_id=niel.id,
    )
    cipc = CIPCAnnualInstance(
        client_id=c.id,
        anniversary_date=date(2025, 3, 15),
        due_date=date(2026, 3, 15),
        status=CIPCAnnualStatus.GENERATED,
        assignee_id=niel.id,
    )
    db.session.add_all([itr14, cipc])
    db.session.commit()
    return {"itr14_id": itr14.id, "itr14_due": "2027-03-01", "cipc_due": "2026-03-15"}


def test_itr14_renders_in_list(client, itr14_world):
    # window=all: the ITR14 is due ~10 months out, beyond the default d60 working view.
    body = client.get("/dashboard/?window=all").data.decode()
    assert "Gamma Pty Ltd" in body
    assert itr14_world["itr14_due"] in body  # the ITR14 row's due date


def test_type_filter_itr14_shows_only_itr14_and_excludes_cipc(client, itr14_world):
    """type=ITR14 narrows to the ITR14 obligation and, per the existing logic (a named
    ObligationType drops CIPC), excludes the CIPC AR row."""
    body = client.get("/dashboard/?type=ITR14&window=all").data.decode()
    assert itr14_world["itr14_due"] in body
    assert itr14_world["cipc_due"] not in body


def test_type_filter_includes_itr14_option_and_repaints(client, itr14_world):
    """The Type dropdown gained ITR14 automatically (enum-driven) and repaints the
    selection."""
    body = client.get("/dashboard/?type=ITR14").data.decode()
    assert '<option value="ITR14" selected>ITR14</option>' in body


def test_itr14_pending_row_actions(client, itr14_world):
    """PENDING ITR14 offers Start / Mark submitted / Mark exempt — and never Mark paid."""
    oid = itr14_world["itr14_id"]
    body = client.get("/dashboard/?window=all").data.decode()
    assert f"/dashboard/obligations/{oid}/mark-in-progress" in body
    assert f"/dashboard/obligations/{oid}/mark-submitted" in body
    assert f"/dashboard/obligations/{oid}/mark-exempt" in body
    assert f"/dashboard/obligations/{oid}/mark-paid" not in body


def test_itr14_in_progress_row_actions(client, itr14_world):
    """IN_PROGRESS ITR14 offers Mark submitted / Revert to pending / Mark exempt — no
    Mark paid."""
    oid = itr14_world["itr14_id"]
    client.post(f"/dashboard/obligations/{oid}/mark-in-progress")
    body = client.get("/dashboard/?window=all").data.decode()
    assert f"/dashboard/obligations/{oid}/mark-submitted" in body
    assert f"/dashboard/obligations/{oid}/revert-to-pending" in body
    assert f"/dashboard/obligations/{oid}/mark-exempt" in body
    assert f"/dashboard/obligations/{oid}/mark-paid" not in body


def test_itr14_submitted_row_is_terminal(client, itr14_world):
    """Once SUBMITTED, a file-only ITR14 is done → terminal: no action buttons at all."""
    oid = itr14_world["itr14_id"]
    client.post(f"/dashboard/obligations/{oid}/mark-submitted")
    assert db.session.get(ObligationInstance, oid).status is ObligationStatus.SUBMITTED
    body = client.get("/dashboard/?window=all").data.decode()
    for action in ("mark-paid", "mark-submitted", "mark-exempt", "mark-in-progress"):
        assert f"/dashboard/obligations/{oid}/{action}" not in body


def test_itr14_detail_submitted_is_terminal_no_mark_paid(client, itr14_world):
    """The DETAIL page renders actions through the adapter too: a SUBMITTED file-only
    ITR14 offers no Mark paid (the detail-page bug) and is fully terminal — no action
    or reassign forms."""
    oid = itr14_world["itr14_id"]
    client.post(f"/dashboard/obligations/{oid}/mark-submitted")
    resp = client.get(f"/dashboard/obligations/{oid}")
    assert resp.status_code == 200
    body = resp.data.decode()
    # Still renders the read-only detail (status badge), but no action forms.
    assert "SUBMITTED" in body
    for action in ("mark-paid", "mark-submitted", "mark-exempt", "mark-in-progress"):
        assert f"/dashboard/obligations/{oid}/{action}" not in body
    assert f"/dashboard/obligations/{oid}/reassign" not in body


def test_itr14_detail_pending_offers_no_mark_paid(client, itr14_world):
    """A PENDING file-only ITR14 detail page offers Start / Mark submitted / Mark exempt
    (with next=detail) but never Mark paid."""
    oid = itr14_world["itr14_id"]
    body = client.get(f"/dashboard/obligations/{oid}").data.decode()
    assert f"/dashboard/obligations/{oid}/mark-in-progress" in body
    assert f"/dashboard/obligations/{oid}/mark-submitted" in body
    assert f"/dashboard/obligations/{oid}/mark-exempt" in body
    assert f"/dashboard/obligations/{oid}/mark-paid" not in body


# --- ITR12 confirmation: enum-driven Type filter + adapter detail (Ticket 4b) ---


@pytest.fixture
def itr12_world(app):
    """An individual with one PENDING ITR12, plus a company CIPC AR so the type=ITR12
    filter's CIPC exclusion can be asserted. Distinct due-date markers."""
    person = Client(legal_name="Smit, J", entity_type=EntityType.INDIVIDUAL)
    company = Client(legal_name="Beta Holdings Pty Ltd", entity_type=EntityType.PTY_LTD)
    db.session.add_all([person, company])
    niel = Staff(code="NIEL", full_name="Niel Meyer", role=StaffRole.TAX)
    db.session.add(niel)
    db.session.commit()

    it12 = ObligationInstance(
        client_id=person.id,
        obligation_type=ObligationType.ITR12,
        period_start=date(2025, 3, 1),
        period_end=date(2026, 2, 28),
        submission_due_date=date(2026, 10, 23),
        payment_due_date=date(2026, 10, 23),
        status=ObligationStatus.PENDING,
        assignee_id=niel.id,
    )
    cipc = CIPCAnnualInstance(
        client_id=company.id,
        anniversary_date=date(2025, 3, 15),
        due_date=date(2026, 3, 15),
        status=CIPCAnnualStatus.GENERATED,
        assignee_id=niel.id,
    )
    db.session.add_all([it12, cipc])
    db.session.commit()
    return {"it12_id": it12.id, "it12_due": "2026-10-23", "cipc_due": "2026-03-15"}


def test_itr12_renders_in_list(client, itr12_world):
    body = client.get("/dashboard/?window=all").data.decode()
    assert "Smit, J" in body
    assert itr12_world["it12_due"] in body


def test_type_filter_itr12_shows_only_itr12_and_excludes_cipc(client, itr12_world):
    """ITR12 appears in the Type filter (enum-driven) and narrows to ITR12, dropping CIPC."""
    body = client.get("/dashboard/?type=ITR12&window=all").data.decode()
    assert itr12_world["it12_due"] in body
    assert itr12_world["cipc_due"] not in body


def test_type_filter_includes_itr12_option(client, itr12_world):
    body = client.get("/dashboard/?type=ITR12").data.decode()
    assert '<option value="ITR12" selected>ITR12</option>' in body


def test_itr12_detail_renders_via_adapter_pending(client, itr12_world):
    """The detail page renders ITR12 through the adapter: Start / Mark submitted / Mark
    exempt, and never Mark paid (file-only)."""
    oid = itr12_world["it12_id"]
    body = client.get(f"/dashboard/obligations/{oid}").data.decode()
    assert "ITR12" in body
    assert f"/dashboard/obligations/{oid}/mark-submitted" in body
    assert f"/dashboard/obligations/{oid}/mark-paid" not in body


def test_itr12_detail_submitted_is_terminal(client, itr12_world):
    """A SUBMITTED ITR12 detail page is terminal — no action forms at all."""
    oid = itr12_world["it12_id"]
    client.post(f"/dashboard/obligations/{oid}/mark-submitted")
    assert db.session.get(ObligationInstance, oid).status is ObligationStatus.SUBMITTED
    body = client.get(f"/dashboard/obligations/{oid}").data.decode()
    for action in ("mark-paid", "mark-submitted", "mark-exempt", "mark-in-progress"):
        assert f"/dashboard/obligations/{oid}/{action}" not in body


# --- Archived clients are inert on the dashboard (H1 chunk 2) ---


def test_archived_client_rows_and_dropdown_absent_from_dashboard(client, app):
    """An archived client's obligation and CIPC rows never appear in the list, and the
    client never appears in the filter dropdown; an active client's row still renders."""
    with app.app_context():
        archived = Client(legal_name="Ghost Pty Ltd", entity_type=EntityType.PTY_LTD, active=False)
        active = Client(legal_name="Live Pty Ltd", entity_type=EntityType.PTY_LTD)
        db.session.add_all([archived, active])
        db.session.commit()

        db.session.add_all(
            [
                ObligationInstance(
                    client_id=archived.id,
                    obligation_type=ObligationType.VAT201,
                    period_start=date(2026, 1, 1),
                    period_end=date(2026, 1, 31),
                    submission_due_date=date(2026, 1, 31),
                    payment_due_date=date(2026, 1, 31),
                    status=ObligationStatus.PENDING,
                ),
                CIPCAnnualInstance(
                    client_id=archived.id,
                    anniversary_date=date(2025, 3, 15),
                    due_date=date(2026, 3, 15),
                    status=CIPCAnnualStatus.GENERATED,
                ),
                ObligationInstance(
                    client_id=active.id,
                    obligation_type=ObligationType.VAT201,
                    period_start=date(2026, 2, 1),
                    period_end=date(2026, 2, 28),
                    submission_due_date=date(2026, 2, 28),
                    payment_due_date=date(2026, 2, 28),
                    status=ObligationStatus.PENDING,
                ),
            ]
        )
        db.session.commit()

    body = client.get("/dashboard/").data.decode()
    # Active client's row renders; archived obligation + CIPC rows do not.
    assert "2026-02-28" in body
    assert "2026-01-31" not in body
    assert "2026-03-15" not in body
    # Dropdown lists the active client only.
    assert "Live Pty Ltd" in body
    assert "Ghost Pty Ltd" not in body
