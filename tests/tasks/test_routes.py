from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.task import Task, TaskStatus


def _make_client(legal_name: str = "Acme Pty Ltd") -> Client:
    """Create and persist a minimal Client for FK use."""
    c = Client(legal_name=legal_name, entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    return c


def test_list_tasks_renders_empty_state(client):
    """GET /dashboard/tasks/ with no tasks: 200 + every section shows its
    per-status empty-state copy."""
    resp = client.get("/dashboard/tasks/")
    assert resp.status_code == 200
    assert "No tasks in this status." in resp.data.decode()


def test_list_tasks_shows_all_tasks(client):
    """Two tasks linked to a client both appear by title in the rendered list."""
    c = _make_client()
    db.session.add_all(
        [
            Task(client_id=c.id, title="Send POA letter", due_date=date(2026, 6, 30)),
            Task(client_id=c.id, title="Draft objection letter", due_date=date(2026, 7, 15)),
        ]
    )
    db.session.commit()

    resp = client.get("/dashboard/tasks/")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Send POA letter" in body
    assert "Draft objection letter" in body


def test_list_tasks_groups_by_status(client):
    """One task in each status renders under its own status section header,
    in OPEN → DONE → CANCELLED order."""
    c = _make_client()
    db.session.add_all(
        [
            Task(
                client_id=c.id,
                title="Open task",
                due_date=date(2026, 6, 30),
                status=TaskStatus.OPEN,
            ),
            Task(
                client_id=c.id,
                title="Done task",
                due_date=date(2026, 7, 15),
                status=TaskStatus.DONE,
            ),
            Task(
                client_id=c.id,
                title="Cancelled task",
                due_date=date(2026, 8, 1),
                status=TaskStatus.CANCELLED,
            ),
        ]
    )
    db.session.commit()

    body = client.get("/dashboard/tasks/").data.decode()

    open_header = body.index("OPEN (1)")
    done_header = body.index("DONE (1)")
    cancelled_header = body.index("CANCELLED (1)")

    # Each title falls between its own section header and the next.
    assert open_header < body.index("Open task") < done_header
    assert done_header < body.index("Done task") < cancelled_header
    assert cancelled_header < body.index("Cancelled task")


def test_open_task_past_due_shows_overdue_badge(client):
    """An OPEN task whose due_date is clearly in the past renders the Overdue
    badge (status == OPEN AND due_date < today_sast())."""
    c = _make_client()
    db.session.add(
        Task(
            client_id=c.id,
            title="Submit IRP6 provisional",
            due_date=date(2024, 1, 1),
            status=TaskStatus.OPEN,
        )
    )
    db.session.commit()

    body = client.get("/dashboard/tasks/").data.decode()
    assert "Submit IRP6 provisional" in body
    assert "Overdue" in body


def test_done_task_past_due_no_overdue_badge(client):
    """A DONE task with the same past due_date is not overdue — overdue is
    OPEN-only — so the badge renders nowhere on the page."""
    c = _make_client()
    db.session.add(
        Task(
            client_id=c.id,
            title="Filed ITR14",
            due_date=date(2024, 1, 1),
            status=TaskStatus.DONE,
        )
    )
    db.session.commit()

    body = client.get("/dashboard/tasks/").data.decode()
    assert "Filed ITR14" in body
    assert 'class="badge bg-danger ms-1">Overdue</span>' not in body

def test_filter_by_status_open(client):
    """?status=OPEN shows only OPEN tasks."""
    c = _make_client()
    db.session.add_all(
        [
            Task(client_id=c.id, title="Open one", due_date=date(2026, 7, 1), status=TaskStatus.OPEN),
            Task(client_id=c.id, title="Done one", due_date=date(2026, 7, 1), status=TaskStatus.DONE),
        ]
    )
    db.session.commit()

    body = client.get("/dashboard/tasks/?status=OPEN").data.decode()
    assert "Open one" in body
    assert "Done one" not in body


def test_filter_by_assignee_staff_code(client):
    """?assignee=<code> shows only tasks assigned to that staff member."""
    from app.models.staff import Staff, StaffRole

    c = _make_client()
    alice = Staff(code="ALI", full_name="Alice Smith", role=StaffRole.TAX, active=True)
    bob = Staff(code="BOB", full_name="Bob Jones", role=StaffRole.TAX, active=True)
    db.session.add_all([alice, bob])
    db.session.commit()

    db.session.add_all(
        [
            Task(client_id=c.id, title="Alice task", due_date=date(2026, 7, 1), assignee_id=alice.id),
            Task(client_id=c.id, title="Bob task", due_date=date(2026, 7, 1), assignee_id=bob.id),
        ]
    )
    db.session.commit()

    body = client.get("/dashboard/tasks/?assignee=ALI").data.decode()
    assert "Alice task" in body
    assert "Bob task" not in body


def test_filter_by_assignee_unassigned(client):
    """?assignee=__unassigned__ shows only tasks with no assignee."""
    from app.models.staff import Staff, StaffRole

    c = _make_client()
    alice = Staff(code="ALI", full_name="Alice Smith", role=StaffRole.TAX, active=True)
    db.session.add(alice)
    db.session.commit()

    db.session.add_all(
        [
            Task(client_id=c.id, title="Has assignee", due_date=date(2026, 7, 1), assignee_id=alice.id),
            Task(client_id=c.id, title="No assignee", due_date=date(2026, 7, 1), assignee_id=None),
        ]
    )
    db.session.commit()

    body = client.get("/dashboard/tasks/?assignee=__unassigned__").data.decode()
    assert "No assignee" in body
    assert "Has assignee" not in body


def test_filter_view_overdue(client):
    """?view=overdue shows only tasks that are OPEN AND due in the past."""
    c = _make_client()
    db.session.add_all(
        [
            Task(client_id=c.id, title="Overdue open", due_date=date(2024, 1, 1), status=TaskStatus.OPEN),
            Task(client_id=c.id, title="Future open", due_date=date(2099, 12, 31), status=TaskStatus.OPEN),
            Task(client_id=c.id, title="Past done", due_date=date(2024, 1, 1), status=TaskStatus.DONE),
        ]
    )
    db.session.commit()

    body = client.get("/dashboard/tasks/?view=overdue").data.decode()
    assert "Overdue open" in body
    assert "Future open" not in body
    assert "Past done" not in body


    