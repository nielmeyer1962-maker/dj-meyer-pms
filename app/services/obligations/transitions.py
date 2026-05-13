from __future__ import annotations

from app.models.obligation import ObligationInstance, ObligationStatus

# Sole documented happy path for ObligationInstance status changes. Per the 3a
# state-graph decision there is NO DB CHECK constraint and NO before_update
# listener — direct ORM writes remain the admin-override escape hatch (e.g.
# walking a PAID row back to EXEMPT after a SARS retroactive cancellation).
# These free functions mutate the instance in place and return None; the caller
# owns the session and the commit. updated_at advances automatically via the
# model's onupdate=func.now() at flush.
#
# Idempotency: a second call on an already-advanced row raises ValueError
# rather than no-opping silently. A silent no-op hides double-submit bugs and
# racing-tab confusion; an error surfaces the incorrect call path. The
# dashboard pre-checks status before rendering each row's action buttons, so
# legitimate flows do not reach this branch.


def _raise_illegal(action: str, instance: ObligationInstance, legal_from: str) -> None:
    raise ValueError(
        f"cannot {action} on ObligationInstance(id={instance.id}, "
        f"status={instance.status.name}); legal prior state is {legal_from}."
    )


def mark_submitted(instance: ObligationInstance) -> None:
    """PENDING → SUBMITTED. Raises ValueError if instance.status is not PENDING."""
    if instance.status is not ObligationStatus.PENDING:
        _raise_illegal("mark_submitted", instance, ObligationStatus.PENDING.name)
    instance.status = ObligationStatus.SUBMITTED


def mark_paid(instance: ObligationInstance) -> None:
    """SUBMITTED → PAID. Raises ValueError if instance.status is not SUBMITTED."""
    if instance.status is not ObligationStatus.SUBMITTED:
        _raise_illegal("mark_paid", instance, ObligationStatus.SUBMITTED.name)
    instance.status = ObligationStatus.PAID


def mark_exempt(instance: ObligationInstance) -> None:
    """Any non-terminal → EXEMPT. Raises ValueError if instance.status is PAID or EXEMPT."""
    if instance.status in (ObligationStatus.PAID, ObligationStatus.EXEMPT):
        _raise_illegal(
            "mark_exempt",
            instance,
            f"{ObligationStatus.PENDING.name} or {ObligationStatus.SUBMITTED.name}",
        )
    instance.status = ObligationStatus.EXEMPT
