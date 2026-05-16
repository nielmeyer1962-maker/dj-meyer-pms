from __future__ import annotations

from app.dashboard.forms import NotesForm

# --- NotesForm validation (Ticket 3c §C2) ---


def test_notes_form_accepts_empty(app):
    """Optional() lets the form validate when notes is missing or empty —
    blank notes is the common case and must not be a validation error."""
    with app.test_request_context(method="POST", data={"notes": ""}):
        form = NotesForm()
        assert form.validate()


def test_notes_form_accepts_normal_text(app):
    with app.test_request_context(
        method="POST", data={"notes": "Awaiting client signature on VAT201."}
    ):
        form = NotesForm()
        assert form.validate()


def test_notes_form_accepts_exactly_4000_chars(app):
    """4000 is the inclusive upper bound — Length(max=4000)."""
    with app.test_request_context(method="POST", data={"notes": "a" * 4000}):
        form = NotesForm()
        assert form.validate()


def test_notes_form_rejects_over_4000_chars(app):
    """4001 chars must fail with a Length-validation error on the notes field."""
    with app.test_request_context(method="POST", data={"notes": "a" * 4001}):
        form = NotesForm()
        assert not form.validate()
        assert "notes" in form.errors
