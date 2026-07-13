from __future__ import annotations

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from app.auth.decorators import require_admin
from app.extensions import db
from app.models.app_setting import (
    DEFAULT_ITR12_NONPROVISIONAL,
    DEFAULT_ITR12_PROVISIONAL,
    KEY_ITR12_NONPROVISIONAL_DAY,
    KEY_ITR12_NONPROVISIONAL_MONTH,
    KEY_ITR12_PROVISIONAL_DAY,
    KEY_ITR12_PROVISIONAL_MONTH,
)
from app.services.settings import get_setting_int, set_setting
from app.settings.forms import ITR12DeadlinesForm

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.before_request
def _settings_requires_admin() -> Response | None:
    """Guard the WHOLE settings blueprint: every current and future route is admin-only,
    so a new settings view can never be added unguarded by accident. Returning the result
    lets require_admin's flash+redirect take effect for non-admins."""
    return require_admin()


def _current_or_default(key: str, default: int) -> int:
    """Read a setting as int, falling back to the seeded default if the key is missing —
    so the page always renders even on a DB that predates the seed."""
    try:
        return get_setting_int(key)
    except KeyError:
        return default


@bp.route("/", methods=["GET", "POST"])
def edit_settings():
    form = ITR12DeadlinesForm()
    if form.validate_on_submit():
        set_setting(KEY_ITR12_NONPROVISIONAL_DAY, str(form.nonprovisional_day.data))
        set_setting(KEY_ITR12_NONPROVISIONAL_MONTH, str(form.nonprovisional_month.data))
        set_setting(KEY_ITR12_PROVISIONAL_DAY, str(form.provisional_day.data))
        set_setting(KEY_ITR12_PROVISIONAL_MONTH, str(form.provisional_month.data))
        db.session.commit()
        flash("ITR12 deadlines updated.", "success")
        return redirect(url_for("settings.edit_settings"))

    if request.method == "GET":
        form.nonprovisional_day.data = _current_or_default(
            KEY_ITR12_NONPROVISIONAL_DAY, DEFAULT_ITR12_NONPROVISIONAL.day
        )
        form.nonprovisional_month.data = _current_or_default(
            KEY_ITR12_NONPROVISIONAL_MONTH, DEFAULT_ITR12_NONPROVISIONAL.month
        )
        form.provisional_day.data = _current_or_default(
            KEY_ITR12_PROVISIONAL_DAY, DEFAULT_ITR12_PROVISIONAL.day
        )
        form.provisional_month.data = _current_or_default(
            KEY_ITR12_PROVISIONAL_MONTH, DEFAULT_ITR12_PROVISIONAL.month
        )

    return render_template("settings/form.html", form=form)
