"""Chunk 2 (H1): an archived client (active=False) is inert — every generator returns []
via an active gate that runs FIRST, before any settings/DB read."""

from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.client import Client, EntityType, VatCategory, VatSubmissionMethod
from app.services.cipc.generate import generate_cipc_annual
from app.services.obligations.emp201 import generate_emp201
from app.services.obligations.it12 import generate_it12
from app.services.obligations.itr14 import generate_itr14
from app.services.obligations.vat201 import generate_vat201

TODAY = date(2026, 6, 15)


def _persist(c: Client) -> Client:
    db.session.add(c)
    db.session.commit()
    return c


def test_vat201_archived_client_generates_nothing(app):
    with app.app_context():
        c = _persist(
            Client(
                legal_name="VAT Co",
                entity_type=EntityType.PTY_LTD,
                has_vat=True,
                vat_category=VatCategory.C,
                vat_submission_method=VatSubmissionMethod.EFILING,
                active=False,
            )
        )
        assert generate_vat201(c, today=TODAY) == []


def test_emp201_archived_client_generates_nothing(app):
    with app.app_context():
        c = _persist(
            Client(
                legal_name="PAYE Co",
                entity_type=EntityType.PTY_LTD,
                has_paye=True,
                active=False,
            )
        )
        assert generate_emp201(c, today=TODAY) == []


def test_itr14_archived_client_generates_nothing(app):
    with app.app_context():
        c = _persist(
            Client(
                legal_name="ITR14 Co",
                entity_type=EntityType.PTY_LTD,
                has_income_tax=True,
                year_end_month=2,
                year_end_day=28,
                active=False,
            )
        )
        assert generate_itr14(c, today=TODAY) == []


def test_it12_archived_client_generates_nothing_without_reading_settings(app):
    """No AppSetting rows are seeded here: the active gate must return [] before the
    settings read, so a missing-settings DB can't even be reached for an archived client."""
    with app.app_context():
        c = _persist(
            Client(
                legal_name="Smit, J",
                entity_type=EntityType.INDIVIDUAL,
                has_income_tax=True,
                active=False,
            )
        )
        assert generate_it12(c, today=TODAY) == []


def test_cipc_archived_client_generates_nothing(app):
    with app.app_context():
        c = _persist(
            Client(
                legal_name="CIPC Co",
                entity_type=EntityType.PTY_LTD,
                cipc_anniversary_month=3,
                cipc_anniversary_day=15,
                active=False,
            )
        )
        assert generate_cipc_annual(c, today=TODAY) == []
