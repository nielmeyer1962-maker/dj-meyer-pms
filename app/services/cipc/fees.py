"""CIPC Annual Return fee derivation (Ticket 4g Chunk 5).

Looks the fee up from the cipc_ar_fees reference table (seeded by migration) by
entity_class and turnover. Bands are half-open [turnover_lower, turnover_upper).

Only the ON-TIME fee is derivable today; fee_late is NULL in the seed pending Tsego's
confirmed figures, so fee_late_for returns None until those are filled in.

Turnover note: the reference table stores turnover in RAND, while
CIPCAnnualInstance.annual_turnover_cents is in cents. The instance-level helpers convert
cents → rand (Decimal) before the band lookup.
"""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.cipc import CIPCAnnualInstance
from app.models.cipc_ar_fee import ENTITY_CLASS_CC, ENTITY_CLASS_COMPANY, CIPCARFee
from app.models.client import EntityType

# EntityType → fee entity_class. Companies (Pty Ltd / INC / NPC) share one schedule; CCs
# have their own. Other entity types do not file a CIPC AR and have no fee class.
_ENTITY_CLASS_BY_TYPE = {
    EntityType.PTY_LTD: ENTITY_CLASS_COMPANY,
    EntityType.INC: ENTITY_CLASS_COMPANY,
    EntityType.NPC: ENTITY_CLASS_COMPANY,
    EntityType.CC: ENTITY_CLASS_CC,
}


def entity_class_for(entity_type: EntityType) -> str:
    """Map an EntityType to its CIPC fee entity_class ('company' | 'cc').

    Raises ValueError for entity types that do not file a CIPC AR.
    """
    try:
        return _ENTITY_CLASS_BY_TYPE[entity_type]
    except KeyError as exc:
        raise ValueError(f"{entity_type.name} does not file a CIPC annual return") from exc


def _band_fee_on_time(entity_class: str, turnover_rand: Decimal) -> Decimal:
    """Look up the on-time fee for a turnover (in rand) within an entity_class.

    Half-open match: turnover_lower <= turnover < turnover_upper (NULL upper = top band).
    Raises ValueError if turnover is negative or no band matches (a seed gap).
    """
    if turnover_rand < 0:
        raise ValueError(f"turnover must be >= 0, got {turnover_rand}")
    row = db.session.scalar(
        db.select(CIPCARFee).where(
            CIPCARFee.entity_class == entity_class,
            CIPCARFee.turnover_lower <= turnover_rand,
            db.or_(
                CIPCARFee.turnover_upper.is_(None),
                CIPCARFee.turnover_upper > turnover_rand,
            ),
        )
    )
    if row is None:
        raise ValueError(
            f"no cipc_ar_fees band for entity_class={entity_class!r}, turnover={turnover_rand}"
        )
    return row.fee_on_time


def fee_on_time_for(instance: CIPCAnnualInstance) -> Decimal | None:
    """The on-time CIPC AR fee (in rand) for the instance, derived from its client's
    entity type and captured turnover. Returns None when turnover is not yet captured —
    the fee is unknown until the AFS turnover is entered.
    """
    if instance.annual_turnover_cents is None:
        return None
    entity_class = entity_class_for(instance.client.entity_type)
    turnover_rand = Decimal(instance.annual_turnover_cents) / 100
    return _band_fee_on_time(entity_class, turnover_rand)
