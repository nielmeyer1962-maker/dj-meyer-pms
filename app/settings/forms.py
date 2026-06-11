from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import IntegerField, SubmitField
from wtforms.validators import DataRequired, NumberRange


class ITR12DeadlinesForm(FlaskForm):
    """The two ITR12 filing deadlines, each a day-of-month + month. Ranges mirror
    DeadlineDM (day 1-31, month 1-12); day-vs-month-length is left to the generator's
    clamp, since these are recurring day+month values, not a concrete date."""

    nonprovisional_day = IntegerField(
        "Day", validators=[DataRequired(), NumberRange(min=1, max=31)]
    )
    nonprovisional_month = IntegerField(
        "Month", validators=[DataRequired(), NumberRange(min=1, max=12)]
    )
    provisional_day = IntegerField("Day", validators=[DataRequired(), NumberRange(min=1, max=31)])
    provisional_month = IntegerField(
        "Month", validators=[DataRequired(), NumberRange(min=1, max=12)]
    )
    submit = SubmitField("Save deadlines")
