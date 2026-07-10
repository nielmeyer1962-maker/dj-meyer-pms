from __future__ import annotations

from app.extensions import db
from app.models.staff import Staff, StaffRole


def _seed(app, *, email="cli@test.local", is_admin=False) -> None:
    with app.app_context():
        s = Staff(
            code="CLI", full_name="CLI User", email=email, role=StaffRole.TAX, is_admin=is_admin
        )
        db.session.add(s)
        db.session.commit()


def test_set_password_sets_a_working_hash(app):
    _seed(app)
    result = app.test_cli_runner().invoke(
        args=["staff", "set-password", "cli@test.local"],
        input="longenough123\nlongenough123\n",
    )
    assert result.exit_code == 0, result.output
    assert "Password set" in result.output
    with app.app_context():
        s = db.session.scalar(db.select(Staff).where(Staff.email == "cli@test.local"))
        assert s.check_password("longenough123")


def test_set_password_rejects_short_password(app):
    _seed(app)
    result = app.test_cli_runner().invoke(
        args=["staff", "set-password", "cli@test.local"],
        input="short\nshort\n",
    )
    assert result.exit_code != 0
    assert "at least 10" in result.output
    with app.app_context():
        s = db.session.scalar(db.select(Staff).where(Staff.email == "cli@test.local"))
        assert s.password_hash is None


def test_set_password_unknown_email_errors(app):
    result = app.test_cli_runner().invoke(
        args=["staff", "set-password", "nobody@test.local"],
        input="longenough123\nlongenough123\n",
    )
    assert result.exit_code != 0
    assert "No staff member" in result.output


def test_set_admin_on_and_off(app):
    _seed(app)
    on = app.test_cli_runner().invoke(args=["staff", "set-admin", "cli@test.local", "--on"])
    assert on.exit_code == 0
    with app.app_context():
        assert db.session.scalar(db.select(Staff).where(Staff.email == "cli@test.local")).is_admin

    off = app.test_cli_runner().invoke(args=["staff", "set-admin", "cli@test.local", "--off"])
    assert off.exit_code == 0
    with app.app_context():
        assert not db.session.scalar(
            db.select(Staff).where(Staff.email == "cli@test.local")
        ).is_admin


def test_set_admin_requires_a_flag(app):
    _seed(app)
    result = app.test_cli_runner().invoke(args=["staff", "set-admin", "cli@test.local"])
    assert result.exit_code != 0
    assert "Specify --on or --off" in result.output


def test_set_admin_unknown_email_errors(app):
    result = app.test_cli_runner().invoke(args=["staff", "set-admin", "nobody@test.local", "--on"])
    assert result.exit_code != 0
    assert "No staff member" in result.output
