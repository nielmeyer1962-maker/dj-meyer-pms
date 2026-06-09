"""Regenerate-with-preservation: synchronise an obligation_instances rowset
with what the generator says is currently due.

Adds new periods, refreshes PENDING due dates against current client config,
and deletes PENDING rows whose periods are no longer generated. SUBMITTED,
PAID, and EXEMPT rows are never touched - they preserve history. See
PROJECT_PLAN.md Ticket 3c §C1 for the locked behaviour and decisions.

Caller owns the commit.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

from app.extensions import db
from app.models.client import Client
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.services.obligations.emp201 import generate_emp201
from app.services.obligations.vat201 import generate_vat201


class RegenerateResult(NamedTuple):
    added: int
    updated: int
    deleted: int


def regenerate(client: Client, today: date | None = None) -> RegenerateResult:
    """Synchronise this client's obligation_instances with current config.

    Adds new periods, refreshes due dates on PENDING rows whose periods are
    still valid, and deletes PENDING rows whose periods are no longer
    generated. SUBMITTED, PAID, EXEMPT rows are never touched.

    The today parameter mirrors generate_vat201(today=...) — production
    callers leave it None; tests inject a fixed date.

    Caller owns the commit. NotImplementedError from a Cat E generator call
    propagates; the caller's existing (ValueError, NotImplementedError)
    handler in the regenerate route catches it.
    """
    existing: dict[tuple[ObligationType, date], ObligationInstance] = {
        (row.obligation_type, row.period_end): row
        for row in db.session.scalars(
            db.select(ObligationInstance).where(ObligationInstance.client_id == client.id)
        )
    }

    # Each generator gates on its own registration flag and returns only its own
    # obligation_type, so their period keys never collide.
    generated_by_key: dict[tuple[ObligationType, date], ObligationInstance] = {
        (inst.obligation_type, inst.period_end): inst
        for inst in (*generate_vat201(client, today=today), *generate_emp201(client, today=today))
    }

    added = updated = deleted = 0

    # Add new periods; refresh PENDING rows whose dates have shifted.
    for key, new_inst in generated_by_key.items():
        old_inst = existing.get(key)
        if old_inst is None:
            db.session.add(new_inst)
            added += 1
            continue
        if old_inst.status is not ObligationStatus.PENDING:
            continue
        if (
            old_inst.submission_due_date != new_inst.submission_due_date
            or old_inst.payment_due_date != new_inst.payment_due_date
        ):
            old_inst.submission_due_date = new_inst.submission_due_date
            old_inst.payment_due_date = new_inst.payment_due_date
            updated += 1

    # Prune PENDING rows whose periods are no longer generated. Terminal-state
    # rows (SUBMITTED / PAID / EXEMPT) survive untouched per the locked rule:
    # they preserve history even when the client's VAT config changes.
    for key, old_inst in existing.items():
        if key in generated_by_key:
            continue
        if old_inst.status is ObligationStatus.PENDING:
            db.session.delete(old_inst)
            deleted += 1

    return RegenerateResult(added=added, updated=updated, deleted=deleted)
