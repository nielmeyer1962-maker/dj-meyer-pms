"""Hardening sweep H1 — regression tests.

Covers the four H1 behaviours:
  1. every generator defaults `today` to today_sast() (Africa/Johannesburg), not the
     container-local date.today();
  2. archived (active=False) clients generate nothing and are hidden from the dashboard,
     while regenerate still preserves their already-due (overdue) PENDING work;
  3. the ITR12 deadline read falls back to the statutory defaults when the settings table
     has not been seeded;
  4. create_app refuses to boot with an empty or placeholder SECRET_KEY.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.app_setting import DEFAULT_ITR12_NONPROVISIONAL, DEFAULT_ITR12_PROVISIONAL
from app.models.client import Client, EntityType, VatCategory, VatSubmissionMethod
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.services.cipc.generate import generate_cipc_annual
from app.services.obligations.emp201 import generate_emp201
from app.services.obligations.it12 import generate_it12
from app.services.obligations.itr14 import generate_itr14
from app.services.obligations.regenerate import regenerate
from app.services.obligations.vat201 import generate_vat201
from app.services.settings import get_itr12_deadline


def _vat_client(legal_name: str = "VAT Co", *, active: bool = True) -> Client:
    """A Cat C / eFiling VAT-registered Pty Ltd, committed."""
    c = Client(
        legal_name=legal_name,
        entity_type=EntityType.PTY_LTD,
        active=active,
        has_vat=True,
        vat_category=VatCategory.C,
        vat_submission_method=VatSubmissionMethod.EFILING,
    )
    db.session.add(c)
    db.session.commit()
    return c


def _rows(client_id: int) -> list[ObligationInstance]:
    return list(
        db.session.scalars(
            db.select(ObligationInstance).where(ObligationInstance.client_id == client_id)
        )
    )


# --- 1) Generators default `today` to today_sast() -----------------------------------


def test_vat201_defaults_today_to_sast(app, monkeypatch):
    """generate_vat201(today=None) resolves the default via today_sast(), not date.today()."""
    fake = date(2026, 1, 1)
    monkeypatch.setattr("app.services.obligations.vat201.today_sast", lambda: fake)
    with app.app_context():
        c = _vat_client()
        got = [i.period_end for i in generate_vat201(c)]
        assert got == [i.period_end for i in generate_vat201(c, today=fake)]
        assert got[0] == date(2026, 1, 31)


def test_emp201_defaults_today_to_sast(app, monkeypatch):
    fake = date(2026, 1, 1)
    monkeypatch.setattr("app.services.obligations.emp201.today_sast", lambda: fake)
    with app.app_context():
        c = Client(legal_name="PAYE Co", entity_type=EntityType.PTY_LTD, has_paye=True)
        db.session.add(c)
        db.session.commit()
        got = [i.period_end for i in generate_emp201(c)]
        assert got == [i.period_end for i in generate_emp201(c, today=fake)]
        assert got[0] == date(2026, 1, 31)


def test_itr14_defaults_today_to_sast(app, monkeypatch):
    fake = date(2026, 6, 10)
    monkeypatch.setattr("app.services.obligations.itr14.today_sast", lambda: fake)
    with app.app_context():
        c = Client(legal_name="ITR14 Co", entity_type=EntityType.PTY_LTD, has_income_tax=True)
        c.year_end_month = 2
        c.year_end_day = 28
        db.session.add(c)
        db.session.commit()
        got = generate_itr14(c)
        assert len(got) == 1
        assert got[0].period_end == date(2026, 2, 28)


def test_it12_defaults_today_to_sast(app, monkeypatch):
    fake = date(2026, 6, 10)
    monkeypatch.setattr("app.services.obligations.it12.today_sast", lambda: fake)
    with app.app_context():
        c = Client(legal_name="Individual", entity_type=EntityType.INDIVIDUAL, has_income_tax=True)
        db.session.add(c)
        db.session.commit()
        got = generate_it12(c)
        assert len(got) == 1
        assert got[0].period_end == date(2026, 2, 28)


def test_cipc_annual_defaults_today_to_sast(app, monkeypatch):
    fake = date(2026, 6, 10)
    monkeypatch.setattr("app.services.cipc.generate.today_sast", lambda: fake)
    with app.app_context():
        c = Client(legal_name="CIPC Co", entity_type=EntityType.PTY_LTD)
        c.cipc_anniversary_month = 6
        c.cipc_anniversary_day = 1
        db.session.add(c)
        db.session.commit()
        got = generate_cipc_annual(c)
        assert len(got) == 1
        assert got[0].anniversary_date == date(2026, 6, 1)


def test_regenerate_defaults_today_to_sast(app, monkeypatch):
    """regenerate(today=None) resolves once via today_sast() and feeds it to the generators."""
    fake = date(2026, 1, 1)
    monkeypatch.setattr("app.services.obligations.regenerate.today_sast", lambda: fake)
    with app.app_context():
        c = _vat_client()
        result = regenerate(c)
        db.session.commit()
        rows = _rows(c.id)
        assert result.added == 12
        assert min(r.period_end for r in rows) == date(2026, 1, 31)


# --- 2) Archived clients are inert -----------------------------------------------------


def test_archived_client_generators_return_empty(app):
    """An active=False client accrues no new work from any generator."""
    with app.app_context():
        today = date(2026, 6, 12)
        c = Client(
            legal_name="Archived Co",
            entity_type=EntityType.PTY_LTD,
            active=False,
            has_vat=True,
            vat_category=VatCategory.C,
            vat_submission_method=VatSubmissionMethod.EFILING,
            has_paye=True,
            has_income_tax=True,
        )
        c.year_end_month = 2
        c.year_end_day = 28
        c.cipc_anniversary_month = 6
        c.cipc_anniversary_day = 1
        db.session.add(c)
        db.session.commit()

        ind = Client(
            legal_name="Archived Person",
            entity_type=EntityType.INDIVIDUAL,
            active=False,
            has_income_tax=True,
        )
        db.session.add(ind)
        db.session.commit()

        assert generate_vat201(c, today=today) == []
        assert generate_emp201(c, today=today) == []
        assert generate_itr14(c, today=today) == []
        assert generate_cipc_annual(c, today=today) == []
        assert generate_it12(ind, today=today) == []


def test_regenerate_keeps_past_due_but_prunes_future_when_archived(app):
    """Archiving a client must not silently drop its overdue work. After archiving,
    regenerate prunes only the still-future PENDING rows; the past-due survivors — the
    seeded VAT201 and the generated ITR14, both period_end 2026-02-28 — remain."""
    with app.app_context():
        today = date(2026, 6, 12)
        c = Client(
            legal_name="Survivor Co",
            entity_type=EntityType.PTY_LTD,
            has_vat=True,
            vat_category=VatCategory.C,
            vat_submission_method=VatSubmissionMethod.EFILING,
            has_income_tax=True,
        )
        c.year_end_month = 2
        c.year_end_day = 28
        db.session.add(c)
        db.session.commit()

        # A past-due VAT201 that the forward window no longer generates (Feb 2026).
        db.session.add(
            ObligationInstance(
                client_id=c.id,
                obligation_type=ObligationType.VAT201,
                period_start=date(2026, 2, 1),
                period_end=date(2026, 2, 28),
                submission_due_date=date(2026, 3, 31),
                payment_due_date=date(2026, 3, 31),
                status=ObligationStatus.PENDING,
            )
        )
        db.session.commit()

        # While active: adds the forward VAT201 window plus the ITR14 for the closed FY.
        regenerate(c, today=today)
        db.session.commit()
        assert any(r.period_end > today for r in _rows(c.id))  # future rows exist to prune

        # Archive, then regenerate: every generator now returns [], so the only action is
        # the prune — which spares the two already-due PENDING rows.
        c.active = False
        db.session.commit()
        regenerate(c, today=today)
        db.session.commit()

        survivors = _rows(c.id)
        assert {(r.obligation_type, r.period_end) for r in survivors} == {
            (ObligationType.VAT201, date(2026, 2, 28)),
            (ObligationType.ITR14, date(2026, 2, 28)),
        }
        assert all(r.status is ObligationStatus.PENDING for r in survivors)


def test_dashboard_hides_archived_client_obligations(app, client):
    """An archived client's obligation rows never render on the work board."""
    with app.app_context():
        active = Client(legal_name="Active Visible Ltd", entity_type=EntityType.PTY_LTD)
        archived = Client(
            legal_name="Archived Hidden Ltd", entity_type=EntityType.PTY_LTD, active=False
        )
        db.session.add_all([active, archived])
        db.session.commit()
        for cl in (active, archived):
            db.session.add(
                ObligationInstance(
                    client_id=cl.id,
                    obligation_type=ObligationType.VAT201,
                    period_start=date(2026, 1, 1),
                    period_end=date(2026, 1, 31),
                    submission_due_date=date(2026, 3, 2),
                    payment_due_date=date(2026, 3, 2),
                    status=ObligationStatus.PENDING,
                )
            )
        db.session.commit()

    body = client.get("/dashboard/").get_data(as_text=True)
    assert "Active Visible Ltd" in body
    assert "Archived Hidden Ltd" not in body


def test_dashboard_dropdown_excludes_archived_client(app, client):
    """The client filter dropdown lists active clients only."""
    with app.app_context():
        active = Client(legal_name="Dropdown Active Ltd", entity_type=EntityType.PTY_LTD)
        archived = Client(
            legal_name="Dropdown Archived Ltd", entity_type=EntityType.PTY_LTD, active=False
        )
        db.session.add_all([active, archived])
        db.session.commit()

    body = client.get("/dashboard/").get_data(as_text=True)
    assert "Dropdown Active Ltd" in body
    assert "Dropdown Archived Ltd" not in body


# --- 3) ITR12 deadline falls back to defaults on an unseeded settings table -----------


def test_itr12_deadline_falls_back_to_default_provisional_when_unseeded(app):
    with app.app_context():
        assert get_itr12_deadline(provisional=True) == DEFAULT_ITR12_PROVISIONAL


def test_itr12_deadline_falls_back_to_default_nonprovisional_when_unseeded(app):
    with app.app_context():
        assert get_itr12_deadline(provisional=False) == DEFAULT_ITR12_NONPROVISIONAL


# --- 4) create_app refuses an empty / placeholder SECRET_KEY -------------------------


def test_create_app_rejects_placeholder_secret_key():
    class BadConfig(Config):
        SECRET_KEY = "change-me-in-production"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(BadConfig)


def test_create_app_rejects_empty_secret_key():
    class BadConfig(Config):
        SECRET_KEY = ""
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(BadConfig)
