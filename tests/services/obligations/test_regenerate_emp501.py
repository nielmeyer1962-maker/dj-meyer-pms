from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.services.obligations.regenerate import regenerate

# A reference date with no prior-year overlap, so EMP501 yields exactly the current tax
# year's interim + annual reconciliations.
TODAY = date(2026, 6, 13)
EMP501_TYPES = (ObligationType.EMP501_INTERIM, ObligationType.EMP501_ANNUAL)


def _make_client(
    *,
    has_paye: bool = True,
    legal_name: str = "EMP501 Regenerate Corp",
) -> Client:
    """PAYE client with no VAT, so regenerate produces only EMP501 rows (assertions filter
    on type regardless)."""
    c = Client(
        legal_name=legal_name,
        entity_type=EntityType.PTY_LTD,
        has_vat=False,
        has_paye=has_paye,
    )
    db.session.add(c)
    db.session.commit()
    return c


def _emp501_rows(client_id: int) -> list[ObligationInstance]:
    return [
        r
        for r in db.session.scalars(
            db.select(ObligationInstance).where(ObligationInstance.client_id == client_id)
        )
        if r.obligation_type in EMP501_TYPES
    ]


def _seed_emp501(
    client_id: int,
    obligation_type: ObligationType,
    period_end: date,
    status: ObligationStatus,
) -> ObligationInstance:
    oi = ObligationInstance(
        client_id=client_id,
        obligation_type=obligation_type,
        period_start=date(period_end.year, 3, 1),
        period_end=period_end,
        submission_due_date=period_end,
        payment_due_date=period_end,
        status=status,
    )
    db.session.add(oi)
    db.session.commit()
    return oi


def test_emp501_generation_is_idempotent(app):
    """Two regenerate runs yield the same interim+annual rows — no duplicates."""
    with app.app_context():
        client = _make_client()
        regenerate(client, today=TODAY)
        db.session.commit()
        first = {(r.obligation_type, r.period_end) for r in _emp501_rows(client.id)}
        assert first == {
            (ObligationType.EMP501_INTERIM, date(2026, 8, 31)),
            (ObligationType.EMP501_ANNUAL, date(2027, 2, 28)),
        }

        regenerate(client, today=TODAY)
        db.session.commit()
        rows = _emp501_rows(client.id)
        assert len(rows) == 2
        assert {(r.obligation_type, r.period_end) for r in rows} == first


def test_gate_off_generates_nothing_then_on_generates_two(app):
    """has_paye False → no EMP501 rows; flipping it True and regenerating brings in the
    interim + annual reconciliations."""
    with app.app_context():
        client = _make_client(has_paye=False)
        regenerate(client, today=TODAY)
        db.session.commit()
        assert _emp501_rows(client.id) == []

        client.has_paye = True
        db.session.commit()
        regenerate(client, today=TODAY)
        db.session.commit()
        assert len(_emp501_rows(client.id)) == 2


def test_past_pending_emp501_row_is_not_pruned(app):
    """A PENDING EMP501 row whose period_end is already past is real outstanding work and
    survives a regenerate even though it is no longer generated."""
    with app.app_context():
        client = _make_client()
        stale = _seed_emp501(
            client.id, ObligationType.EMP501_ANNUAL, date(2020, 2, 29), ObligationStatus.PENDING
        )

        result = regenerate(client, today=TODAY)
        db.session.commit()

        assert db.session.get(ObligationInstance, stale.id) is not None
        assert result.deleted == 0
        assert len(_emp501_rows(client.id)) == 3  # the stale row + the two current ones


def test_future_non_generated_emp501_row_is_pruned(app):
    """A FUTURE PENDING EMP501 row the generator no longer produces is pruned like any
    other future non-generated PENDING row."""
    with app.app_context():
        client = _make_client()
        orphan = _seed_emp501(
            client.id, ObligationType.EMP501_INTERIM, date(2030, 8, 31), ObligationStatus.PENDING
        )

        regenerate(client, today=TODAY)
        db.session.commit()

        assert db.session.get(ObligationInstance, orphan.id) is None
        assert {(r.obligation_type, r.period_end) for r in _emp501_rows(client.id)} == {
            (ObligationType.EMP501_INTERIM, date(2026, 8, 31)),
            (ObligationType.EMP501_ANNUAL, date(2027, 2, 28)),
        }
