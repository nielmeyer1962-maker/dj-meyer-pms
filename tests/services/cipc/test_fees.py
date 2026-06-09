from decimal import Decimal

import pytest

from app.extensions import db
from app.models.cipc import CIPCAnnualInstance
from app.models.cipc_ar_fee import CIPC_AR_FEE_SEED, CIPC_AR_LATE_PENALTY, CIPCARFee
from app.models.client import Client, EntityType
from app.services.cipc.fees import entity_class_for, fee_late_for, fee_on_time_for

# Rand → cents (the instance stores annual_turnover_cents).
R = 100


def _seed_fees() -> None:
    db.session.add_all(CIPCARFee(**row) for row in CIPC_AR_FEE_SEED)
    db.session.commit()


def _instance(entity_type: EntityType, turnover_rand: int | None) -> CIPCAnnualInstance:
    from datetime import date

    c = Client(legal_name="Fee Corp", entity_type=entity_type)
    db.session.add(c)
    db.session.commit()
    inst = CIPCAnnualInstance(
        client_id=c.id,
        anniversary_date=date(2026, 3, 16),
        due_date=date(2026, 4, 30),
        annual_turnover_cents=None if turnover_rand is None else turnover_rand * R,
    )
    db.session.add(inst)
    db.session.commit()
    return inst


# --- entity_class_for ---


@pytest.mark.parametrize(
    "entity_type,expected",
    [
        (EntityType.PTY_LTD, "company"),
        (EntityType.INC, "company"),
        (EntityType.NPC, "company"),
        (EntityType.CC, "cc"),
    ],
)
def test_entity_class_for(entity_type, expected):
    assert entity_class_for(entity_type) == expected


@pytest.mark.parametrize(
    "entity_type",
    [EntityType.INDIVIDUAL, EntityType.SOLE_PROP, EntityType.TRUST, EntityType.PARTNERSHIP],
)
def test_entity_class_for_non_filing_raises(entity_type):
    with pytest.raises(ValueError):
        entity_class_for(entity_type)


# --- Company on-time fee, half-open bands [lower, upper) ---


@pytest.mark.parametrize(
    "turnover_rand,expected_fee",
    [
        (0, 100),
        (999_999, 100),
        (1_000_000, 450),  # upper bound is EXCLUSIVE → exactly R1m falls in the next band
        (9_999_999, 450),
        (10_000_000, 2000),
        (24_999_999, 2000),
        (25_000_000, 3000),  # top band lower bound is inclusive
        (500_000_000, 3000),
    ],
)
def test_company_on_time_fee(app, turnover_rand, expected_fee):
    with app.app_context():
        _seed_fees()
        inst = _instance(EntityType.PTY_LTD, turnover_rand)
        assert fee_on_time_for(inst) == Decimal(expected_fee)


# --- CC on-time fee ---


@pytest.mark.parametrize(
    "turnover_rand,expected_fee",
    [
        (0, 100),
        (49_999_999, 100),
        (50_000_000, 4000),  # exclusive upper → exactly R50m is the top CC band
        (250_000_000, 4000),
    ],
)
def test_cc_on_time_fee(app, turnover_rand, expected_fee):
    with app.app_context():
        _seed_fees()
        inst = _instance(EntityType.CC, turnover_rand)
        assert fee_on_time_for(inst) == Decimal(expected_fee)


# --- Company late fee = on-time + R150 ---


@pytest.mark.parametrize(
    "turnover_rand,expected_fee",
    [
        (0, 250),
        (1_000_000, 600),
        (10_000_000, 2150),
        (25_000_000, 3150),
    ],
)
def test_company_late_fee(app, turnover_rand, expected_fee):
    with app.app_context():
        _seed_fees()
        inst = _instance(EntityType.PTY_LTD, turnover_rand)
        assert fee_late_for(inst) == Decimal(expected_fee)


# --- CC late fee = on-time + R150 ---


@pytest.mark.parametrize(
    "turnover_rand,expected_fee",
    [
        (0, 250),
        (50_000_000, 4150),
    ],
)
def test_cc_late_fee(app, turnover_rand, expected_fee):
    with app.app_context():
        _seed_fees()
        inst = _instance(EntityType.CC, turnover_rand)
        assert fee_late_for(inst) == Decimal(expected_fee)


# --- Penalty recoverable for billing: late - on-time == R150 ---


@pytest.mark.parametrize(
    "entity_type,turnover_rand",
    [
        (EntityType.PTY_LTD, 0),
        (EntityType.PTY_LTD, 25_000_000),
        (EntityType.CC, 0),
        (EntityType.CC, 50_000_000),
    ],
)
def test_late_minus_on_time_is_fixed_penalty(app, entity_type, turnover_rand):
    with app.app_context():
        _seed_fees()
        inst = _instance(entity_type, turnover_rand)
        assert fee_late_for(inst) - fee_on_time_for(inst) == CIPC_AR_LATE_PENALTY
        assert CIPC_AR_LATE_PENALTY == Decimal(150)


# --- Uncaptured turnover ---


def test_fee_none_when_turnover_uncaptured(app):
    with app.app_context():
        _seed_fees()
        inst = _instance(EntityType.PTY_LTD, None)
        assert fee_on_time_for(inst) is None
        assert fee_late_for(inst) is None
