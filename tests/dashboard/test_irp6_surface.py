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
def irp6_row(app):
    c = Client(legal_name="Provisional Corp", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    oi = ObligationInstance(
        client_id=c.id,
        obligation_type=ObligationType.IRP6,
        period_start=date(2025, 3, 1),
        period_end=date(2026, 9, 30),
        submission_due_date=date(2026, 5, 13),  # in the default window
        payment_due_date=date(2026, 5, 13),
        status=ObligationStatus.PENDING,
        window_code="03",
    )
    db.session.add(oi)
    db.session.commit()
    return oi


def test_irp6_appears_in_enum_driven_type_filter(client):
    """The Type filter is built from ObligationType, so adding IRP6 to the enum surfaces it
    automatically — no template change needed."""
    body = client.get("/dashboard/").data.decode()
    assert 'value="IRP6"' in body


def test_irp6_type_filter_narrows_to_irp6(client, irp6_row):
    body = client.get("/dashboard/?type=IRP6").data.decode()
    assert "Provisional Corp" in body
    assert "2026-09-30" in body  # the IRP6 period_end


def test_irp6_row_shows_window_and_optional_badges(client, irp6_row):
    body = client.get("/dashboard/?type=IRP6").data.decode()
    # The 01/02/03 window badge…
    assert "Provisional period 03" in body
    # …and the voluntary-third "optional" label (window_code == "03").
    assert "optional" in body


def test_irp6_submitted_row_offers_pay_action(client, irp6_row):
    """A SUBMITTED IRP6 (payment leg) still offers Mark paid on the rendered dashboard."""
    irp6_row.status = ObligationStatus.SUBMITTED
    db.session.commit()
    body = client.get("/dashboard/?type=IRP6").data.decode()
    assert "Mark paid" in body
