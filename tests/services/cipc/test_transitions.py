import pytest

# Register every mapped class so SQLAlchemy can configure the Client→Staff /
# CIPCAnnualInstance relationships when an instance is constructed. Without this, running
# this pure-unit module in isolation fails to locate 'Staff'/'Client' in the registry.
from app.models import client, obligation, staff, task  # noqa: F401
from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
from app.services.cipc.transitions import (
    mark_ar_submitted,
    mark_bo_submitted,
    mark_closed,
    mark_invoice_paid,
    mark_invoiced,
)

# In-memory instances are enough — transitions are pure status mutations and never
# touch the session.


def _instance(status: CIPCAnnualStatus) -> CIPCAnnualInstance:
    return CIPCAnnualInstance(status=status)


# Ordered (function, required_from, resulting) edges of the state machine.
_EDGES = [
    (mark_invoiced, CIPCAnnualStatus.GENERATED, CIPCAnnualStatus.INVOICED),
    (mark_invoice_paid, CIPCAnnualStatus.INVOICED, CIPCAnnualStatus.INVOICE_PAID),
    (mark_bo_submitted, CIPCAnnualStatus.INVOICE_PAID, CIPCAnnualStatus.BO_SUBMITTED),
    (mark_ar_submitted, CIPCAnnualStatus.BO_SUBMITTED, CIPCAnnualStatus.AR_SUBMITTED),
    (mark_closed, CIPCAnnualStatus.AR_SUBMITTED, CIPCAnnualStatus.CLOSED),
]


@pytest.mark.parametrize("fn,required_from,resulting", _EDGES)
def test_legal_transition_advances(fn, required_from, resulting):
    inst = _instance(required_from)
    fn(inst)
    assert inst.status is resulting


@pytest.mark.parametrize("fn,required_from,resulting", _EDGES)
def test_transition_from_any_other_state_raises(fn, required_from, resulting):
    """Each transition is legal only from its exact predecessor; every other state
    raises ValueError (covers idempotency on the already-advanced state too)."""
    for status in CIPCAnnualStatus:
        if status is required_from:
            continue
        inst = _instance(status)
        with pytest.raises(ValueError):
            fn(inst)


def test_full_happy_path_walk():
    inst = _instance(CIPCAnnualStatus.GENERATED)
    mark_invoiced(inst)
    mark_invoice_paid(inst)
    mark_bo_submitted(inst)
    mark_ar_submitted(inst)
    mark_closed(inst)
    assert inst.status is CIPCAnnualStatus.CLOSED


def test_ar_cannot_be_submitted_before_bo():
    """The regulatory mandate: AR_SUBMITTED is unreachable until BO_SUBMITTED. Trying to
    file the AR straight after paying the invoice raises."""
    inst = _instance(CIPCAnnualStatus.INVOICE_PAID)
    with pytest.raises(ValueError):
        mark_ar_submitted(inst)
    # And the state is unchanged after the rejected transition.
    assert inst.status is CIPCAnnualStatus.INVOICE_PAID


def test_bo_cannot_be_skipped_from_generated():
    """BO cannot be reached without first invoicing and paying."""
    inst = _instance(CIPCAnnualStatus.GENERATED)
    with pytest.raises(ValueError):
        mark_bo_submitted(inst)
