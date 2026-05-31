from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    validators,
)


class TaskForm(FlaskForm):
    """Create/edit form for an ad-hoc task.

    Mirrors the dashboard forms' conventions: FlaskForm base for CSRF,
    dynamic SelectField choices populated per-request in the route (so the
    choices=[] defaults here are placeholders), and validate_choice=False on
    those selects because membership is validated in the route against the
    live client/staff lists rather than against a frozen choice set.
    """

    # Choices populated in the route from active clients.
    client_id = SelectField(
        "Client",
        choices=[],
        validate_choice=False,  # validated against live clients in the route
        validators=[validators.InputRequired()],
    )
    title = StringField(
        "Title",
        validators=[validators.InputRequired(), validators.Length(max=200)],
    )
    due_date = DateField(
        "Due date",
        validators=[validators.InputRequired()],
    )
    description = TextAreaField(
        "Description",
        validators=[validators.Optional(), validators.Length(max=4000)],
    )
    # Empty string ("") = Unassigned. Populated in the route handler from
    # active Staff plus the Unassigned sentinel.
    assignee_id = SelectField(
        "Assignee",
        choices=[],
        validate_choice=False,  # validated against active staff in the route
        validators=[validators.Optional()],
    )
    notes = TextAreaField(
        "Notes",
        validators=[validators.Optional(), validators.Length(max=4000)],
    )
    requested_by = StringField(
        "Requested by",
        validators=[validators.Optional(), validators.Length(max=120)],
    )
    submit = SubmitField("Save task")
