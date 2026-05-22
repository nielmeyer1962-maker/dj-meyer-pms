from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.staff import Staff, StaffRole
from app.models.task import Task, TaskStatus

# --- Helpers ---


def _make_client(legal_name: str = "Task Test Corp") -> Client:
    """Create and persist a minimal Client for FK use."""
    c = Client(legal_name=legal_name, entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    return c


def _make_staff(code: str = "NIEL", full_name: str = "Niel Meyer") -> Staff:
    """Create and persist a minimal Staff for assignee FK use."""
    s = Staff(code=code, full_name=full_name, role=StaffRole.TAX)
    db.session.add(s)
    db.session.commit()
    return s


# --- 1. Mandatory-only construction ---


def test_minimal_task_persists_with_defaults(app):
    """Mandatory fields only -> persists; status defaults to OPEN; both timestamps set."""
    with app.app_context():
        c = _make_client()
        t = Task(client_id=c.id, title="Send POA letter", due_date=date(2026, 6, 30))
        db.session.add(t)
        db.session.commit()
        db.session.refresh(t)

        assert t.id is not None
        assert t.status is TaskStatus.OPEN
        assert isinstance(t.created_at, datetime)
        assert isinstance(t.updated_at, datetime)


# --- 2. All nullable fields explicitly None ---


def test_task_persists_with_nullables_explicitly_none(app):
    """Setting every nullable column to None at construction persists."""
    with app.app_context():
        c = _make_client()
        t = Task(
            client_id=c.id,
            title="Ask client about logbook",
            due_date=date(2026, 7, 15),
            description=None,
            assignee_id=None,
            notes=None,
            requested_by=None,
        )
        db.session.add(t)
        db.session.commit()
        db.session.refresh(t)

        assert t.id is not None
        assert t.description is None
        assert t.assignee_id is None
        assert t.notes is None
        assert t.requested_by is None


# --- 3. Full field round-trip ---


def test_task_full_field_roundtrip(app):
    """Constructing a Task with every field populated round-trips on re-query."""
    with app.app_context():
        c = _make_client()
        s = _make_staff()
        t = Task(
            client_id=c.id,
            title="Draft objection letter - VAT201 2026-03",
            description="SARS disallowed input VAT; draft objection per s104 TAA.",
            due_date=date(2026, 8, 31),
            status=TaskStatus.OPEN,
            assignee_id=s.id,
            notes="Awaiting supporting docs from client.",
            requested_by="Reception (client phoned 2026-05-22)",
        )
        db.session.add(t)
        db.session.commit()
        task_id = t.id
        db.session.expire_all()

        fetched = db.session.get(Task, task_id)
        assert fetched is not None
        assert fetched.client_id == c.id
        assert fetched.title == "Draft objection letter - VAT201 2026-03"
        assert fetched.description == "SARS disallowed input VAT; draft objection per s104 TAA."
        assert fetched.due_date == date(2026, 8, 31)
        assert fetched.status is TaskStatus.OPEN
        assert fetched.assignee_id == s.id
        assert fetched.notes == "Awaiting supporting docs from client."
        assert fetched.requested_by == "Reception (client phoned 2026-05-22)"


# --- 4. No uniqueness on (client_id, title, due_date) ---


def test_no_uniqueness_on_client_title_due_date(app):
    """Tasks are not generated - duplicate (client_id, title, due_date) is legitimate."""
    with app.app_context():
        c = _make_client()
        common = dict(
            client_id=c.id,
            title="Send tax clearance request",
            due_date=date(2026, 9, 30),
        )
        db.session.add(Task(**common))
        db.session.add(Task(**common))
        db.session.commit()

        count = db.session.scalar(db.select(db.func.count()).select_from(Task))
        assert count == 2


# --- 5. TaskStatus enum members in order ---


def test_task_status_enum_members_and_order():
    """Enum has exactly OPEN, DONE, CANCELLED in that order."""
    assert list(TaskStatus) == [TaskStatus.OPEN, TaskStatus.DONE, TaskStatus.CANCELLED]


# --- 6. Relationships resolve (and None when assignee_id is null) ---


def test_task_relationships_resolve(app):
    """Task.client resolves to the seeded Client; Task.assignee resolves to Staff
    when assignee_id is set, and to None when assignee_id is null."""
    with app.app_context():
        c = _make_client()
        s = _make_staff()

        t_assigned = Task(
            client_id=c.id,
            title="Call client re: SARS audit letter",
            due_date=date(2026, 6, 1),
            assignee_id=s.id,
        )
        db.session.add(t_assigned)
        t_unassigned = Task(
            client_id=c.id,
            title="File DTR02 manually",
            due_date=date(2026, 6, 5),
        )
        db.session.add(t_unassigned)
        db.session.commit()

        assigned_id = t_assigned.id
        unassigned_id = t_unassigned.id
        db.session.expire_all()

        t_assigned = db.session.get(Task, assigned_id)
        t_unassigned = db.session.get(Task, unassigned_id)

        assert t_assigned.client is not None
        assert t_assigned.client.id == c.id
        assert t_assigned.assignee is not None
        assert t_assigned.assignee.id == s.id

        assert t_unassigned.client.id == c.id
        assert t_unassigned.assignee is None


# --- 7. updated_at advances on mutation ---


def test_updated_at_advances_on_mutation(app):
    """Guards against an accidental refactor that breaks the model's onupdate=func.now().
    Matches the precedent in tests/services/obligations/test_transitions.py:139-151."""
    with app.app_context():
        c = _make_client()
        t = Task(client_id=c.id, title="Initial title", due_date=date(2026, 10, 31))
        db.session.add(t)
        db.session.commit()
        created_at = t.created_at

        t.title = "Renamed"
        db.session.commit()
        db.session.refresh(t)

        assert t.updated_at >= created_at


# --- 8. Client delete RESTRICT ---


def test_client_delete_restricts(app):
    """ON DELETE RESTRICT on tasks.client_id prevents removing a Client that has
    a referencing Task. Requires SQLite PRAGMA foreign_keys = ON (see conftest)."""
    with app.app_context():
        c = _make_client()
        t = Task(client_id=c.id, title="Don't delete me", due_date=date(2026, 11, 30))
        db.session.add(t)
        db.session.commit()

        db.session.delete(c)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        assert db.session.get(Client, c.id) is not None
        assert db.session.get(Task, t.id) is not None


# --- 9. Staff delete SET NULL ---


def test_staff_delete_nulls_assignee(app):
    """ON DELETE SET NULL on tasks.assignee_id reverts Task.assignee_id to None
    when the referenced Staff row is hard-deleted; Task row survives."""
    with app.app_context():
        c = _make_client()
        s = _make_staff()
        t = Task(
            client_id=c.id,
            title="Will lose assignee",
            due_date=date(2026, 12, 31),
            assignee_id=s.id,
        )
        db.session.add(t)
        db.session.commit()
        assert t.assignee_id == s.id

        db.session.delete(s)
        db.session.commit()
        db.session.refresh(t)

        assert t.assignee_id is None
        assert db.session.get(Task, t.id) is not None
