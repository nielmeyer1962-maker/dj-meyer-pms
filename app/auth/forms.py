from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length


class LoginForm(FlaskForm):
    """Email + password. No length/shape validators beyond presence — the login route
    returns one generic error for any failure, so the form never reveals which field was
    wrong."""

    email = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in")


class AccountPasswordForm(FlaskForm):
    """A logged-in staff member changing their own password. Current password is required
    (so a hijacked session can't silently reset it); new password min length 10 to match
    the CLI."""

    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField("New password", validators=[DataRequired(), Length(min=10)])
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")],
    )
    submit = SubmitField("Change password")
