"""Admin authorisation helpers. Authentication (being logged in) is handled by the global
login wall in create_app; this layer is the second gate: is the logged-in staff an admin."""

from __future__ import annotations

from functools import wraps

from flask import Response, flash, redirect, url_for
from flask_login import current_user

# Shown (as a flash) whenever a non-admin is turned away from an admin-only action, so the
# rejection is visible instead of a bare 403 page — even on the direct-URL / stale-page path.
ADMIN_REQUIRED_MESSAGE = "You need admin rights to do that."


def is_admin() -> bool:
    return current_user.is_authenticated and bool(getattr(current_user, "is_admin", False))


def require_admin() -> Response | None:
    """Flash + redirect to the dashboard for a non-admin; return None if the user is an admin.

    Callers MUST return the result so the redirect takes effect — from a blueprint
    before_request (`return require_admin()`) this guards the WHOLE blueprint, so a future
    route can't be added unguarded. Redirecting (rather than abort 403) means every
    admin-gated route inherits a visible rejection message automatically."""
    if is_admin():
        return None
    flash(ADMIN_REQUIRED_MESSAGE, "danger")
    return redirect(url_for("dashboard.list_obligations"))


def admin_required(view):
    """Decorator form, for guarding a single view — inherits require_admin's flash+redirect."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        denied = require_admin()
        if denied is not None:
            return denied
        return view(*args, **kwargs)

    return wrapped
