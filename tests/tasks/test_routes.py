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
    assert "Overdue" not in body
