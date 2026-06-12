"""Admin authorisation helpers. Authentication (being logged in) is handled by the global
login wall in create_app; this layer is the second gate: is the logged-in staff an admin."""

from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user


def is_admin() -> bool:
    return current_user.is_authenticated and bool(getattr(current_user, "is_admin", False))


def require_admin() -> None:
    """Abort 403 unless the current user is an admin. Use from a blueprint before_request
    to guard an ENTIRE blueprint (so a future route can't be added unguarded)."""
    if not is_admin():
        abort(403)


def admin_required(view):
    """Decorator form, for guarding a single view."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        require_admin()
        return view(*args, **kwargs)

    return wrapped
