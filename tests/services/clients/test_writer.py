"""Chunk 2 — the natural-key upsert (`writer.apply_report`) against a real session.

Uses the `app` fixture (in-memory SQLite by default, Postgres under TEST_DATABASE_URL) so
the model's VAT / year-end / CIPC pairing invariants actually fire on flush.
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models.client import Client, EntityType, VatCategory, VatSubmissionMethod
from app.models.staff import Staff, StaffRole
from app.services.clients import importer as im
from app.services.clients import writer
from app.services.clients.readers import SourceRow

pytestmark = pytest.mark.usefixtures("app")


# --- helpers ---


def _seed_staff() -> list[Staff]:
    staff = [
        Staff(code="NIEL", full_name="Niel Meyer", role=StaffRole.TAX),
        Staff(code="TSEGO", full_name="Tsego Mogale", role=StaffRole.SECRETARIAL),
    ]
    db.session.add_all(staff)
    db.session.commit()
    return staff


_KEY_FIELD = {im.COMPANIES: "registration_number", im.INDIVIDUALS: "id_number"}


def _existing(kind: str) -> dict[str, Client]:
    column = _KEY_FIELD[kind]
    clients = db.session.scalars(db.select(Client)).all()
    return {getattr(c, column): c for c in clients if getattr(c, column)}


def _run(rows, kind, staff):
    """Parse + apply + commit, mirroring the CLI's --commit path."""
    existing_by_key = _existing(kind)
    report = im.parse_file(rows, kind, staff, existing_keys=frozenset(existing_by_key))
    result = writer.apply_report(report, existing_by_key, db.session)
    db.session.commit()
    return report, result


def _all_clients() -> list[Client]:
    return list(db.session.scalars(db.select(Client)).all())


def _company_row(number, name, reg, *, staff="Niel", vat=None, **extra):
    values = {im.CO_NAME: name, im.CO_REG: reg, im.CO_STAFF: staff}
    if vat is not None:
        values[im.CO_VAT] = vat
    values.update(extra)
    return SourceRow(number, values)


# --- insert ---


def test_insert_creates_client_with_mapped_fields():
    staff = _seed_staff()
    rows = [
        _company_row(
            2,
            "Acme (Pty) Ltd",
            "2015/123456/07",
            vat="B",
            **{
                im.CO_MONTH: "March",
                im.CO_DUE_DAY: "15",
                im.CO_EMAIL: "a@acme.co.za",
                im.CO_PAYE: "Yes",
                im.CO_YEAR_END: "February",
            },
        )
    ]
    _, result = _run(rows, im.COMPANIES, staff)

    assert result.inserted == 1
    assert result.updated == 0
    c = db.session.scalar(db.select(Client).where(Client.registration_number == "2015/123456/07"))
    assert c.entity_type is EntityType.PTY_LTD
    assert c.legal_name == "Acme (Pty) Ltd"
    assert c.email == "a@acme.co.za"
    assert (c.cipc_anniversary_month, c.cipc_anniversary_day) == (3, 15)
    assert (c.year_end_month, c.year_end_day) == (2, 28)
    assert c.has_vat is True
    assert c.vat_category is VatCategory.B
    assert c.vat_submission_method is VatSubmissionMethod.EFILING
    assert c.has_paye is True
    assert c.has_income_tax is True
    assert c.allocated_staff_id == staff[0].id


def test_individual_insert_keys_on_id_number():
    staff = _seed_staff()
    rows = [
        SourceRow(
            3,
            {
                im.IN_NAME: "Smit, J",
                im.IN_ID: "8001015009087",
                im.IN_TAXREF: "0001234567",
                im.IN_STAFF: "Niel",
            },
        )
    ]
    _, result = _run(rows, im.INDIVIDUALS, staff)

    assert result.inserted == 1
    c = db.session.scalar(db.select(Client).where(Client.id_number == "8001015009087"))
    assert c.entity_type is EntityType.INDIVIDUAL
    assert c.tax_ref == "0001234567"
    assert c.has_income_tax is True
    assert c.has_vat is False  # individuals carry no VAT info


# --- idempotency / never-delete ---


def test_rerun_is_idempotent_zero_new_inserts():
    staff = _seed_staff()
    rows = [_company_row(2, "Acme (Pty) Ltd", "2015/123456/07")]
    _run(rows, im.COMPANIES, staff)
    count_after_first = len(_all_clients())

    report2, result2 = _run(rows, im.COMPANIES, staff)

    assert result2.inserted == 0
    assert result2.updated == 1
    assert report2.to_insert == []  # the row now classifies as an update
    assert len(_all_clients()) == count_after_first  # no duplicate row


def test_missing_row_on_rerun_is_not_deleted():
    staff = _seed_staff()
    both = [
        _company_row(2, "Acme (Pty) Ltd", "2015/123456/07"),
        _company_row(3, "Beta CC", "1994/000403/23"),
    ]
    _run(both, im.COMPANIES, staff)
    assert len(_all_clients()) == 2

    # Re-import a list that no longer contains Beta CC.
    _run([_company_row(2, "Acme (Pty) Ltd", "2015/123456/07")], im.COMPANIES, staff)

    assert len(_all_clients()) == 2  # Beta CC survives — import never deletes
    assert db.session.scalar(
        db.select(Client).where(Client.registration_number == "1994/000403/23")
    )


def test_update_overwrites_mapped_fields_but_preserves_unmapped():
    staff = _seed_staff()
    _run(
        [_company_row(2, "Acme (Pty) Ltd", "2015/123456/07", **{im.CO_EMAIL: "old@acme.co.za"})],
        im.COMPANIES,
        staff,
    )
    c = db.session.scalar(db.select(Client).where(Client.registration_number == "2015/123456/07"))
    c.phone = "011 555 0000"  # unmapped column — a manual edit
    db.session.commit()

    _run(
        [_company_row(2, "Acme (Pty) Ltd", "2015/123456/07", **{im.CO_EMAIL: "new@acme.co.za"})],
        im.COMPANIES,
        staff,
    )

    db.session.refresh(c)
    assert c.email == "new@acme.co.za"  # mapped: overwritten
    assert c.phone == "011 555 0000"  # unmapped: survives the re-import


# --- flags / unwritable rows ---


def test_data_quality_note_persisted_on_flagged_row():
    staff = _seed_staff()
    rows = [_company_row(2, "Ghost (Pty) Ltd", "2015/123456/07", staff="Nobody")]
    _run(rows, im.COMPANIES, staff)

    c = db.session.scalar(db.select(Client).where(Client.registration_number == "2015/123456/07"))
    assert c.allocated_staff_id is None
    assert "unknown staff member" in c.data_quality_note


def test_malformed_reg_row_skipped_and_reported():
    staff = _seed_staff()
    rows = [
        _company_row(2, "Bad Reg Co", "not-a-reg"),
        _company_row(3, "Good (Pty) Ltd", "2015/123456/07"),
    ]
    _, result = _run(rows, im.COMPANIES, staff)

    assert result.inserted == 1  # only the well-formed row loaded
    assert len(result.skipped) == 1
    assert result.skipped[0][0] == 2
    assert "no entity type" in result.skipped[0][2]
    assert db.session.scalar(db.select(Client).where(Client.legal_name == "Bad Reg Co")) is None


# --- VAT pairing across re-runs ---


def test_vat_removed_on_rerun_clears_category_and_method():
    staff = _seed_staff()
    _run([_company_row(2, "Vatco (Pty) Ltd", "2015/123456/07", vat="B")], im.COMPANIES, staff)
    c = db.session.scalar(db.select(Client).where(Client.registration_number == "2015/123456/07"))
    assert c.has_vat is True
    assert c.vat_submission_method is VatSubmissionMethod.EFILING

    # De-registers for VAT in the corrected list — must not trip the has_vat=False invariant.
    _run(
        [_company_row(2, "Vatco (Pty) Ltd", "2015/123456/07", vat="Not registered")],
        im.COMPANIES,
        staff,
    )

    db.session.refresh(c)
    assert c.has_vat is False
    assert c.vat_category is None
    assert c.vat_submission_method is None


def test_manual_vat_method_preserved_on_rerun():
    staff = _seed_staff()
    _run([_company_row(2, "Vatco (Pty) Ltd", "2015/123456/07", vat="B")], im.COMPANIES, staff)
    c = db.session.scalar(db.select(Client).where(Client.registration_number == "2015/123456/07"))
    c.vat_submission_method = VatSubmissionMethod.MANUAL  # human corrects the default
    db.session.commit()

    _run([_company_row(2, "Vatco (Pty) Ltd", "2015/123456/07", vat="B")], im.COMPANIES, staff)

    db.session.refresh(c)
    assert c.vat_submission_method is VatSubmissionMethod.MANUAL  # not clobbered by re-import
