"""CIPC Annual Return state-machine transitions (Ticket 4g Chunk 4).

The sole documented happy path for CIPCAnnualInstance status changes. Mirrors the
ObligationInstance transitions convention: free functions that mutate the instance in
place and return None; the caller owns the session and the commit. No DB CHECK
constraint and no before_update listener — direct ORM writes remain the admin-override
escape hatch.

The six states are strictly ordered:

    GENERATED → INVOICED → INVOICE_PAID → BO_SUBMITTED → AR_SUBMITTED → CLOSED

Each transition requires its exact predecessor state, which enforces the regulatory
mandate that BENEFICIAL OWNERSHIP precedes the Annual Return: since 15 Apr 2024 CIPC
blocks AR filing unless BO is already on file, so mark_ar_submitted is reachable only
from BO_SUBMITTED — BO_SUBMITTED can never be skipped.

Idempotency: calling a transition on an already-advanced row raises ValueError rather
than silently no-opping, so an incorrect call path surfaces instead of hiding.
"""

from __future__ import annotations

from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus


def _raise_illegal(action: str, instance: CIPCAnnualInstance, legal_from: str) -> None:
    raise ValueError(
        f"cannot {action} on CIPCAnnualInstance(id={instance.id}, "
        f"status={instance.status.name}); legal prior state is {legal_from}."
    )


def _advance(
    instance: CIPCAnnualInstance,
    action: str,
    required_from: CIPCAnnualStatus,
    to: CIPCAnnualStatus,
) -> None:
    if instance.status is not required_from:
        _raise_illegal(action, instance, required_from.name)
    instance.status = to


def mark_invoiced(instance: CIPCAnnualInstance) -> None:
    """GENERATED → INVOICED. Raises ValueError if status is not GENERATED."""
    _advance(instance, "mark_invoiced", CIPCAnnualStatus.GENERATED, CIPCAnnualStatus.INVOICED)


def mark_invoice_paid(instance: CIPCAnnualInstance) -> None:
    """INVOICED → INVOICE_PAID. Raises ValueError if status is not INVOICED.

    Manual: Tsego checks QuickBooks and marks the invoice paid (no integration)."""
    _advance(
        instance, "mark_invoice_paid", CIPCAnnualStatus.INVOICED, CIPCAnnualStatus.INVOICE_PAID
    )


def mark_bo_submitted(instance: CIPCAnnualInstance) -> None:
    """INVOICE_PAID → BO_SUBMITTED. Raises ValueError if status is not INVOICE_PAID."""
    _advance(
        instance,
        "mark_bo_submitted",
        CIPCAnnualStatus.INVOICE_PAID,
        CIPCAnnualStatus.BO_SUBMITTED,
    )


def mark_ar_submitted(instance: CIPCAnnualInstance) -> None:
    """BO_SUBMITTED → AR_SUBMITTED. Raises ValueError if status is not BO_SUBMITTED.

    BO_SUBMITTED is the only legal prior state, which is exactly the CIPC mandate that
    Beneficial Ownership must be filed before the Annual Return."""
    _advance(
        instance,
        "mark_ar_submitted",
        CIPCAnnualStatus.BO_SUBMITTED,
        CIPCAnnualStatus.AR_SUBMITTED,
    )


def mark_closed(instance: CIPCAnnualInstance) -> None:
    """AR_SUBMITTED → CLOSED. Raises ValueError if status is not AR_SUBMITTED."""
    _advance(instance, "mark_closed", CIPCAnnualStatus.AR_SUBMITTED, CIPCAnnualStatus.CLOSED)
