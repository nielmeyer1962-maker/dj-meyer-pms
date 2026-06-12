"""`flask staff …` CLI for credential management — there is no self-registration, so
passwords and admin rights are set here by an operator."""

from __future__ import annotations

import click
from flask.cli import AppGroup

from app.extensions import db
from app.models.staff import Staff

staff_cli = AppGroup("staff", help="Manage staff credentials.")

_MIN_PASSWORD_LEN = 10


def _require_staff(email: str) -> Staff:
    staff = db.session.scalar(db.select(Staff).where(Staff.email == email))
    if staff is None:
        raise click.ClickException(f"No staff member with email {email!r}.")
    return staff


@staff_cli.command("set-password")
@click.argument("email")
def set_password(email: str) -> None:
    """Set EMAIL's login password (prompts twice, hidden)."""
    staff = _require_staff(email)
    password = click.prompt("New password", hide_input=True, confirmation_prompt=True)
    if len(password) < _MIN_PASSWORD_LEN:
        raise click.ClickException(f"Password must be at least {_MIN_PASSWORD_LEN} characters.")
    staff.set_password(password)
    db.session.commit()
    click.echo(f"Password set for {staff.code} <{email}>.")


@staff_cli.command("set-admin")
@click.argument("email")
@click.option("--on/--off", "make_admin", default=None, help="Grant or revoke admin.")
def set_admin(email: str, make_admin: bool | None) -> None:
    """Grant (--on) or revoke (--off) admin rights for EMAIL."""
    if make_admin is None:
        raise click.ClickException("Specify --on or --off.")
    staff = _require_staff(email)
    staff.is_admin = make_admin
    db.session.commit()
    state = "granted" if make_admin else "revoked"
    click.echo(f"Admin {state} for {staff.code} <{email}>.")
