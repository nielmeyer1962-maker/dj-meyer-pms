from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.services.obligations.regenerate import regenerate

# A reference date where the Feb-year-end client's prior-YOA 03 has lapsed, so IRP6
# generation yields exactly the current YOA's three windows.
TODAY = date(2026, 11, 1)


def _make_client(
    *,
    has_provisional_tax: bool = True,
    year_end_month: int | None = 2,
    year_end_day: int | None = 28,
    legal_name: str = "IRP6 Regenerate Corp",
) -> Client:
    """Provisional-tax client with no VAT/PAYE, so regenerate produces only IRP6 rows
    (plus any annual returns, which the assertions ignore by filtering on type)."""
    c = Client(
        legal_name=legal_name,
        entity_type=EntityType.PTY_LTD,
        has_vat=False,
        has_paye=False,
        has_provisional_tax=has_provisional_tax,
        year_end_month=year_end_month,
        year_end_day=year_end_day,
    )
    db.session.add(c)
    db.session.commit()
    return c


def _irp6_rows(client_id: int) -> list[ObligationInstance]:
    return [
        r
        for r in db.session.scalars(
            db.select(ObligationInstance).where(ObligationInstance.client_id == client_id)
        )
        if r.obligation_type is ObligationType.IRP6
    ]


def _seed_irp6(
    client_id: int,
    period_end: date,
    status: ObligationStatus,
    window_code: str,
) -> ObligationInstance:
    oi = ObligationInstance(
        client_id=client_id,
        obligation_type=ObligationType.IRP6,
        period_start=date(period_end.year - 1, 3, 1),
        period_end=period_end,
        submission_due_date=period_end,
        payment_due_date=period_end,
        status=status,
        window_code=window_code,
    )
    db.session.add(oi)
    db.session.commit()
    return oi


def test_irp6_generation_is_idempotent(app):
    """Running regenerate twice yields the same three IRP6 rows — no duplicates (the
    (client, type, period_end) unique key holds)."""
    with app.app_context():
        client = _make_client()
        regenerate(client, today=TODAY)
        db.session.commit()
        first = {r.period_end for r in _irp6_rows(client.id)}
        assert first == {date(2026, 8, 31), date(2027, 2, 28), date(2027, 9, 30)}

        regenerate(client, today=TODAY)
        db.session.commit()
        rows = _irp6_rows(client.id)
        assert len(rows) == 3
        assert {r.period_end for r in rows} == first


def test_gate_off_generates_nothing_then_on_generates_three(app):
    """has_provisional_tax False → no IRP6 rows; flipping it True and regenerating brings
    the three windows in."""
    with app.app_context():
        client = _make_client(has_provisional_tax=False)
        regenerate(client, today=TODAY)
        db.session.commit()
        assert _irp6_rows(client.id) == []

        client.has_provisional_tax = True
        db.session.commit()
        regenerate(client, today=TODAY)
        db.session.commit()
        assert len(_irp6_rows(client.id)) == 3


def test_past_pending_irp6_row_is_not_pruned(app):
    """A PENDING IRP6 row whose period_end is already past is real outstanding work and
    must survive a regenerate, even though it's no longer in the generated set."""
    with app.app_context():
        client = _make_client()
        stale = _seed_irp6(client.id, date(2020, 2, 29), ObligationStatus.PENDING, "02")

        result = regenerate(client, today=TODAY)
        db.session.commit()

        surviving = {r.period_end for r in _irp6_rows(client.id)}
        assert date(2020, 2, 29) in surviving  # past PENDING row preserved
        assert db.session.get(ObligationInstance, stale.id) is not None
        # Only the three current windows were added; nothing deleted.
        assert len(surviving) == 4
        assert result.deleted == 0


def test_voluntary_third_gets_no_special_prune_treatment(app):
    """A FUTURE PENDING window-03 row that the generator no longer produces is pruned just
    like any other future non-generated PENDING row — being the voluntary top-up earns it
    no exemption."""
    with app.app_context():
        client = _make_client()
        orphan = _seed_irp6(client.id, date(2030, 9, 30), ObligationStatus.PENDING, "03")

        regenerate(client, today=TODAY)
        db.session.commit()

        # The far-future voluntary 03 is gone; only the three current windows remain.
        assert db.session.get(ObligationInstance, orphan.id) is None
        assert {r.period_end for r in _irp6_rows(client.id)} == {
            date(2026, 8, 31),
            date(2027, 2, 28),
            date(2027, 9, 30),
        }
