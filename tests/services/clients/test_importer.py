"""Unit tests for the client bulk-import service (app/services/clients/importer.py).

Covers the CSV->model mapping (bool/enum/int), the has_vat=No VAT blanking rule,
allocated_staff resolution (code / prefix / unresolvable / ambiguous), per-row
error isolation (bad rows skipped and reported while good rows load), and
idempotency (a second identical run reports everything UNCHANGED).
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models.client import Client, EntityType, VatCategory, VatSubmissionMethod
from app.models.staff import Staff, StaffRole
from app.services.clients.importer import import_rows

# Roster used across the resolution tests. "Ca…" is deliberately ambiguous
# (Candice / Caroline) to exercise the ambiguity branch.
_ROSTER = [
    ("NIEL", "Niel Meyer", StaffRole.TAX),
    ("CANDI", "Candice van der Merwe", StaffRole.TAX),
    ("CAROLINE", "Caroline Lombard", StaffRole.TAX),
    ("TSEGO", "Tsego Mogale", StaffRole.SECRETARIAL),
]


@pytest.fixture
def staff(app):
    with app.app_context():
        for code, full_name, role in _ROSTER:
            db.session.add(Staff(code=code, full_name=full_name, role=role))
        db.session.commit()
        yield


def _row(**overrides):
    """A full, valid CSV row (all contract headers present). Override per test."""
    base = {
        "legal_name": "Acme (Pty) Ltd",
        "entity_type": "Pty Ltd",
        "registration_number": "2001/000001/07",
        "known_as": "Acme",
        "trading_name": "Acme Trading",
        "has_income_tax": "Yes",
        "has_provisional_tax": "No",
        "has_vat": "Yes",
        "vat_category": "A",
        "vat_submission_method": "EFILING",
        "has_paye": "No",
        "has_dividends_tax": "No",
        "year_end_month": "2",
        "year_end_day": "28",
        "cipc_anniversary_month": "3",
        "cipc_anniversary_day": "15",
        "allocated_staff": "Niel",
        "contact_person": "Jane Doe",
        "email": "jane@acme.co.za",
        "cc_email": "",
        "street1": "1 Main Rd",
        "postcode": "1500",
        "active": "Yes",
        "owner_id_number": "",
        "owner_id_type": "",
        "source_row": "2",
    }
    base.update(overrides)
    return base


def _get(reg):
    return db.session.scalar(db.select(Client).where(Client.registration_number == reg))


def test_bool_enum_int_and_known_as_mapping(app, staff):
    with app.app_context():
        niel = db.session.scalar(db.select(Staff).where(Staff.code == "NIEL"))
        report = import_rows([_row()])
        assert (report.added, report.updated, report.unchanged, report.errors) == (1, 0, 0, [])

        c = _get("2001/000001/07")
        assert c.entity_type is EntityType.PTY_LTD
        assert c.has_income_tax is True
        assert c.has_provisional_tax is False
        assert c.has_vat is True
        assert c.vat_category is VatCategory.A
        assert c.vat_submission_method is VatSubmissionMethod.EFILING
        assert c.year_end_month == 2 and c.year_end_day == 28
        assert c.cipc_anniversary_month == 3 and c.cipc_anniversary_day == 15
        assert c.known_as == "Acme"
        assert c.allocated_staff_id == niel.id
        assert c.active is True


def test_has_vat_no_blanks_vat_fields(app, staff):
    with app.app_context():
        # VAT cells are populated but has_vat=No must force both to None.
        report = import_rows(
            [_row(has_vat="No", vat_category="A", vat_submission_method="EFILING")]
        )
        assert report.added == 1 and report.errors == []
        c = _get("2001/000001/07")
        assert c.has_vat is False
        assert c.vat_category is None
        assert c.vat_submission_method is None


def test_blank_numeric_and_optional_text_become_none(app, staff):
    with app.app_context():
        report = import_rows(
            [
                _row(
                    year_end_month="",
                    year_end_day="",
                    cipc_anniversary_month="",
                    cipc_anniversary_day="",
                    known_as="",
                    cc_email="",
                )
            ]
        )
        assert report.added == 1 and report.errors == []
        c = _get("2001/000001/07")
        assert c.year_end_month is None and c.year_end_day is None
        assert c.cipc_anniversary_month is None and c.cipc_anniversary_day is None
        assert c.known_as is None and c.cc_email is None


def test_staff_resolution_by_code_prefix_blank(app, staff):
    with app.app_context():
        niel = db.session.scalar(db.select(Staff).where(Staff.code == "NIEL"))
        report = import_rows(
            [
                _row(
                    registration_number="R-CODE", allocated_staff="niel"
                ),  # code, case-insensitive
                _row(registration_number="R-PREFIX", allocated_staff="Niel M"),  # full-name prefix
                _row(registration_number="R-BLANK", allocated_staff=""),  # unallocated
            ]
        )
        assert report.added == 3 and report.errors == []
        assert _get("R-CODE").allocated_staff_id == niel.id
        assert _get("R-PREFIX").allocated_staff_id == niel.id
        assert _get("R-BLANK").allocated_staff_id is None


def test_unresolvable_staff_is_a_row_error(app, staff):
    with app.app_context():
        report = import_rows([_row(allocated_staff="Nobody", source_row="7")])
        assert report.added == 0
        assert len(report.errors) == 1
        assert report.errors[0].source_row == "7"
        assert "did not match" in report.errors[0].message
        assert _get("2001/000001/07") is None


def test_ambiguous_staff_is_a_row_error(app, staff):
    with app.app_context():
        # "Ca" prefixes both Candice and Caroline.
        report = import_rows([_row(allocated_staff="Ca", source_row="9")])
        assert report.added == 0
        assert len(report.errors) == 1
        assert "ambiguous" in report.errors[0].message


def test_bad_entity_type_skipped_good_row_loads(app, staff):
    with app.app_context():
        report = import_rows(
            [
                _row(registration_number="GOOD-1", source_row="2"),
                _row(registration_number="BAD-1", entity_type="Wizard", source_row="3"),
                _row(registration_number="GOOD-2", source_row="4"),
            ]
        )
        assert report.added == 2
        assert len(report.errors) == 1
        assert report.errors[0].source_row == "3"
        assert _get("GOOD-1") is not None and _get("GOOD-2") is not None
        assert _get("BAD-1") is None


def test_blank_entity_type_is_a_row_error(app, staff):
    with app.app_context():
        report = import_rows([_row(entity_type="", source_row="5")])
        assert report.added == 0
        assert len(report.errors) == 1
        assert "entity_type is required" in report.errors[0].message


def test_blank_registration_number_is_a_row_error(app, staff):
    with app.app_context():
        report = import_rows([_row(registration_number="", source_row="6")])
        assert report.added == 0
        assert len(report.errors) == 1
        assert "registration_number is required" in report.errors[0].message


def test_second_identical_run_is_all_unchanged(app, staff):
    with app.app_context():
        rows = [
            _row(registration_number="R-1"),
            _row(registration_number="R-2", legal_name="Beta CC", entity_type="CC"),
            _row(registration_number="R-3", legal_name="Gamma NPC", entity_type="NPC"),
        ]
        first = import_rows(rows)
        assert (first.added, first.updated, first.unchanged) == (3, 0, 0)
        db.session.commit()

        second = import_rows(rows)
        assert (second.added, second.updated, second.unchanged) == (0, 0, 3)
        assert second.errors == []


def test_changed_field_counts_as_updated(app, staff):
    with app.app_context():
        import_rows([_row(registration_number="R-1")])
        db.session.commit()

        report = import_rows([_row(registration_number="R-1", legal_name="Acme Renamed (Pty) Ltd")])
        assert (report.added, report.updated, report.unchanged) == (0, 1, 0)
        assert _get("R-1").legal_name == "Acme Renamed (Pty) Ltd"
