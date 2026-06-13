from __future__ import annotations

from datetime import date

import pytest

from app.dashboard.items import (
    CIPC_TYPE_LABEL,
    KIND_CIPC,
    KIND_OBLIGATION,
    from_cipc,
    from_obligation,
)

# Register every mapped class so SQLAlchemy can configure the relationships when an
# instance is constructed in-memory (no session/app context needed for a pure mapper).
from app.models import client, obligation, staff, task  # noqa: F401
from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.models.staff import Staff, StaffRole

TODAY = date(2026, 5, 13)
YESTERDAY = date(2026, 5, 12)
TOMORROW = date(2026, 5, 14)


def _client() -> Client:
    return Client(legal_name="Adapter Test Corp", entity_type=EntityType.PTY_LTD)


def _staff() -> Staff:
    return Staff(code="NIEL", full_name="Niel Meyer", role=StaffRole.TAX)


def _obligation(
    status: ObligationStatus,
    due: date = TODAY,
    *,
    client_obj: Client | None = None,
    assignee: Staff | None = None,
) -> ObligationInstance:
    return ObligationInstance(
        id=1,
        obligation_type=ObligationType.VAT201,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        submission_due_date=due,
        payment_due_date=due,
        status=status,
        client=client_obj,
        assignee=assignee,
        notes=None,
    )


def _cipc(
    status: CIPCAnnualStatus,
    due: date = TODAY,
    *,
    client_obj: Client | None = None,
    assignee: Staff | None = None,
) -> CIPCAnnualInstance:
    return CIPCAnnualInstance(
        id=7,
        anniversary_date=date(2026, 3, 15),
        due_date=due,
        status=status,
        client=client_obj,
        assignee=assignee,
        notes=None,
    )


def _keys(item) -> list[str]:
    return [a.key for a in item.actions]


# --- Obligation mapper: field bridging ---


def test_obligation_field_bridging_and_passthrough():
    c = _client()
    s = _staff()
    oi = _obligation(ObligationStatus.PENDING, client_obj=c, assignee=s)
    item = from_obligation(oi, TODAY)
    assert item.kind == KIND_OBLIGATION
    assert item.id == 1
    assert item.client is c  # passthrough, not flattened
    assert item.assignee is s
    assert item.type_label == "VAT201"  # from obligation_type
    assert item.period_label == "2026-04-30"  # period_end ISO
    assert item.due_date == TODAY  # bridged from submission_due_date
    assert item.status_name == "PENDING"


def test_obligation_emp201_type_label():
    oi = _obligation(ObligationStatus.PENDING)
    oi.obligation_type = ObligationType.EMP201
    assert from_obligation(oi, TODAY).type_label == "EMP201"


# --- Obligation mapper: predicate-driven overdue (matches is_overdue) ---


@pytest.mark.parametrize(
    "status,due,expected",
    [
        (ObligationStatus.PENDING, YESTERDAY, True),
        (ObligationStatus.PENDING, TODAY, False),  # strict <
        (ObligationStatus.IN_PROGRESS, YESTERDAY, True),
        (ObligationStatus.SUBMITTED, YESTERDAY, False),
        (ObligationStatus.PAID, YESTERDAY, False),
        (ObligationStatus.EXEMPT, YESTERDAY, False),
    ],
)
def test_obligation_overdue_is_predicate_driven(status, due, expected):
    assert from_obligation(_obligation(status, due), TODAY).is_overdue is expected


# --- Obligation mapper: action list + open/reassignable per status ---


@pytest.mark.parametrize(
    "status,expected_keys,expected_open",
    [
        (
            ObligationStatus.PENDING,
            ["mark_in_progress", "mark_submitted", "mark_exempt"],
            True,
        ),
        (
            ObligationStatus.IN_PROGRESS,
            ["mark_submitted", "revert_to_pending", "mark_exempt"],
            True,
        ),
        (ObligationStatus.SUBMITTED, ["mark_paid", "mark_exempt"], True),
        (ObligationStatus.PAID, [], False),
        (ObligationStatus.EXEMPT, [], False),
    ],
)
def test_obligation_actions_and_open_per_status(status, expected_keys, expected_open):
    item = from_obligation(_obligation(status), TODAY)
    assert _keys(item) == expected_keys
    assert item.is_open is expected_open
    assert item.reassignable is expected_open


def test_every_obligation_status_has_an_action_entry():
    """Guard against an enum value added without a corresponding action list (KeyError)."""
    for status in ObligationStatus:
        assert from_obligation(_obligation(status), TODAY) is not None


@pytest.mark.parametrize("status", list(ObligationStatus))
def test_obligation_is_open_is_negation_of_is_done(status):
    """is_open / reassignable are delegated to the model's is_done, not re-derived from
    the status set — so file-only types (done at SUBMITTED) and payment-leg types (done
    at PAID) are both judged by the same rule the rest of the app uses."""
    oi = _obligation(status)
    item = from_obligation(oi, TODAY)
    assert item.is_open is (not oi.is_done)
    assert item.reassignable is (not oi.is_done)


# --- Obligation mapper: file-only types are terminal at SUBMITTED (Ticket 4a) ---


@pytest.mark.parametrize(
    "status,expected_keys,expected_open",
    [
        (
            ObligationStatus.PENDING,
            ["mark_in_progress", "mark_submitted", "mark_exempt"],
            True,
        ),
        (
            ObligationStatus.IN_PROGRESS,
            ["mark_submitted", "revert_to_pending", "mark_exempt"],
            True,
        ),
        # File-only (ITR14) is done at SUBMITTED → terminal: no actions, not open.
        (ObligationStatus.SUBMITTED, [], False),
        (ObligationStatus.EXEMPT, [], False),
    ],
)
def test_file_only_obligation_actions_and_open_per_status(status, expected_keys, expected_open):
    oi = _obligation(status)
    oi.obligation_type = ObligationType.ITR14  # has_payment_leg is False
    item = from_obligation(oi, TODAY)
    assert _keys(item) == expected_keys
    assert item.is_open is expected_open
    assert item.reassignable is expected_open


def test_file_only_never_offers_mark_paid_in_any_status():
    """A file-only obligation must never expose the payment-leg-only 'mark_paid' action,
    in any status — the action set is gated on is_done, not hardcoded per type."""
    for status in ObligationStatus:
        oi = _obligation(status)
        oi.obligation_type = ObligationType.ITR14
        assert "mark_paid" not in _keys(from_obligation(oi, TODAY))


def test_payment_leg_submitted_still_offers_mark_paid():
    """Contrast with the file-only case: a payment-leg type (VAT201) at SUBMITTED is NOT
    done, so it keeps Mark paid. The fix is keyed on is_done, not a blanket removal."""
    item = from_obligation(_obligation(ObligationStatus.SUBMITTED), TODAY)
    assert _keys(item) == ["mark_paid", "mark_exempt"]
    assert item.is_open is True


# --- CIPC mapper: field bridging ---


def test_cipc_field_bridging_and_passthrough():
    c = _client()
    s = _staff()
    inst = _cipc(CIPCAnnualStatus.GENERATED, client_obj=c, assignee=s)
    item = from_cipc(inst, TODAY)
    assert item.kind == KIND_CIPC
    assert item.id == 7
    assert item.client is c
    assert item.assignee is s
    assert item.type_label == CIPC_TYPE_LABEL  # "CIPC AR"
    assert item.period_label == "—"  # CIPC has no reporting period
    assert item.due_date == TODAY  # bridged from due_date
    assert item.status_name == "GENERATED"


# --- CIPC mapper: predicate-driven overdue (matches is_overdue) ---


@pytest.mark.parametrize(
    "status,due,expected",
    [
        (CIPCAnnualStatus.GENERATED, YESTERDAY, True),
        (CIPCAnnualStatus.GENERATED, TODAY, False),  # strict <
        (CIPCAnnualStatus.BO_SUBMITTED, YESTERDAY, True),
        # Filed: deadline met, never overdue even if past.
        (CIPCAnnualStatus.AR_SUBMITTED, YESTERDAY, False),
        (CIPCAnnualStatus.CLOSED, YESTERDAY, False),
        (CIPCAnnualStatus.DECLINED, YESTERDAY, False),
    ],
)
def test_cipc_overdue_is_predicate_driven(status, due, expected):
    assert from_cipc(_cipc(status, due), TODAY).is_overdue is expected


# --- CIPC mapper: action list + open/reassignable per status ---


@pytest.mark.parametrize(
    "status,expected_keys,expected_open",
    [
        (CIPCAnnualStatus.GENERATED, ["mark_invoiced", "mark_declined"], True),
        (CIPCAnnualStatus.INVOICED, ["mark_invoice_paid", "mark_declined"], True),
        (CIPCAnnualStatus.INVOICE_PAID, ["mark_bo_submitted", "mark_declined"], True),
        (CIPCAnnualStatus.BO_SUBMITTED, ["mark_ar_submitted", "mark_declined"], True),
        # AR filed: only close remains, no decline off-ramp.
        (CIPCAnnualStatus.AR_SUBMITTED, ["mark_closed"], True),
        (CIPCAnnualStatus.CLOSED, [], False),
        (CIPCAnnualStatus.DECLINED, [], False),
    ],
)
def test_cipc_actions_and_open_per_status(status, expected_keys, expected_open):
    item = from_cipc(_cipc(status), TODAY)
    assert _keys(item) == expected_keys
    assert item.is_open is expected_open
    assert item.reassignable is expected_open


def test_cipc_decline_offered_exactly_on_pre_filing_states():
    """The decline action appears on, and only on, the four pre-filing states — the same
    set mark_declined accepts."""
    declinable = {
        status
        for status in CIPCAnnualStatus
        if "mark_declined" in _keys(from_cipc(_cipc(status), TODAY))
    }
    assert declinable == {
        CIPCAnnualStatus.GENERATED,
        CIPCAnnualStatus.INVOICED,
        CIPCAnnualStatus.INVOICE_PAID,
        CIPCAnnualStatus.BO_SUBMITTED,
    }


# --- ITR12 confirmation: file-only wiring covers it with no adapter change (Ticket 4b) ---


def test_itr12_is_terminal_at_submitted_via_adapter():
    """ITR12 is file-only, so the data-driven is_done gating makes SUBMITTED terminal —
    no actions, not open, never 'mark_paid'. No adapter change was needed for IT12."""
    oi = _obligation(ObligationStatus.SUBMITTED)
    oi.obligation_type = ObligationType.ITR12
    item = from_obligation(oi, TODAY)
    assert item.actions == ()
    assert item.is_open is False
    assert "mark_paid" not in _keys(item)


def test_itr12_pending_offers_no_mark_paid_via_adapter():
    oi = _obligation(ObligationStatus.PENDING)
    oi.obligation_type = ObligationType.ITR12
    item = from_obligation(oi, TODAY)
    assert _keys(item) == ["mark_in_progress", "mark_submitted", "mark_exempt"]
    assert "mark_paid" not in _keys(item)


# --- IRP6 (provisional tax): payment-leg actions + window/voluntary display ---


def _irp6(status: ObligationStatus, window_code: str = "01") -> ObligationInstance:
    oi = _obligation(status)
    oi.obligation_type = ObligationType.IRP6
    oi.window_code = window_code
    return oi


def test_irp6_pending_offers_submit_action():
    """IRP6 is data-driven through the status-keyed action map, so PENDING exposes the
    submit transition automatically — no IRP6-specific branch."""
    item = from_obligation(_irp6(ObligationStatus.PENDING), TODAY)
    assert "mark_submitted" in _keys(item)


def test_irp6_submitted_offers_pay_action():
    """IRP6 carries a payment leg (is_done only at PAID), so a SUBMITTED IRP6 is still open
    and offers Mark paid — exactly like VAT201, derived from has_payment_leg."""
    item = from_obligation(_irp6(ObligationStatus.SUBMITTED), TODAY)
    assert "mark_paid" in _keys(item)
    assert item.is_open is True


def test_irp6_window_code_propagates_and_third_is_voluntary():
    for code in ("01", "02"):
        item = from_obligation(_irp6(ObligationStatus.PENDING, code), TODAY)
        assert item.window_code == code
        assert item.is_voluntary is False
    third = from_obligation(_irp6(ObligationStatus.PENDING, "03"), TODAY)
    assert third.window_code == "03"
    assert third.is_voluntary is True


def test_non_irp6_has_no_window_or_voluntary_flag():
    """A VAT201 row leaves the IRP6-only display hints unset."""
    item = from_obligation(_obligation(ObligationStatus.PENDING), TODAY)
    assert item.window_code is None
    assert item.is_voluntary is False
