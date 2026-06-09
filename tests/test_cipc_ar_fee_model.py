from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.cipc_ar_fee import (
    CIPC_AR_FEE_SEED,
    CIPC_AR_LATE_PENALTY,
    ENTITY_CLASS_CC,
    ENTITY_CLASS_COMPANY,
    CIPCARFee,
)


def _seed(session) -> None:
    session.add_all(CIPCARFee(**row) for row in CIPC_AR_FEE_SEED)
    session.commit()


def test_seed_inserts_expected_bands(app):
    with app.app_context():
        _seed(db.session)
        rows = db.session.scalars(db.select(CIPCARFee)).all()
        assert len(rows) == 6
        assert sum(1 for r in rows if r.entity_class == ENTITY_CLASS_COMPANY) == 4
        assert sum(1 for r in rows if r.entity_class == ENTITY_CLASS_CC) == 2


def test_seed_late_is_on_time_plus_fixed_penalty(app):
    """fee_late = fee_on_time + R150, flat across every band (Niel, 2026-06-09)."""
    with app.app_context():
        _seed(db.session)
        rows = db.session.scalars(db.select(CIPCARFee)).all()
        assert CIPC_AR_LATE_PENALTY == Decimal("150")
        assert all(r.fee_late is not None for r in rows)
        assert all(r.fee_late - r.fee_on_time == CIPC_AR_LATE_PENALTY for r in rows)


def test_company_top_band_has_null_upper_and_3000(app):
    with app.app_context():
        _seed(db.session)
        top = db.session.scalar(
            db.select(CIPCARFee).where(
                CIPCARFee.entity_class == ENTITY_CLASS_COMPANY,
                CIPCARFee.turnover_upper.is_(None),
            )
        )
        assert top.turnover_lower == Decimal("25000000")
        assert top.fee_on_time == Decimal("3000")


def test_cc_bands_are_100_then_4000(app):
    with app.app_context():
        _seed(db.session)
        cc = db.session.scalars(
            db.select(CIPCARFee)
            .where(CIPCARFee.entity_class == ENTITY_CLASS_CC)
            .order_by(CIPCARFee.turnover_lower)
        ).all()
        assert [(r.turnover_lower, r.turnover_upper, r.fee_on_time) for r in cc] == [
            (Decimal("0"), Decimal("50000000"), Decimal("100")),
            (Decimal("50000000"), None, Decimal("4000")),
        ]


def test_entity_class_check_constraint_rejects_unknown(app):
    """The CHECK constraint allows only 'company' | 'cc'. Requires Postgres/SQLite to
    enforce CHECK (SQLite enforces CHECK constraints by default)."""
    with app.app_context():
        db.session.add(
            CIPCARFee(
                entity_class="trust",
                turnover_lower=0,
                turnover_upper=None,
                fee_on_time=100,
            )
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
