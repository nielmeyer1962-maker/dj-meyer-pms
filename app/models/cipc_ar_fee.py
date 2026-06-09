from __future__ import annotations

from decimal import Decimal

from sqlalchemy import CheckConstraint, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

# entity_class values. Companies (Pty Ltd / INC / NPC) share one CIPC AR fee schedule;
# close corporations have their own (Schedule 1 of the CC Administrative Regulations).
ENTITY_CLASS_COMPANY = "company"
ENTITY_CLASS_CC = "cc"


class CIPCARFee(db.Model):
    """Turnover-banded CIPC Annual Return fee reference table (Ticket 4g Chunk 5).

    A reference/lookup table seeded by migration, keyed by entity_class. Bands are
    half-open [turnover_lower, turnover_upper): the lower bound is inclusive and the
    upper bound is exclusive; a NULL upper bound is the open-ended top band. Money and
    turnover are stored as Decimal (Numeric) in RAND — turnover compares against the
    instance's annual_turnover converted to rand.

    fee_late is nullable and intentionally left NULL on seed: Tsego's late-filing figures
    are not yet supplied, and whether a late filing is (on-time fee + penalty) or a flat
    late total — and whether it is fixed per band or accrues daily — is still to be
    confirmed (see the migration note).
    """

    __tablename__ = "cipc_ar_fees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 'company' (Pty Ltd / INC / NPC) or 'cc'.
    entity_class: Mapped[str] = mapped_column(String(16), nullable=False)
    # Inclusive lower bound of the turnover band, in rand.
    turnover_lower: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # Exclusive upper bound, in rand. NULL = open-ended top band.
    turnover_upper: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    # On-time AR fee for the band, in rand.
    fee_on_time: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # Late-filing fee, in rand. Nullable; left NULL until confirmed.
    fee_late: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"entity_class IN ('{ENTITY_CLASS_COMPANY}', '{ENTITY_CLASS_CC}')",
            name="ck_cipc_ar_fees_entity_class",
        ),
        # Lookup is always "rows for this entity_class, ordered by lower bound".
        Index("ix_cipc_ar_fees_class_lower", "entity_class", "turnover_lower"),
    )

    def __repr__(self) -> str:
        return (
            f"<CIPCARFee {self.entity_class} [{self.turnover_lower}, {self.turnover_upper}) "
            f"on_time={self.fee_on_time} late={self.fee_late}>"
        )


# Canonical seed for the reference table — the single source of truth, imported by both
# the seeding migration and the test fixtures so they cannot drift. Bands are half-open
# [turnover_lower, turnover_upper); amounts in rand.
#   On-time fees: confirmed by Tsego, 2026-06-09, CIPC fee schedule.
#   fee_late: intentionally None — Tsego's late-filing figures are not yet supplied, and
#     whether a late filing is (on-time fee + penalty) or a flat total, and fixed-per-band
#     vs daily-accrual, is unconfirmed. A daily accrual would not fit this single column.
CIPC_AR_FEE_SEED: list[dict] = [
    # company (Pty Ltd / INC / NPC)
    {
        "entity_class": ENTITY_CLASS_COMPANY,
        "turnover_lower": 0,
        "turnover_upper": 1_000_000,
        "fee_on_time": 100,
        "fee_late": None,
    },
    {
        "entity_class": ENTITY_CLASS_COMPANY,
        "turnover_lower": 1_000_000,
        "turnover_upper": 10_000_000,
        "fee_on_time": 450,
        "fee_late": None,
    },
    {
        "entity_class": ENTITY_CLASS_COMPANY,
        "turnover_lower": 10_000_000,
        "turnover_upper": 25_000_000,
        "fee_on_time": 2000,
        "fee_late": None,
    },
    {
        "entity_class": ENTITY_CLASS_COMPANY,
        "turnover_lower": 25_000_000,
        "turnover_upper": None,
        "fee_on_time": 3000,
        "fee_late": None,
    },
    # close corporation
    {
        "entity_class": ENTITY_CLASS_CC,
        "turnover_lower": 0,
        "turnover_upper": 50_000_000,
        "fee_on_time": 100,
        "fee_late": None,
    },
    {
        "entity_class": ENTITY_CLASS_CC,
        "turnover_lower": 50_000_000,
        "turnover_upper": None,
        "fee_on_time": 4000,
        "fee_late": None,
    },
]
