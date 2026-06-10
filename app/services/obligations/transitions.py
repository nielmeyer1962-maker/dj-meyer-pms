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


def mark_in_progress(instance: ObligationInstance) -> None:
    """PENDING → IN_PROGRESS. Raises ValueError if instance.status is not PENDING.

    The "I've started this" signal. IN_PROGRESS still counts as overdue when late (it
    is an open status, see predicates._OPEN_STATUSES) and can still advance to SUBMITTED
    or EXEMPT, or be walked back to PENDING via revert_to_pending."""
    if instance.status is not ObligationStatus.PENDING:
        _raise_illegal("mark_in_progress", instance, ObligationStatus.PENDING.name)
    instance.status = ObligationStatus.IN_PROGRESS


def revert_to_pending(instance: ObligationInstance) -> None:
    """IN_PROGRESS → PENDING. Raises ValueError if instance.status is not IN_PROGRESS.

    Undo for an accidental "Start": returns an in-progress row to the not-yet-started
    PENDING state."""
    if instance.status is not ObligationStatus.IN_PROGRESS:
        _raise_illegal("revert_to_pending", instance, ObligationStatus.IN_PROGRESS.name)
    instance.status = ObligationStatus.PENDING


def mark_submitted(instance: ObligationInstance) -> None:
    """PENDING or IN_PROGRESS → SUBMITTED. Raises ValueError from any other state.

    IN_PROGRESS is an accepted prior state so work that was explicitly started can be
    submitted directly without a detour back through PENDING."""
    if instance.status not in (ObligationStatus.PENDING, ObligationStatus.IN_PROGRESS):
        _raise_illegal(
            "mark_submitted",
            instance,
            f"{ObligationStatus.PENDING.name} or {ObligationStatus.IN_PROGRESS.name}",
        )
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
            f"{ObligationStatus.PENDING.name}, {ObligationStatus.IN_PROGRESS.name} "
            f"or {ObligationStatus.SUBMITTED.name}",
        )
    instance.status = ObligationStatus.EXEMPT
