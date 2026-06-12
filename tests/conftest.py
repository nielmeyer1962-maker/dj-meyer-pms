import os

import pytest
from flask.testing import FlaskClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.config import Config
from app.extensions import db as _db
from app.models.staff import Staff, StaffRole

# Shared password for every fixture-created auth staff member.
_TEST_PASSWORD = "fixture-password-123"


def _make_auth_staff(*, code: str, email: str, is_admin: bool) -> Staff:
    """Create + persist an active staff member who can log in (has a password hash)."""
    s = Staff(
        code=code,
        full_name=f"{code} Test User",
        email=email,
        role=StaffRole.TAX,
        is_admin=is_admin,
        active=True,
    )
    s.set_password(_TEST_PASSWORD)
    _db.session.add(s)
    _db.session.commit()
    return s


def _logged_in_client(app, *, code: str, email: str, is_admin: bool) -> FlaskClient:
    _make_auth_staff(code=code, email=email, is_admin=is_admin)
    c = app.test_client()
    resp = c.post("/login", data={"email": email, "password": _TEST_PASSWORD})
    # 302 → landed past the login wall; anything else means login silently failed.
    assert resp.status_code == 302, f"fixture login failed: {resp.status_code}"
    return c


class TestConfig(Config):
    TESTING = True
    # Run on real Postgres when TEST_DATABASE_URL is set (CI), else SQLite in-memory
    # (the local default — fast, zero-setup).
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    WTF_CSRF_ENABLED = False


# SQLite ignores foreign-key constraints unless explicitly enabled per connection.
# Without this, ON DELETE SET NULL and ON DELETE RESTRICT are schema-only and
# never fire at runtime — exactly what we need to assert in tests. CI uses
# Postgres, which enforces FKs unconditionally; the dialect check keeps the
# PRAGMA from being issued to psycopg2.
@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):  # pragma: no cover
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()


@pytest.fixture
def app():
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        # Drop the scoped session before drop_all. The fixture holds one app context open
        # across the whole test, so a request made via the test client reuses it and
        # Flask-SQLAlchemy's teardown_appcontext never fires — leaving the session's
        # connection idle-in-transaction. On Postgres that open transaction holds a lock
        # that blocks DROP TABLE indefinitely; SQLite never enforced it. Removing the
        # session here rolls it back and frees the connection before teardown.
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app) -> FlaskClient:
    """Authenticated as an ordinary (non-admin) staff member, so the existing route suite
    runs behind the login wall untouched."""
    return _logged_in_client(app, code="AUTH", email="auth@test.local", is_admin=False)


@pytest.fixture
def anon_client(app) -> FlaskClient:
    """No login — for the auth tests themselves (redirects, bad credentials, etc.)."""
    return app.test_client()


@pytest.fixture
def admin_client(app) -> FlaskClient:
    """Authenticated as an admin staff member — for admin-gate tests (chunk 4)."""
    return _logged_in_client(app, code="ADMIN", email="admin@test.local", is_admin=True)
