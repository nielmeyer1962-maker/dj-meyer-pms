from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField, TextAreaField, validators


class ReassignForm(FlaskForm):
    """Reassignment form rendered inside the shared dashboard modal.

    Choices are populated dynamically per-request in the route because the
    active-staff list changes over time; the choices=[] default here is a
    placeholder. CSRF lives on this form so the same hidden_tag() that the
    per-row mark-* mini-forms use can be reused inside the modal.
    """

    # Empty string ("") = Unassigned. Populated in the route handler from
    # active Staff plus the Unassigned sentinel.
    assignee_id = SelectField(
        "Assignee",
        choices=[],
        validate_choice=False,  # we validate against active staff in the route
    )
    submit = SubmitField("Reassign")


class NotesForm(FlaskForm):
    """Free-text notes textarea on the obligation detail page.

    4000-char soft cap (PROJECT_PLAN.md §C2): well over a screen of prose,
    stops accidental megabyte pastes, adjustable later without a migration
    because the DB column is `Text`.
    """

    notes = TextAreaField(
        "Notes",
        validators=[validators.Optional(), validators.Length(max=4000)],
    )
    submit = SubmitField("Save notes")
