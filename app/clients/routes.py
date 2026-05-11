from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.clients.forms import ClientForm
from app.extensions import db
from app.models.client import Client, EntityType

bp = Blueprint("clients", __name__, url_prefix="/clients")


@bp.get("/")
def list_clients():
    clients = db.session.scalars(db.select(Client).order_by(Client.legal_name)).all()
    return render_template("clients/list.html", clients=clients)


@bp.route("/new", methods=["GET", "POST"])
def create_client():
    form = ClientForm()
    if form.validate_on_submit():
        try:
            client = Client(
                legal_name=form.legal_name.data,
                trading_name=form.trading_name.data or None,
                entity_type=EntityType[form.entity_type.data],
                registration_number=form.registration_number.data or None,
                tax_ref=form.tax_ref.data or None,
                vat_number=form.vat_number.data or None,
                paye_number=form.paye_number.data or None,
                year_end_month=form.year_end_month.data,
                year_end_day=form.year_end_day.data,
                bbee_applicable=form.bbee_applicable.data,
                client_since=form.client_since.data,
                has_income_tax=form.has_income_tax.data,
                has_vat=form.has_vat.data,
                has_paye=form.has_paye.data,
                has_provisional_tax=form.has_provisional_tax.data,
                has_dividends_tax=form.has_dividends_tax.data,
            )
        except ValueError as exc:
            flash(str(exc), "danger")
        else:
            db.session.add(client)
            db.session.commit()
            flash(f"{client.legal_name} added.", "success")
            return redirect(url_for("clients.list_clients"))
    return render_template("clients/form.html", form=form, title="New client", client=None)


@bp.route("/<int:client_id>/edit", methods=["GET", "POST"])
def edit_client(client_id: int):
    client = db.get_or_404(Client, client_id)
    form = ClientForm(obj=client)
    if request.method == "GET":
        # SelectField expects the enum name string, not the enum member
        form.entity_type.data = client.entity_type.name
    if form.validate_on_submit():
        try:
            client.legal_name = form.legal_name.data
            client.trading_name = form.trading_name.data or None
            client.entity_type = EntityType[form.entity_type.data]
            client.registration_number = form.registration_number.data or None
            client.tax_ref = form.tax_ref.data or None
            client.vat_number = form.vat_number.data or None
            client.paye_number = form.paye_number.data or None
            client.year_end_month = form.year_end_month.data
            client.year_end_day = form.year_end_day.data
            client.bbee_applicable = form.bbee_applicable.data
            client.client_since = form.client_since.data
            client.has_income_tax = form.has_income_tax.data
            client.has_vat = form.has_vat.data
            client.has_paye = form.has_paye.data
            client.has_provisional_tax = form.has_provisional_tax.data
            client.has_dividends_tax = form.has_dividends_tax.data
        except ValueError as exc:
            flash(str(exc), "danger")
        else:
            db.session.commit()
            flash(f"{client.legal_name} updated.", "success")
            return redirect(url_for("clients.list_clients"))
    return render_template("clients/form.html", form=form, title="Edit client", client=client)


@bp.post("/<int:client_id>/archive")
def archive_client(client_id: int):
    client = db.get_or_404(Client, client_id)
    client.active = False
    db.session.commit()
    flash(f"{client.legal_name} archived.", "info")
    return redirect(url_for("clients.list_clients"))
