from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.auth.forms import AccountPasswordForm, LoginForm
from app.extensions import db, login_manager
from app.models.staff import Staff

bp = Blueprint("auth", __name__)


@login_manager.user_loader
def load_user(user_id: str) -> Staff | None:
    return db.session.get(Staff, int(user_id))


def _is_safe_next(target: str | None) -> bool:
    """Only honour same-origin relative redirects — never an absolute/cross-host URL."""
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and target.startswith("/")


@bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        staff = db.session.scalar(db.select(Staff).where(Staff.email == form.email.data))
        # One generic failure for every case — wrong email, wrong password, inactive, or
        # no password set — so we never reveal which part was wrong.
        if staff is not None and staff.active and staff.check_password(form.password.data):
            login_user(staff)
            next_url = request.args.get("next")
            if _is_safe_next(next_url):
                return redirect(next_url)
            return redirect(url_for("dashboard.list_obligations"))
        flash("Invalid email or password.", "danger")

    return render_template("auth/login.html", form=form)


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def account_password():
    form = AccountPasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            form.current_password.errors.append("Current password is incorrect.")
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash("Your password has been changed.", "success")
            return redirect(url_for("auth.account_password"))
    return render_template("auth/account_password.html", form=form)
