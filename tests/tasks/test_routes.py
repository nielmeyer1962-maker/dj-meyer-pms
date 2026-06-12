from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.client import Client, EntityType
from app.models.staff import Staff, StaffRole
from app.models.task import Task, TaskStatus


def _make_client(legal_name: str = "Acme Pty Ltd") -> Client:
    """Create and persist a minimal Client for FK use."""
    c = Client(legal_name=legal_name, entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    return c


def _make_staff(code: str = "NIEL", full_name: str = "Niel Meyer") -> Staff:
    """Create and persist an active Staff for assignee FK use."""
    s = Staff(code=code, full_name=full_name, role=StaffRole.TAX, active=True)
    db.session.add(s)
    db.session.commit()
    return s


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


def test_list_tasks_hides_archived_client_tasks(client):
    """A task on an archived (active=False) client never renders on the board,
    while an active client's task does — mirroring the obligation/CIPC dashboard
    gating (H1 chunk 2)."""
    active = _make_client("Active Visible Ltd")
    archived = Client(
        legal_name="Archived Hidden Ltd", entity_type=EntityType.PTY_LTD, active=False
    )
    db.session.add(archived)
    db.session.commit()
    db.session.add_all(
        [
            Task(client_id=active.id, title="Visible task", due_date=date(2026, 6, 30)),
            Task(client_id=archived.id, title="Hidden task", due_date=date(2026, 6, 30)),
        ]
    )
    db.session.commit()

    body = client.get("/dashboard/tasks/").data.decode()
    assert "Visible task" in body
    assert "Hidden task" not in body


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
            Task(
                client_id=c.id, title="Open one", due_date=date(2026, 7, 1), status=TaskStatus.OPEN
            ),
            Task(
                client_id=c.id, title="Done one", due_date=date(2026, 7, 1), status=TaskStatus.DONE
            ),
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
            Task(
                client_id=c.id, title="Alice task", due_date=date(2026, 7, 1), assignee_id=alice.id
            ),
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
            Task(
                client_id=c.id,
                title="Has assignee",
                due_date=date(2026, 7, 1),
                assignee_id=alice.id,
            ),
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
            Task(
                client_id=c.id,
                title="Overdue open",
                due_date=date(2024, 1, 1),
                status=TaskStatus.OPEN,
            ),
            Task(
                client_id=c.id,
                title="Future open",
                due_date=date(2099, 12, 31),
                status=TaskStatus.OPEN,
            ),
            Task(
                client_id=c.id, title="Past done", due_date=date(2024, 1, 1), status=TaskStatus.DONE
            ),
        ]
    )
    db.session.commit()

    body = client.get("/dashboard/tasks/?view=overdue").data.decode()
    assert "Overdue open" in body
    assert "Future open" not in body
    assert "Past done" not in body


def test_task_detail_returns_200_and_renders_for_existing_task(client):
    """GET /dashboard/tasks/<id> for an existing task: 200 + the task title
    appears in the rendered detail page."""
    c = _make_client()
    t = Task(client_id=c.id, title="Prepare AFS pack", due_date=date(2026, 6, 30))
    db.session.add(t)
    db.session.commit()

    resp = client.get(f"/dashboard/tasks/{t.id}")
    assert resp.status_code == 200
    assert "Prepare AFS pack" in resp.data.decode()


def test_task_detail_returns_404_for_missing_task(client):
    """GET /dashboard/tasks/<id> for a non-existent id returns 404."""
    resp = client.get("/dashboard/tasks/99999")
    assert resp.status_code == 404


def test_task_new_get_renders_form(client):
    """GET /dashboard/tasks/new returns 200 and renders the New task form."""
    resp = client.get("/dashboard/tasks/new")
    assert resp.status_code == 200
    assert "New task" in resp.data.decode()


def test_task_new_post_valid_creates_and_assigns(client):
    """POST with a valid client and assignee creates the task, assigns it, and
    redirects to its detail page."""
    c = _make_client()
    s = _make_staff()

    resp = client.post(
        "/dashboard/tasks/new",
        data={
            "client_id": str(c.id),
            "title": "Call SARS about ITR14",
            "due_date": "2026-07-01",
            "assignee_id": str(s.id),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    task = db.session.scalars(db.select(Task)).one()
    assert task.title == "Call SARS about ITR14"
    assert task.client_id == c.id
    assert task.assignee_id == s.id
    assert resp.headers["Location"].endswith(f"/dashboard/tasks/{task.id}")


def test_task_new_post_missing_title_does_not_create(client):
    """POST without a title fails validation: 200 re-render, nothing persisted."""
    c = _make_client()

    resp = client.post(
        "/dashboard/tasks/new",
        data={"client_id": str(c.id), "title": "", "due_date": "2026-07-01"},
    )
    assert resp.status_code == 200
    assert db.session.scalar(db.select(db.func.count(Task.id))) == 0


def test_task_new_post_bad_client_id_does_not_create(client):
    """A client_id not in the live active list is rejected (validate_choice=False
    means the route must enforce membership): 200 re-render, nothing persisted."""
    _make_client()  # exists, but we POST a different id

    resp = client.post(
        "/dashboard/tasks/new",
        data={"client_id": "99999", "title": "Orphan task", "due_date": "2026-07-01"},
    )
    assert resp.status_code == 200
    assert "Select a current client." in resp.data.decode()
    assert db.session.scalar(db.select(db.func.count(Task.id))) == 0


def test_task_edit_get_prepopulates(client):
    """GET edit renders the form pre-filled with the task's current title."""
    c = _make_client()
    t = Task(client_id=c.id, title="Prepare AFS pack", due_date=date(2026, 6, 30))
    db.session.add(t)
    db.session.commit()

    resp = client.get(f"/dashboard/tasks/{t.id}/edit")
    assert resp.status_code == 200
    assert "Prepare AFS pack" in resp.data.decode()


def test_task_edit_post_valid_updates(client):
    """POST edit with changed fields updates the row and redirects to detail."""
    c = _make_client()
    s = _make_staff()
    t = Task(client_id=c.id, title="Old title", due_date=date(2026, 6, 30))
    db.session.add(t)
    db.session.commit()

    resp = client.post(
        f"/dashboard/tasks/{t.id}/edit",
        data={
            "client_id": str(c.id),
            "title": "New title",
            "due_date": "2026-08-15",
            "assignee_id": str(s.id),
        },
    )
    assert resp.status_code == 302

    db.session.refresh(t)
    assert t.title == "New title"
    assert t.due_date == date(2026, 8, 15)
    assert t.assignee_id == s.id


def test_task_edit_missing_task_returns_404(client):
    """GET edit for a non-existent task id returns 404."""
    resp = client.get("/dashboard/tasks/99999/edit")
    assert resp.status_code == 404
