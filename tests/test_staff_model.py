from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.staff import Staff, StaffRole

# --- Happy path: round-trip persistence ---


def test_staff_persists_with_all_required_fields(app):
    with app.app_context():
        s = Staff(
            code="NIEL",
            full_name="Niel Meyer",
            email="niel@example.com",
            role=StaffRole.TAX,
        )
        db.session.add(s)
        db.session.commit()
        assert s.id is not None
        assert s.code == "NIEL"
        assert s.full_name == "Niel Meyer"
        assert s.email == "niel@example.com"
        assert s.role is StaffRole.TAX
        assert s.active is True  # default
        assert s.created_at is not None


def test_email_accepts_none(app):
    with app.app_context():
        s = Staff(code="CAND", full_name="Candice", role=StaffRole.TAX)
        db.session.add(s)
        db.session.commit()
        assert s.email is None


def test_active_defaults_to_true(app):
    with app.app_context():
        s = Staff(code="TSEG", full_name="Tsego", role=StaffRole.SECRETARIAL)
        db.session.add(s)
        db.session.commit()
        assert s.active is True


def test_all_staff_roles_persist(app):
    """Every StaffRole value is storable — no enum-coercion surprises."""
    with app.app_context():
        for i, role in enumerate(StaffRole, start=1):
            db.session.add(Staff(code=f"R{i}", full_name=f"Role {role.name}", role=role))
        db.session.commit()
        count = db.session.scalar(db.select(db.func.count()).select_from(Staff))
        assert count == len(StaffRole)


# --- Uniqueness ---


def test_code_unique_constraint(app):
    with app.app_context():
        db.session.add(Staff(code="NIEL", full_name="First Niel", role=StaffRole.TAX))
        db.session.commit()
        db.session.add(Staff(code="NIEL", full_name="Second Niel", role=StaffRole.TAX))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


# --- Validators ---


@pytest.mark.parametrize("bad_code", ["", " ", "  ", " NIEL", "NIEL ", "  NIEL  "])
def test_code_blank_or_whitespace_padded_raises(app, bad_code):
    with app.app_context():
        with pytest.raises(ValueError, match="code"):
            Staff(code=bad_code, full_name="Whatever", role=StaffRole.TAX)


@pytest.mark.parametrize("bad_name", ["", " ", "   "])
def test_full_name_blank_raises(app, bad_name):
    with app.app_context():
        with pytest.raises(ValueError, match="full_name"):
            Staff(code="OK", full_name=bad_name, role=StaffRole.TAX)
