"""Regenerate-with-preservation for CIPC Annual Return instances — the parallel of
services/obligations/regenerate.py for the separate CIPCAnnualInstance model.

Adds the current-cycle AR, refreshes the due date on a still-GENERATED row whose
deadline shifted (e.g. holiday-data change), and deletes GENERATED rows whose
anniversary is no longer generated. Any row past GENERATED (INVOICED → ... → CLOSED)
is never touched — it preserves workflow history. Caller owns the commit.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

from app.extensions import db
from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
from app.models.client import Client
from app.models.staff import Staff
from app.services.cipc.generate import generate_cipc_annual

# CIPC work is centralised to this staff member (Secretarial).
_CIPC_STAFF_CODE = "TSEGO"


class RegenerateCIPCResult(NamedTuple):
    added: int
    updated: int
    deleted: int


def _tsego_id() -> int | None:
    """Resolve the active Tsego staff id, or None if absent/inactive (instance then
    surfaces as unassigned rather than blocking generation)."""
    staff = db.session.scalar(db.select(Staff).where(Staff.code == _CIPC_STAFF_CODE))
    if staff is None or not staff.active:
        return None
    return staff.id


def regenerate_cipc(client: Client, today: date | None = None) -> RegenerateCIPCResult:
    """Synchronise this client's CIPCAnnualInstance rows with the current cycle.

    Adds the newly-surfaced AR, refreshes the due date on a still-GENERATED row, and
    deletes GENERATED rows no longer generated. Rows past GENERATED are preserved.
    Caller owns the commit.
    """
    existing: dict[date, CIPCAnnualInstance] = {
        row.anniversary_date: row
        for row in db.session.scalars(
            db.select(CIPCAnnualInstance).where(CIPCAnnualInstance.client_id == client.id)
        )
    }

    generated_by_anniversary: dict[date, CIPCAnnualInstance] = {
        inst.anniversary_date: inst
        for inst in generate_cipc_annual(client, today=today, assignee_id=_tsego_id())
    }

    added = updated = deleted = 0

    for anniversary, new_inst in generated_by_anniversary.items():
        old_inst = existing.get(anniversary)
        if old_inst is None:
            db.session.add(new_inst)
            added += 1
            continue
        # Only a still-GENERATED row may be refreshed; once the workflow has advanced
        # the dates are part of the record and must not move under Tsego.
        if old_inst.status is not CIPCAnnualStatus.GENERATED:
            continue
        if old_inst.due_date != new_inst.due_date:
            old_inst.due_date = new_inst.due_date
            updated += 1

    # Prune GENERATED rows whose anniversary is no longer generated. Terminal/in-flight
    # rows (INVOICED → ... → CLOSED) survive untouched — they preserve workflow history.
    for anniversary, old_inst in existing.items():
        if anniversary in generated_by_anniversary:
            continue
        if old_inst.status is CIPCAnnualStatus.GENERATED:
            db.session.delete(old_inst)
            deleted += 1

    return RegenerateCIPCResult(added=added, updated=updated, deleted=deleted)
