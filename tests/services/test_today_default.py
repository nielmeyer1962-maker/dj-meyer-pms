"""Chunk 1 (H1): every generator's default-today path resolves via today_sast(), not
date.today(). Each generator imports today_sast into its own module namespace, so we patch
it there and assert the today=None result matches an explicit today= call with the same
date."""

from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.app_setting import APP_SETTING_SEED, AppSetting
from app.models.client import Client, EntityType, VatCategory, VatSubmissionMethod
from app.models.obligation import ObligationInstance
from app.services.cipc.generate import generate_cipc_annual
from app.services.obligations.emp201 import generate_emp201
from app.services.obligations.it12 import generate_it12
from app.services.obligations.itr14 import generate_itr14
from app.services.obligations.regenerate import regenerate
from app.services.obligations.vat201 import generate_vat201

FIXED = date(2026, 6, 15)


def _seed_settings() -> None:
    for row in APP_SETTING_SEED:
        db.session.add(AppSetting(**row))
    db.session.commit()


def _persist(c: Client) -> Client:
    db.session.add(c)
    db.session.commit()
    return c


def test_vat201_default_today_uses_today_sast(app, monkeypatch):
    with app.app_context():
        c = _persist(
            Client(
                legal_name="VAT Co",
                entity_type=EntityType.PTY_LTD,
                has_vat=True,
                vat_category=VatCategory.C,
                vat_submission_method=VatSubmissionMethod.EFILING,
            )
        )
        monkeypatch.setattr("app.services.obligations.vat201.today_sast", lambda: FIXED)
        defaulted = generate_vat201(c)
        explicit = generate_vat201(c, today=FIXED)
        assert defaulted, "expected instances on the default-today path"
        assert [i.period_end for i in defaulted] == [i.period_end for i in explicit]


def test_emp201_default_today_uses_today_sast(app, monkeypatch):
    with app.app_context():
        c = _persist(Client(legal_name="PAYE Co", entity_type=EntityType.PTY_LTD, has_paye=True))
        monkeypatch.setattr("app.services.obligations.emp201.today_sast", lambda: FIXED)
        defaulted = generate_emp201(c)
        explicit = generate_emp201(c, today=FIXED)
        assert defaulted
        assert [i.period_end for i in defaulted] == [i.period_end for i in explicit]


def test_itr14_default_today_uses_today_sast(app, monkeypatch):
    with app.app_context():
        c = _persist(
            Client(
                legal_name="ITR14 Co",
                entity_type=EntityType.PTY_LTD,
                has_income_tax=True,
                year_end_month=2,
                year_end_day=28,
            )
        )
        monkeypatch.setattr("app.services.obligations.itr14.today_sast", lambda: FIXED)
        defaulted = generate_itr14(c)
        explicit = generate_itr14(c, today=FIXED)
        assert defaulted
        assert defaulted[0].period_end == explicit[0].period_end


def test_it12_default_today_uses_today_sast(app, monkeypatch):
    with app.app_context():
        _seed_settings()
        c = _persist(
            Client(legal_name="Smit, J", entity_type=EntityType.INDIVIDUAL, has_income_tax=True)
        )
        monkeypatch.setattr("app.services.obligations.it12.today_sast", lambda: FIXED)
        defaulted = generate_it12(c)
        explicit = generate_it12(c, today=FIXED)
        assert defaulted
        assert defaulted[0].submission_due_date == explicit[0].submission_due_date


def test_cipc_generate_default_today_uses_today_sast(app, monkeypatch):
    with app.app_context():
        c = _persist(
            Client(
                legal_name="CIPC Co",
                entity_type=EntityType.PTY_LTD,
                cipc_anniversary_month=3,
                cipc_anniversary_day=15,
            )
        )
        monkeypatch.setattr("app.services.cipc.generate.today_sast", lambda: FIXED)
        defaulted = generate_cipc_annual(c)
        explicit = generate_cipc_annual(c, today=FIXED)
        assert defaulted
        assert defaulted[0].anniversary_date == explicit[0].anniversary_date


def test_regenerate_default_today_uses_today_sast(app, monkeypatch):
    """regenerate resolves today once and threads it to the generators; the default path
    must produce the same rows as an explicit today=FIXED run."""
    with app.app_context():
        c = _persist(
            Client(
                legal_name="Regen Co",
                entity_type=EntityType.PTY_LTD,
                has_vat=True,
                vat_category=VatCategory.C,
                vat_submission_method=VatSubmissionMethod.EFILING,
            )
        )
        monkeypatch.setattr("app.services.obligations.regenerate.today_sast", lambda: FIXED)
        regenerate(c)  # today=None → today_sast()
        db.session.commit()

        produced = {
            r.period_end
            for r in db.session.scalars(
                db.select(ObligationInstance).where(ObligationInstance.client_id == c.id)
            )
        }
        expected = {i.period_end for i in generate_vat201(c, today=FIXED)}
        assert produced == expected
