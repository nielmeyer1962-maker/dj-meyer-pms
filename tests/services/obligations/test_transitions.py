from __future__ import annotations

from datetime import date

import pytest

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.services.obligations.transitions import (
    mark_exempt,
    mark_in_progress,
    mark_paid,
    mark_submitted,
    revert_to_pending,
)


def _make_client() -> Client:
    c = Client(legal_name="Transitions Test Corp", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    return c


def _make_instance(
    client_id: int,
    status: ObligationStatus,
    period_end: date = date(2026, 4, 30),
) -> ObligationInstance:
    oi = ObligationInstance(
        client_id=client_id,
        obligation_type=ObligationType.VAT201,
        period_start=date(period_end.year, period_end.month, 1),
        period_end=period_end,
        submission_due_date=period_end,
        payment_due_date=period_end,
        status=status,
    )
    db.session.add(oi)
    db.session.commit()
    return oi


# --- Legal advances ---


def test_mark_in_progress_advances_pending_to_in_progress(app):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, ObligationStatus.PENDING)
        mark_in_progress(oi)
        assert oi.status is ObligationStatus.IN_PROGRESS


def test_revert_to_pending_walks_in_progress_back_to_pending(app):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, ObligationStatus.IN_PROGRESS)
        revert_to_pending(oi)
        assert oi.status is ObligationStatus.PENDING


def test_mark_submitted_advances_pending_to_submitted(app):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, ObligationStatus.PENDING)
        mark_submitted(oi)
        assert oi.status is ObligationStatus.SUBMITTED


def test_mark_submitted_advances_in_progress_to_submitted(app):
    """IN_PROGRESS is an accepted prior state — started work submits without a detour."""
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, ObligationStatus.IN_PROGRESS)
        mark_submitted(oi)
        assert oi.status is ObligationStatus.SUBMITTED


def test_mark_exempt_from_in_progress(app):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, ObligationStatus.IN_PROGRESS)
        mark_exempt(oi)
        assert oi.status is ObligationStatus.EXEMPT


def test_mark_paid_advances_submitted_to_paid(app):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, ObligationStatus.SUBMITTED)
        mark_paid(oi)
        assert oi.status is ObligationStatus.PAID


def test_mark_exempt_from_pending(app):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, ObligationStatus.PENDING)
        mark_exempt(oi)
        assert oi.status is ObligationStatus.EXEMPT


def test_mark_exempt_from_submitted(app):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, ObligationStatus.SUBMITTED)
        mark_exempt(oi)
        assert oi.status is ObligationStatus.EXEMPT


# --- Illegal transitions: each must raise ValueError and not mutate the row ---


@pytest.mark.parametrize(
    "from_status",
    [ObligationStatus.SUBMITTED, ObligationStatus.PAID, ObligationStatus.EXEMPT],
)
def test_mark_submitted_illegal(app, from_status):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, from_status)
        with pytest.raises(ValueError, match=from_status.name):
            mark_submitted(oi)
        assert oi.status is from_status  # unchanged


@pytest.mark.parametrize(
    "from_status",
    [
        ObligationStatus.PENDING,
        ObligationStatus.IN_PROGRESS,
        ObligationStatus.PAID,
        ObligationStatus.EXEMPT,
    ],
)
def test_mark_paid_illegal(app, from_status):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, from_status)
        with pytest.raises(ValueError, match=from_status.name):
            mark_paid(oi)
        assert oi.status is from_status


@pytest.mark.parametrize(
    "from_status",
    [
        ObligationStatus.IN_PROGRESS,
        ObligationStatus.SUBMITTED,
        ObligationStatus.PAID,
        ObligationStatus.EXEMPT,
    ],
)
def test_mark_in_progress_illegal(app, from_status):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, from_status)
        with pytest.raises(ValueError, match=from_status.name):
            mark_in_progress(oi)
        assert oi.status is from_status


@pytest.mark.parametrize(
    "from_status",
    [
        ObligationStatus.PENDING,
        ObligationStatus.SUBMITTED,
        ObligationStatus.PAID,
        ObligationStatus.EXEMPT,
    ],
)
def test_revert_to_pending_illegal(app, from_status):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, from_status)
        with pytest.raises(ValueError, match=from_status.name):
            revert_to_pending(oi)
        assert oi.status is from_status


@pytest.mark.parametrize(
    "from_status",
    [ObligationStatus.PAID, ObligationStatus.EXEMPT],
)
def test_mark_exempt_illegal(app, from_status):
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, from_status)
        with pytest.raises(ValueError, match=from_status.name):
            mark_exempt(oi)
        assert oi.status is from_status


# --- Error message format ---


def test_error_message_includes_id_status_and_legal_prior_state(app):
    """The dashboard's danger flash echoes this message; it must be self-contained."""
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, ObligationStatus.SUBMITTED)
        with pytest.raises(ValueError) as exc:
            mark_submitted(oi)
        msg = str(exc.value)
        assert f"id={oi.id}" in msg
        assert "status=SUBMITTED" in msg
        assert "PENDING" in msg  # legal prior state


# --- Timestamp sanity: updated_at advances on flush after a transition ---


def test_updated_at_advances_after_transition_and_flush(app):
    """Guards against an accidental refactor that breaks the model's onupdate=func.now()."""
    with app.app_context():
        c = _make_client()
        oi = _make_instance(c.id, ObligationStatus.PENDING)
        generated_at = oi.generated_at

        mark_submitted(oi)
        db.session.commit()
        db.session.refresh(oi)

        assert oi.updated_at >= generated_at
        assert oi.status is ObligationStatus.SUBMITTED
