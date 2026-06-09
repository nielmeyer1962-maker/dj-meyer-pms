from datetime import date

from app.extensions import db
from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
from app.models.client import Client, EntityType
from app.models.staff import Staff, StaffRole
from app.services.cipc.regenerate import RegenerateCIPCResult, regenerate_cipc

TODAY = date(2026, 2, 1)


def _make_client(
    *,
    entity_type: EntityType = EntityType.PTY_LTD,
    anniversary_month: int | None = 3,
    anniversary_day: int | None = 16,
    legal_name: str = "CIPC Regen Corp",
) -> Client:
    c = Client(
        legal_name=legal_name,
        entity_type=entity_type,
        cipc_anniversary_month=anniversary_month,
        cipc_anniversary_day=anniversary_day,
    )
    db.session.add(c)
    db.session.commit()
    return c


def _make_tsego() -> Staff:
    s = Staff(code="TSEGO", full_name="Tsego Mogale", role=StaffRole.SECRETARIAL)
    db.session.add(s)
    db.session.commit()
    return s


def _rows(client_id: int) -> list[CIPCAnnualInstance]:
    return list(
        db.session.scalars(
            db.select(CIPCAnnualInstance).where(CIPCAnnualInstance.client_id == client_id)
        )
    )


# --- First run / idempotency ---


def test_first_run_adds_current_cycle(app):
    with app.app_context():
        c = _make_client()
        result = regenerate_cipc(c, today=TODAY)
        db.session.commit()
        assert result == RegenerateCIPCResult(added=1, updated=0, deleted=0)
        rows = _rows(c.id)
        assert len(rows) == 1
        assert rows[0].anniversary_date == date(2026, 3, 16)


def test_second_run_is_noop_and_preserves_pk(app):
    with app.app_context():
        c = _make_client()
        regenerate_cipc(c, today=TODAY)
        db.session.commit()
        pk_before = _rows(c.id)[0].id

        result = regenerate_cipc(c, today=TODAY)
        db.session.commit()
        assert result == RegenerateCIPCResult(0, 0, 0)
        assert _rows(c.id)[0].id == pk_before


def test_non_filing_client_generates_nothing(app):
    with app.app_context():
        c = _make_client(entity_type=EntityType.TRUST)
        result = regenerate_cipc(c, today=TODAY)
        db.session.commit()
        assert result == RegenerateCIPCResult(0, 0, 0)
        assert _rows(c.id) == []


# --- Assignee centralised to Tsego ---


def test_instance_assigned_to_tsego(app):
    with app.app_context():
        tsego = _make_tsego()
        c = _make_client()
        regenerate_cipc(c, today=TODAY)
        db.session.commit()
        assert _rows(c.id)[0].assignee_id == tsego.id


def test_unassigned_when_no_tsego(app):
    """No Tsego on file → instance surfaces unassigned rather than blocking generation."""
    with app.app_context():
        c = _make_client()
        regenerate_cipc(c, today=TODAY)
        db.session.commit()
        assert _rows(c.id)[0].assignee_id is None


# --- Preservation + pruning ---


def test_advanced_row_is_preserved_not_pruned(app):
    """A row past GENERATED survives even when its anniversary is no longer the current
    cycle, and its due date is not refreshed."""
    with app.app_context():
        c = _make_client()
        # Seed a stale row from a prior anniversary, already INVOICED.
        stale = CIPCAnnualInstance(
            client_id=c.id,
            anniversary_date=date(2024, 3, 16),
            due_date=date(2024, 4, 30),
            status=CIPCAnnualStatus.INVOICED,
        )
        db.session.add(stale)
        db.session.commit()
        stale_id = stale.id

        result = regenerate_cipc(c, today=TODAY)
        db.session.commit()

        # Current cycle added; stale INVOICED row untouched (not pruned, not updated).
        assert result.added == 1
        assert result.deleted == 0
        survivor = db.session.get(CIPCAnnualInstance, stale_id)
        assert survivor is not None
        assert survivor.status is CIPCAnnualStatus.INVOICED


def test_stale_generated_row_is_pruned(app):
    """A GENERATED row whose anniversary is no longer current is pruned."""
    with app.app_context():
        c = _make_client()
        stale = CIPCAnnualInstance(
            client_id=c.id,
            anniversary_date=date(2024, 3, 16),
            due_date=date(2024, 4, 30),
            status=CIPCAnnualStatus.GENERATED,
        )
        db.session.add(stale)
        db.session.commit()

        result = regenerate_cipc(c, today=TODAY)
        db.session.commit()

        assert result.added == 1
        assert result.deleted == 1
        anniversaries = {r.anniversary_date for r in _rows(c.id)}
        assert anniversaries == {date(2026, 3, 16)}
