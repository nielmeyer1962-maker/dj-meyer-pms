from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.task import Task


def _make_client(legal_name: str = "Acme Pty Ltd") -> Client:
    """Create and persist a minimal Client for FK use."""
    c = Client(legal_name=legal_name, entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    return c


def test_list_tasks_renders_empty_state(client):
    """GET /dashboard/tasks/ with no tasks: 200 + the empty-state copy."""
    resp = client.get("/dashboard/tasks/")
    assert resp.status_code == 200
    assert "No tasks yet." in resp.data.decode()


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
