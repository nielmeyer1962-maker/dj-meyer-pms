from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import (
    _PAYMENT_LEG_TYPES,
    ObligationInstance,
    ObligationStatus,
    ObligationType,
)
from app.models.staff import Staff, StaffRole

# --- Helpers ---


def _make_client(legal_name: str = "VAT Test Corp") -> Client:
    """Create and persist a minimal Client for FK use; returns the Client."""
    c = Client(legal_name=legal_name, entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    return c


def _instance_kwargs(client_id: int, period_end: date) -> dict:
    """Minimum-viable kwargs for an ObligationInstance — adjust per test."""
    return dict(
        client_id=client_id,
        obligation_type=ObligationType.VAT201,
        period_start=date(period_end.year, period_end.month, 1),
        period_end=period_end,
        submission_due_date=period_end,
        payment_due_date=period_end,
    )


# --- Happy paths ---


def test_obligation_instance_persists(app):
    with app.app_context():
        c = _make_client()
        oi = ObligationInstance(**_instance_kwargs(c.id, date(2026, 4, 30)))
        db.session.add(oi)
        db.session.commit()
        assert oi.id is not None
        assert oi.obligation_type is ObligationType.VAT201
        assert oi.period_start == date(2026, 4, 1)
        assert oi.period_end == date(2026, 4, 30)


def test_status_defaults_to_pending(app):
    with app.app_context():
        c = _make_client()
        oi = ObligationInstance(**_instance_kwargs(c.id, date(2026, 4, 30)))
        db.session.add(oi)
        db.session.commit()
        assert oi.status is ObligationStatus.PENDING


def test_timestamps_auto_populate(app):
    with app.app_context():
        c = _make_client()
        oi = ObligationInstance(**_instance_kwargs(c.id, date(2026, 4, 30)))
        db.session.add(oi)
        db.session.commit()
        assert oi.generated_at is not None
        assert oi.updated_at is not None


def test_all_obligation_statuses_persist(app):
    """Every ObligationStatus value is storable — no enum-coercion surprises."""
    with app.app_context():
        c = _make_client()
        for i, status in enumerate(ObligationStatus, start=1):
            db.session.add(
                ObligationInstance(
                    status=status,
                    **_instance_kwargs(c.id, date(2026, i, 28)),
                )
            )
        db.session.commit()
        count = db.session.scalar(db.select(db.func.count()).select_from(ObligationInstance))
        assert count == len(ObligationStatus)


# --- Invariants ---


def test_unique_constraint_on_client_type_period(app):
    """Generator idempotency: (client_id, obligation_type, period_end) is unique."""
    with app.app_context():
        c = _make_client()
        kwargs = _instance_kwargs(c.id, date(2026, 4, 30))
        db.session.add(ObligationInstance(**kwargs))
        db.session.commit()

        db.session.add(ObligationInstance(**kwargs))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_client_fk_ondelete_restrict(app):
    """FK on client_id is RESTRICT so client deletion cannot orphan submission history."""
    fk = next(iter(ObligationInstance.__table__.c.client_id.foreign_keys))
    assert fk.ondelete == "RESTRICT"


# --- assignee_id (Ticket 3b §B3) ---


def _make_staff(code: str = "NIEL", full_name: str = "Niel Meyer") -> Staff:
    s = Staff(code=code, full_name=full_name, role=StaffRole.TAX)
    db.session.add(s)
    db.session.commit()
    return s


def test_assignee_id_nullable(app):
    """A fresh ObligationInstance with assignee_id=None persists — Unassigned is
    a first-class state."""
    with app.app_context():
        c = _make_client()
        oi = ObligationInstance(assignee_id=None, **_instance_kwargs(c.id, date(2026, 4, 30)))
        db.session.add(oi)
        db.session.commit()
        assert oi.id is not None
        assert oi.assignee_id is None


def test_assignee_id_persists_with_valid_staff_fk(app):
    with app.app_context():
        c = _make_client()
        s = _make_staff()
        oi = ObligationInstance(assignee_id=s.id, **_instance_kwargs(c.id, date(2026, 4, 30)))
        db.session.add(oi)
        db.session.commit()
        assert oi.assignee_id == s.id


def test_assignee_fk_set_null_on_staff_delete(app):
    """Hard-deleting a Staff row reverts assigned obligations to assignee_id=None,
    not blocked. Requires SQLite PRAGMA foreign_keys = ON (see conftest)."""
    with app.app_context():
        c = _make_client()
        s = _make_staff()
        oi = ObligationInstance(assignee_id=s.id, **_instance_kwargs(c.id, date(2026, 4, 30)))
        db.session.add(oi)
        db.session.commit()
        assert oi.assignee_id == s.id

        db.session.delete(s)
        db.session.commit()
        db.session.refresh(oi)
        assert oi.assignee_id is None


# --- notes (Ticket 3c §C2) ---


def test_notes_column_behaviour(app):
    """notes defaults to None, persists arbitrary text, and accepts None explicitly."""
    with app.app_context():
        c = _make_client()

        # Default: omitted on construction → None after commit.
        oi_default = ObligationInstance(**_instance_kwargs(c.id, date(2026, 1, 31)))
        db.session.add(oi_default)
        db.session.commit()
        db.session.refresh(oi_default)
        assert oi_default.notes is None

        # Arbitrary text persists round-trip.
        text = "Client emailed VAT invoice 2026-04-30; awaiting bank proof of payment."
        oi_text = ObligationInstance(notes=text, **_instance_kwargs(c.id, date(2026, 2, 28)))
        db.session.add(oi_text)
        db.session.commit()
        db.session.refresh(oi_text)
        assert oi_text.notes == text

        # Explicit None is accepted at construction time.
        oi_none = ObligationInstance(notes=None, **_instance_kwargs(c.id, date(2026, 3, 31)))
        db.session.add(oi_none)
        db.session.commit()
        db.session.refresh(oi_none)
        assert oi_none.notes is None


# --- ObligationStatus finalisation: IN_PROGRESS, has_payment_leg, is_done ---


def test_in_progress_sits_between_pending_and_submitted():
    """IN_PROGRESS is declared between PENDING and SUBMITTED in the lifecycle order."""
    assert [s.name for s in ObligationStatus] == [
        "PENDING",
        "IN_PROGRESS",
        "SUBMITTED",
        "PAID",
        "EXEMPT",
    ]


def test_vat201_has_payment_leg():
    assert ObligationType.VAT201.has_payment_leg is True


def test_itr12_is_file_only():
    """ITR12 (individual income-tax return) is file-only — like ITR14, it is absent from
    _PAYMENT_LEG_TYPES, so has_payment_leg is False and it is done at SUBMITTED."""
    assert ObligationType.ITR12.value not in _PAYMENT_LEG_TYPES
    assert ObligationType.ITR12.has_payment_leg is False


def test_itr12_is_done_at_submitted():
    """A file-only ITR12 is finished once SUBMITTED (no payment leg); EXEMPT is also done,
    PENDING/IN_PROGRESS are not. is_done is a pure property, so no DB is needed."""
    oi = ObligationInstance(obligation_type=ObligationType.ITR12)
    for status, expected in (
        (ObligationStatus.PENDING, False),
        (ObligationStatus.IN_PROGRESS, False),
        (ObligationStatus.SUBMITTED, True),
        (ObligationStatus.EXEMPT, True),
    ):
        oi.status = status
        assert oi.is_done is expected


def test_payment_leg_map_covers_future_types():
    """The payment-leg map is keyed by enum value; VAT201, EMP201 and IRP6 are all
    now ObligationType members and all carry a payment leg."""
    assert _PAYMENT_LEG_TYPES == {"VAT201", "EMP201", "IRP6"}


def test_irp6_is_a_member_with_payment_leg():
    """IRP6 (provisional tax) is a payment-leg type — filed and paid, so done at PAID."""
    assert ObligationType.IRP6.value == "IRP6"
    assert ObligationType.IRP6.value in _PAYMENT_LEG_TYPES
    assert ObligationType.IRP6.has_payment_leg is True


def test_irp6_is_done_at_paid():
    """IRP6 carries a payment leg, so a SUBMITTED-but-unpaid provisional return is not
    finished; only PAID (or EXEMPT) counts as done."""
    oi = ObligationInstance(obligation_type=ObligationType.IRP6)
    for status, expected in (
        (ObligationStatus.PENDING, False),
        (ObligationStatus.IN_PROGRESS, False),
        (ObligationStatus.SUBMITTED, False),
        (ObligationStatus.PAID, True),
        (ObligationStatus.EXEMPT, True),
    ):
        oi.status = status
        assert oi.is_done is expected


def test_window_code_column_behaviour(app):
    """window_code defaults to None (every non-IRP6 row leaves it unset) and round-trips
    the IRP6 period markers "01"/"02"/"03"."""
    with app.app_context():
        c = _make_client()

        # Default: a VAT201 row leaves window_code NULL.
        oi_default = ObligationInstance(**_instance_kwargs(c.id, date(2026, 8, 31)))
        db.session.add(oi_default)
        db.session.commit()
        db.session.refresh(oi_default)
        assert oi_default.window_code is None

        # An IRP6 row stores its window marker (and the IRP6 enum value round-trips).
        oi_irp6 = ObligationInstance(
            client_id=c.id,
            obligation_type=ObligationType.IRP6,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 8, 31),
            submission_due_date=date(2026, 8, 31),
            payment_due_date=date(2026, 8, 31),
            window_code="01",
        )
        db.session.add(oi_irp6)
        db.session.commit()
        db.session.refresh(oi_irp6)
        assert oi_irp6.obligation_type is ObligationType.IRP6
        assert oi_irp6.window_code == "01"


@pytest.mark.parametrize(
    "status,expected",
    [
        (ObligationStatus.PENDING, False),
        (ObligationStatus.IN_PROGRESS, False),
        (ObligationStatus.SUBMITTED, False),  # filed but unpaid → not done
        (ObligationStatus.PAID, True),
        (ObligationStatus.EXEMPT, True),
    ],
)
def test_is_done_for_payment_leg_obligation(app, status, expected):
    """VAT201 carries a payment leg, so done means PAID (or EXEMPT) — a SUBMITTED-but-
    unpaid return is not finished."""
    with app.app_context():
        c = _make_client()
        oi = ObligationInstance(status=status, **_instance_kwargs(c.id, date(2026, 4, 30)))
        db.session.add(oi)
        db.session.commit()
        assert oi.is_done is expected


def test_is_done_for_filing_only_obligation():
    """A file-only obligation (no payment leg) is done once SUBMITTED, and EXEMPT is
    always done. Uses a stub obligation_type because no file-only type is enum-modelled
    yet; is_done reads only obligation_type.has_payment_leg and status."""
    oi = ObligationInstance()
    oi.obligation_type = SimpleNamespace(has_payment_leg=False)

    oi.status = ObligationStatus.SUBMITTED
    assert oi.is_done is True
    oi.status = ObligationStatus.PENDING
    assert oi.is_done is False
    oi.status = ObligationStatus.IN_PROGRESS
    assert oi.is_done is False
    oi.status = ObligationStatus.EXEMPT
    assert oi.is_done is True
