from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType

TODAY = date(2026, 5, 13)


@pytest.fixture(autouse=True)
def _freeze_today():
    with patch("app.dashboard.routes.today_sast", return_value=TODAY):
        yield


@pytest.fixture
def emp501_row(app):
    c = Client(legal_name="Reconciliation Corp", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    oi = ObligationInstance(
        client_id=c.id,
        obligation_type=ObligationType.EMP501_ANNUAL,
        period_start=date(2025, 3, 1),
        period_end=date(2026, 2, 28),
        submission_due_date=date(2026, 5, 13),  # in the default window
        payment_due_date=date(2026, 5, 13),
        status=ObligationStatus.PENDING,
    )
    db.session.add(oi)
    db.session.commit()
    return oi


def test_both_emp501_values_in_enum_driven_type_filter(client):
    """Adding the two EMP501 members to ObligationType surfaces them in the Type filter
    automatically (it is built from the enum) — no template change."""
    body = client.get("/dashboard/").data.decode()
    assert 'value="EMP501_INTERIM"' in body
    assert 'value="EMP501_ANNUAL"' in body


def test_emp501_type_filter_narrows(client, emp501_row):
    body = client.get("/dashboard/?type=EMP501_ANNUAL").data.decode()
    assert "Reconciliation Corp" in body
    assert "2026-02-28" in body  # the annual reconciliation period_end


def test_emp501_pending_offers_submit_not_pay(client, emp501_row):
    """File-only on the rendered dashboard: Mark submitted, never Mark paid."""
    body = client.get("/dashboard/?type=EMP501_ANNUAL").data.decode()
    assert "Mark submitted" in body
    assert "Mark paid" not in body
