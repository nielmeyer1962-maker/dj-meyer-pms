import calendar

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    validators,
)

from app.models.client import EntityType, VatCategory, VatSubmissionMethod


class ClientForm(FlaskForm):
    legal_name = StringField(
        "Legal name",
        validators=[validators.DataRequired(), validators.Length(max=200)],
    )
    trading_name = StringField(
        "Trading name",
        validators=[validators.Optional(), validators.Length(max=200)],
    )
    entity_type = SelectField(
        "Entity type",
        choices=[(e.name, e.value) for e in EntityType],
        validators=[validators.DataRequired()],
    )
    registration_number = StringField(
        "Registration number",
        validators=[validators.Optional(), validators.Length(max=50)],
    )
    tax_ref = StringField(
        "Income tax reference",
        validators=[validators.Optional(), validators.Length(max=50)],
    )
    vat_number = StringField(
        "VAT number",
        validators=[validators.Optional(), validators.Length(max=50)],
    )
    paye_number = StringField(
        "PAYE number",
        validators=[validators.Optional(), validators.Length(max=50)],
    )
    year_end_month = IntegerField(
        "Year-end month (1–12)",
        validators=[validators.Optional(), validators.NumberRange(min=1, max=12)],
    )
    year_end_day = IntegerField(
        "Year-end day (1–31)",
        validators=[validators.Optional(), validators.NumberRange(min=1, max=31)],
    )
    bbee_applicable = BooleanField("B-BBEE applicable")
    client_since = DateField("Date became a client", validators=[validators.Optional()])

    # Tax registrations
    has_income_tax = BooleanField("Income Tax")
    has_vat = BooleanField("VAT")
    has_paye = BooleanField("PAYE")
    has_provisional_tax = BooleanField("Provisional Tax")
    has_dividends_tax = BooleanField("Dividends Tax")

    vat_category = SelectField(
        "VAT category",
        choices=[("", "—")] + [(c.name, c.name) for c in VatCategory],
        validators=[validators.Optional()],
    )
    vat_submission_method = SelectField(
        "VAT submission method",
        choices=[
            ("", "—"),
            (VatSubmissionMethod.EFILING.name, "eFiling"),
            (VatSubmissionMethod.MANUAL.name, "Manual"),
        ],
        validators=[validators.Optional()],
    )

    submit = SubmitField("Save")

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            return False
        month = self.year_end_month.data
        day = self.year_end_day.data
        if (month is None) != (day is None):
            field = self.year_end_day if month is not None else self.year_end_month
            field.errors.append("Year-end month and day must both be set or both left blank.")
            return False
        if month is not None and day is not None:
            _, max_day = calendar.monthrange(2001, month)
            if day > max_day:
                self.year_end_day.errors.append(
                    f"Day {day} is invalid for month {month} (max {max_day})."
                )
                return False

        # VAT field invariants — mirror app/models/client.py _check_pairing_invariants:
        # has_vat=False forbids any VAT detail; pairing rule applies in all cases.
        cat = self.vat_category.data or None
        method = self.vat_submission_method.data or None
        if not self.has_vat.data and (cat or method):
            self.has_vat.errors.append(
                "VAT category and submission method must both be empty when VAT is not registered."
            )
            return False
        if (cat is None) != (method is None):
            target = self.vat_submission_method if cat else self.vat_category
            target.errors.append(
                "VAT category and submission method must both be set or both be empty."
            )
            return False

        return True
