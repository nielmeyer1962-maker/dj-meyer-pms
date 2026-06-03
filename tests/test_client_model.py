import pytest

from app.extensions import db
from app.models.client import Client, EntityType, VatCategory, VatSubmissionMethod
from app.models.staff import Staff, StaffRole

# --- Happy paths ---


def test_client_defaults(app):
    with app.app_context():
        c = Client(legal_name="Test Corp", entity_type=EntityType.PTY_LTD)
        db.session.add(c)
        db.session.commit()
        assert c.id is not None
        assert c.active is True
        assert c.bbee_applicable is False
        assert c.trading_name is None
        assert c.created_at is not None


def test_client_archive(app):
    with app.app_context():
        c = Client(legal_name="Old Corp", entity_type=EntityType.CC)
        db.session.add(c)
        db.session.commit()
        c.active = False
        db.session.commit()
        assert db.session.get(Client, c.id).active is False


def test_client_tax_registrations(app):
    with app.app_context():
        c = Client(
            legal_name="VAT Corp",
            entity_type=EntityType.PTY_LTD,
            has_income_tax=True,
            has_vat=True,
        )
        db.session.add(c)
        db.session.commit()
        assert c.has_income_tax is True
        assert c.has_vat is True
        assert c.has_paye is False
        assert c.has_provisional_tax is False
        assert c.has_dividends_tax is False


def test_client_year_end_valid(app):
    with app.app_context():
        c = Client(
            legal_name="March Corp",
            entity_type=EntityType.PTY_LTD,
            year_end_month=3,
            year_end_day=31,
        )
        db.session.add(c)
        db.session.commit()
        assert c.year_end_month == 3
        assert c.year_end_day == 31


def test_all_entity_types_persist(app):
    with app.app_context():
        for etype in EntityType:
            db.session.add(Client(legal_name=f"Test {etype.value}", entity_type=etype))
        db.session.commit()
        count = db.session.scalar(db.select(db.func.count()).select_from(Client))
        assert count == len(EntityType)


# --- Invariant: legal_name ---


def test_legal_name_empty_raises(app):
    with app.app_context():
        with pytest.raises(ValueError, match="legal_name"):
            Client(legal_name="", entity_type=EntityType.PTY_LTD)


def test_legal_name_blank_raises(app):
    with app.app_context():
        with pytest.raises(ValueError, match="legal_name"):
            Client(legal_name="   ", entity_type=EntityType.PTY_LTD)


# --- Invariant: year_end_month range ---


def test_year_end_month_zero_raises(app):
    with app.app_context():
        with pytest.raises(ValueError, match="year_end_month"):
            Client(legal_name="Corp", entity_type=EntityType.PTY_LTD, year_end_month=0)


def test_year_end_month_thirteen_raises(app):
    with app.app_context():
        with pytest.raises(ValueError, match="year_end_month"):
            Client(legal_name="Corp", entity_type=EntityType.PTY_LTD, year_end_month=13)


def test_year_end_month_boundaries_valid(app):
    with app.app_context():
        for month, day in [(1, 31), (12, 31)]:
            db.session.add(
                Client(
                    legal_name=f"Month {month} Corp",
                    entity_type=EntityType.PTY_LTD,
                    year_end_month=month,
                    year_end_day=day,
                )
            )
        db.session.commit()


# --- Invariant: year_end_day valid for month ---


def test_feb_30_raises(app):
    with app.app_context():
        c = Client(legal_name="Corp", entity_type=EntityType.PTY_LTD, year_end_month=2)
        with pytest.raises(ValueError):
            c.year_end_day = 30


def test_feb_29_raises(app):
    """Feb 29 is rejected: year-ends must be valid in every year, not just leap years."""
    with app.app_context():
        c = Client(legal_name="Corp", entity_type=EntityType.PTY_LTD, year_end_month=2)
        with pytest.raises(ValueError):
            c.year_end_day = 29


def test_apr_31_raises(app):
    with app.app_context():
        c = Client(legal_name="Corp", entity_type=EntityType.PTY_LTD, year_end_month=4)
        with pytest.raises(ValueError):
            c.year_end_day = 31


def test_feb_28_valid(app):
    with app.app_context():
        c = Client(
            legal_name="Feb Corp",
            entity_type=EntityType.PTY_LTD,
            year_end_month=2,
            year_end_day=28,
        )
        db.session.add(c)
        db.session.commit()


# --- Invariant: year_end must be paired ---


def test_day_without_month_raises(app):
    with app.app_context():
        c = Client(legal_name="Corp", entity_type=EntityType.PTY_LTD)
        with pytest.raises(ValueError):
            c.year_end_day = 31


def test_month_without_day_raises_on_flush(app):
    with app.app_context():
        c = Client(legal_name="Corp", entity_type=EntityType.PTY_LTD, year_end_month=3)
        db.session.add(c)
        with pytest.raises(ValueError, match="year_end"):
            db.session.flush()
        db.session.rollback()


# --- Invariant: VAT category + submission method ---


def test_vat_client_with_category_and_method_valid(app):
    with app.app_context():
        c = Client(
            legal_name="VAT Corp A",
            entity_type=EntityType.PTY_LTD,
            has_vat=True,
            vat_category=VatCategory.A,
            vat_submission_method=VatSubmissionMethod.EFILING,
        )
        db.session.add(c)
        db.session.commit()
        assert c.vat_category is VatCategory.A
        assert c.vat_submission_method is VatSubmissionMethod.EFILING


def test_has_vat_true_with_both_vat_fields_none_valid(app):
    """Newly-registered VAT vendor whose category and method aren't yet captured."""
    with app.app_context():
        c = Client(
            legal_name="Pending VAT Corp",
            entity_type=EntityType.PTY_LTD,
            has_vat=True,
        )
        db.session.add(c)
        db.session.commit()
        assert c.has_vat is True
        assert c.vat_category is None
        assert c.vat_submission_method is None


def test_has_vat_false_with_category_raises_on_flush(app):
    with app.app_context():
        c = Client(
            legal_name="Non-VAT Corp",
            entity_type=EntityType.PTY_LTD,
            has_vat=False,
            vat_category=VatCategory.A,
        )
        db.session.add(c)
        with pytest.raises(ValueError, match="has_vat is False"):
            db.session.flush()
        db.session.rollback()


def test_has_vat_false_with_method_raises_on_flush(app):
    with app.app_context():
        c = Client(
            legal_name="Non-VAT Corp",
            entity_type=EntityType.PTY_LTD,
            has_vat=False,
            vat_submission_method=VatSubmissionMethod.EFILING,
        )
        db.session.add(c)
        with pytest.raises(ValueError, match="has_vat is False"):
            db.session.flush()
        db.session.rollback()


def test_vat_category_without_method_raises_on_flush(app):
    """Pairing rule: vat_category set, vat_submission_method None -> must raise."""
    with app.app_context():
        c = Client(
            legal_name="Half-Config Corp",
            entity_type=EntityType.PTY_LTD,
            has_vat=True,
            vat_category=VatCategory.A,
        )
        db.session.add(c)
        with pytest.raises(ValueError, match="both be set or both be None"):
            db.session.flush()
        db.session.rollback()


def test_vat_category_invalid_string_raises(app):
    with app.app_context():
        with pytest.raises(ValueError, match="vat_category"):
            Client(
                legal_name="Corp",
                entity_type=EntityType.PTY_LTD,
                has_vat=True,
                vat_category="Z",
            )


# --- CIPC anniversary: happy path + month range ---


def test_cipc_anniversary_valid(app):
    with app.app_context():
        c = Client(
            legal_name="Anniversary Corp",
            entity_type=EntityType.PTY_LTD,
            cipc_anniversary_month=7,
            cipc_anniversary_day=15,
        )
        db.session.add(c)
        db.session.commit()
        assert c.cipc_anniversary_month == 7
        assert c.cipc_anniversary_day == 15


def test_cipc_anniversary_month_zero_raises(app):
    with app.app_context():
        with pytest.raises(ValueError, match="cipc_anniversary_month"):
            Client(legal_name="Corp", entity_type=EntityType.PTY_LTD, cipc_anniversary_month=0)


def test_cipc_anniversary_month_thirteen_raises(app):
    with app.app_context():
        with pytest.raises(ValueError, match="cipc_anniversary_month"):
            Client(legal_name="Corp", entity_type=EntityType.PTY_LTD, cipc_anniversary_month=13)


# --- CIPC anniversary: day valid for month ---


def test_cipc_feb_30_raises(app):
    with app.app_context():
        c = Client(legal_name="Corp", entity_type=EntityType.PTY_LTD, cipc_anniversary_month=2)
        with pytest.raises(ValueError):
            c.cipc_anniversary_day = 30


def test_cipc_apr_31_raises(app):
    with app.app_context():
        c = Client(legal_name="Corp", entity_type=EntityType.PTY_LTD, cipc_anniversary_month=4)
        with pytest.raises(ValueError):
            c.cipc_anniversary_day = 31


# --- CIPC anniversary: must be paired ---


def test_cipc_day_without_month_raises(app):
    with app.app_context():
        c = Client(legal_name="Corp", entity_type=EntityType.PTY_LTD)
        with pytest.raises(ValueError):
            c.cipc_anniversary_day = 15


def test_cipc_month_without_day_raises_on_flush(app):
    with app.app_context():
        c = Client(legal_name="Corp", entity_type=EntityType.PTY_LTD, cipc_anniversary_month=7)
        db.session.add(c)
        with pytest.raises(ValueError, match="cipc_anniversary"):
            db.session.flush()
        db.session.rollback()


# --- Allocation: FK + ON DELETE SET NULL ---


def test_allocated_staff_assignment_valid(app):
    with app.app_context():
        s = Staff(code="NIEL", full_name="Niel Meyer", role=StaffRole.TAX)
        db.session.add(s)
        db.session.commit()
        c = Client(
            legal_name="Allocated Corp",
            entity_type=EntityType.PTY_LTD,
            allocated_staff_id=s.id,
        )
        db.session.add(c)
        db.session.commit()
        assert c.allocated_staff_id == s.id
        assert c.allocated_staff is s


def test_allocated_staff_set_null_on_staff_delete(app):
    """Hard-deleting a staff member reverts their clients to unallocated rather
    than blocking the delete (ON DELETE SET NULL)."""
    with app.app_context():
        s = Staff(code="CAND", full_name="Candice", role=StaffRole.TAX)
        db.session.add(s)
        db.session.commit()
        c = Client(
            legal_name="Reassign Corp",
            entity_type=EntityType.PTY_LTD,
            allocated_staff_id=s.id,
        )
        db.session.add(c)
        db.session.commit()

        db.session.delete(s)
        db.session.commit()
        db.session.refresh(c)
        assert c.allocated_staff_id is None
